#!/usr/bin/env python3
"""Collect measurable facts about ONE page (no model involved, stdlib only).

Usage:
    python3 -I facts.py <url> [--out facts.json] [--ua "UserAgent"]

What it records (all read-only GET/HEAD requests):
  - HTTP: status, redirect chain, TTFB, size, compression, cache and security headers
  - Head: title, meta description, canonical, robots meta, viewport, lang, Open Graph, Twitter, hreflang
  - Structure: headings outline, images (alt, lazy), links (internal/external/empty/generic anchors),
    forms, buttons and calls to action, JSON-LD types, visible word count
  - Third parties: script hosts, tracking and consent tools detected in the HTML
  - Site level: robots.txt, sitemaps, llms.txt, http->https and www redirects, soft-404 test
"""
import argparse
import codecs
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import botwall  # noqa: E402
import robotsrules  # noqa: E402
import safenet  # noqa: E402

DEFAULT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36 SiteAuditSkill/1.0"
GENERIC_ANCHORS = {
    "click here", "here", "read more", "learn more", "more", "en savoir plus", "cliquez ici", "ici",
    "lire la suite", "voir plus", "plus d'infos", "details", "détails", "link", "lien",
}
TRACKERS = {
    "google-tag-manager": r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]+",
    "google-analytics/gtag": r"googletagmanager\.com/gtag/js|gtag\(",
    "meta-pixel": r"connect\.facebook\.net|fbq\(",
    "posthog": r"posthog\.(?:com|init|js)|\bposthog\b|/static/array\.js",
    "plausible": r"plausible\.io|plausible\.js",
    "matomo": r"matomo\.(?:js|php|cloud)|/matomo/|piwik\.(?:js|php)|/piwik/|_paq\.push",
    "hotjar": r"hotjar\.com",
    "clarity": r"clarity\.ms",
    "linkedin-insight": r"snap\.licdn\.com|_linkedin_partner_id",
    "tiktok-pixel": r"analytics\.tiktok\.com",
}
CONSENT = {
    "complianz": r"cmplz|complianz",
    "cookiebot": r"cookiebot",
    "onetrust": r"onetrust|optanon",
    "didomi": r"didomi",
    "axeptio": r"axeptio",
    "tarteaucitron": r"tarteaucitron",
    "cookieyes": r"cookieyes|(?<![a-z0-9])cky-",
    "iubenda": r"iubenda",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(NoRedirect)
MAX_BODY = 8_000_000
ERROR_BODY_MAX = 65536          # a protection page is small; this is all that is read of a 4xx or 5xx body


def _charset(hdrs, raw):
    """Charset announced by the server, else by the page itself, else utf-8."""
    m = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_\-]+)", hdrs.get("content-type", ""), re.I)
    if not m:
        m = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([A-Za-z0-9_\-]+)", raw[:4096], re.I)
        name = m.group(1).decode("ascii", "ignore") if m else ""
    else:
        name = m.group(1)
    try:
        return codecs.lookup(name).name if name else "utf-8"
    except LookupError:
        return "utf-8"


def decode_body(raw, hdrs):
    return raw.decode(_charset(hdrs, raw), "replace")


def _gunzip(raw, limit):
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw, limit + 1)
    return out[:limit], len(out) > limit


def _read_by_deadline(resp, limit, seconds):
    """Read at most `limit` bytes, and for at most `seconds` in total. `timeout` of urllib is per socket read: a
    server sending one byte every few seconds would otherwise hold the audit for as long as it likes."""
    end, chunks, got = time.monotonic() + seconds, [], 0
    while got < limit:
        if time.monotonic() > end:
            return b"".join(chunks), True
        chunk = resp.read1(min(65536, limit - got))   # read1: whatever has arrived, so the clock is looked at between bursts
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks), False


def to_uri(url):
    """Percent-encode what urllib cannot send as is (accents and spaces in the path or query, a non-ASCII host name)."""
    try:
        p = urllib.parse.urlsplit(url)
        netloc = p.netloc
        if any(ord(c) > 127 for c in netloc):
            host = p.hostname or ""
            port = f":{p.port}" if p.port else ""
            netloc = host.encode("idna").decode("ascii") + port
        path = urllib.parse.quote(p.path, safe="/%:@!$&'()*+,;=~-._")
        query = urllib.parse.quote(p.query, safe="=&%:@!$'()*+,;/?~-._")
        return urllib.parse.urlunsplit((p.scheme, netloc, path, query, ""))
    except (ValueError, UnicodeError):
        return url


def _open_by_deadline(req, timeout, total):
    """`timeout` of urllib is per socket read, and covers neither a status line nor headers that arrive one byte at a
    time. The call runs in a thread we stop waiting for after `total` seconds (the thread ends with the process)."""
    box = {}

    def run():
        try:
            box["r"] = _opener.open(req, timeout=timeout)
        except BaseException as e:  # noqa: BLE001 - handed back to the caller
            box["e"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(total)
    if t.is_alive():
        raise TimeoutError(f"no complete response head after {total} s")
    if "e" in box:
        raise box["e"]
    return box["r"]


def _result(status, hdrs, body, nbytes, final, chain, ttfb, error, truncated=False):
    return {"status": status, "headers": hdrs, "body": body, "bytes": nbytes, "final_url": final,
            "chain": chain, "ttfb_ms": ttfb, "error": error, "truncated": truncated}


def fetch(url, ua, method="GET", max_hops=6, timeout=30, want_body=True, max_bytes=MAX_BODY, allow_private=None, gunzip_file=False, hop_check=None, error_body=False):
    """GET following redirects manually. Returns dict with chain, status, headers, body, ttfb_ms.

    Every hop goes through safenet.check(): only http(s), and a public start URL never leads to a private
    address. `allow_private=None` means: allowed only when the start URL is itself local or private.
    The body is read up to `max_bytes` (then `truncated` is true), whatever the server sends, and the whole head of
    the response must arrive within `timeout` seconds. `hop_check(url)` may return a reason to refuse a redirect target
    (the crawler uses it to keep to robots.txt after a redirect). `error_body=True` also keeps the first bytes of the
    body of a 4xx or 5xx answer (a bot-protection page says what it is there); otherwise that body is dropped.
    """
    chain = []
    cur = url
    t0 = time.time()
    ttfb = None
    if allow_private is None:
        allow_private = safenet.default_allow_private(url)
    for _ in range(max_hops + 1):
        why = safenet.check(cur, allow_private)
        if why:
            return _result(0, {}, "", 0, cur, chain, ttfb, why)
        req = urllib.request.Request(to_uri(cur), method=method, headers={
            "User-Agent": ua, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Encoding": "gzip", "Accept-Language": "fr,en;q=0.8"})
        try:
            r = _open_by_deadline(req, timeout, timeout)
            status, hdrs = r.status, {k.lower(): v for k, v in r.headers.items()}
            ttfb = ttfb if ttfb is not None else round((time.time() - t0) * 1000)
            raw, slow = _read_by_deadline(r, max_bytes + 1, timeout) if (want_body and method == "GET") else (b"", False)
            truncated = len(raw) > max_bytes or slow
            raw = raw[:max_bytes]
            body = raw
            if hdrs.get("content-encoding", "").strip().lower() == "gzip" or (gunzip_file and raw[:2] == b"\x1f\x8b"):
                try:
                    body, more = _gunzip(raw, max_bytes)
                    truncated = truncated or more
                except Exception:
                    body = raw
            return _result(status, hdrs, decode_body(body, hdrs), len(raw), cur, chain, ttfb, None, truncated)
        except urllib.error.HTTPError as e:
            status, hdrs = e.code, {k.lower(): v for k, v in e.headers.items()}
            err_body = ""
            if error_body and want_body and method == "GET" and status >= 400:
                try:
                    raw_err, _ = _read_by_deadline(e, ERROR_BODY_MAX, 5)
                    if hdrs.get("content-encoding", "").strip().lower() == "gzip":
                        raw_err, _ = _gunzip(raw_err, ERROR_BODY_MAX)
                    err_body = decode_body(raw_err, hdrs)
                except Exception:
                    err_body = ""
            e.close()
            ttfb = ttfb if ttfb is not None else round((time.time() - t0) * 1000)
            if status in (301, 302, 303, 307, 308) and hdrs.get("location"):
                nxt = urllib.parse.urljoin(cur, hdrs["location"])
                chain.append({"url": cur, "status": status, "to": nxt})
                refusal = hop_check(nxt) if hop_check else None
                if refusal:
                    return _result(0, {}, "", 0, cur, chain, ttfb, refusal)
                cur = nxt
                continue
            return _result(status, hdrs, err_body, len(err_body), cur, chain, ttfb, None)
        except Exception as e:  # network, TLS, timeout
            return _result(0, {}, "", 0, cur, chain, ttfb, f"{type(e).__name__}: {e}")
    return _result(0, {}, "", 0, cur, chain, ttfb, "too many redirects")


class PageParser(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.host = urllib.parse.urlparse(base).netloc.lower().removeprefix("www.")
        self.title = None
        self._in_title = False
        self._in_svg = 0
        self.meta = {}
        self.links_head = []
        self.headings = []  # (level, text)
        self._h = None
        self.images = []
        self.links = []
        self._a = None
        self.forms = []
        self._form = None
        self.buttons = []
        self._btn = None
        self.scripts = []
        self.inline_script_bytes = 0
        self._in_script = False
        self._script_ld = False
        self._script_buf = []
        self.jsonld_raw = []
        self.stylesheets = 0
        self.text = []
        self._skip = 0
        self.html_lang = None
        self.has_doctype = False
        self.charset = None
        self.iframes = 0
        self.videos = 0
        self.tel_mailto = 0

    def handle_decl(self, decl):
        if decl.lower().startswith("doctype"):
            self.has_doctype = True

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "svg":
            self._in_svg += 1
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "title" and self.title is None and not self._in_svg:
            self._in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
            if a.get("charset"):
                self.charset = a["charset"]
        elif tag == "link":
            self.links_head.append(a)
            if "stylesheet" in a.get("rel", "").lower():
                self.stylesheets += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self._h = [int(tag[1]), []]
        elif tag == "img":
            self.images.append(a)
        elif tag == "a":
            self._a = {"href": a.get("href"), "rel": a.get("rel", ""), "text": [], "aria": a.get("aria-label", "")}
            if (a.get("href") or "").startswith(("tel:", "mailto:")):
                self.tel_mailto += 1
        elif tag == "form":
            self._form = {"action": a.get("action", ""), "method": a.get("method", "get").lower(), "fields": 0, "labels": 0, "required": 0}
            self.forms.append(self._form)
        elif tag in ("input", "select", "textarea") and self._form is not None:
            if a.get("type", "text").lower() not in ("hidden", "submit", "button"):
                self._form["fields"] += 1
                if "required" in a or a.get("aria-required") == "true":
                    self._form["required"] += 1
        elif tag == "label" and self._form is not None:
            self._form["labels"] += 1
        elif tag == "button":
            self._btn = []
        elif tag == "script":
            self._in_script = True
            self._script_ld = "ld+json" in a.get("type", "").lower()
            self._script_buf = []
            self._script_has_src = bool(a.get("src"))
            if a.get("src"):
                self.scripts.append(a["src"])
        elif tag in ("style", "noscript", "template"):
            self._skip += 1
        elif tag == "iframe":
            self.iframes += 1
        elif tag == "video":
            self.videos += 1

    def handle_endtag(self, tag):
        if tag == "svg" and self._in_svg:
            self._in_svg -= 1
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4") and self._h:
            self.headings.append((self._h[0], " ".join("".join(self._h[1]).split())))
            self._h = None
        elif tag == "a" and self._a is not None:
            self._a["text"] = " ".join("".join(self._a["text"]).split())
            self.links.append(self._a)
            self._a = None
        elif tag == "button" and self._btn is not None:
            self.buttons.append(" ".join("".join(self._btn).split()))
            self._btn = None
        elif tag == "script":
            if self._script_ld:
                self.jsonld_raw.append("".join(self._script_buf))
            elif not getattr(self, "_script_has_src", False):
                self.inline_script_bytes += len("".join(self._script_buf).encode())
            self._in_script = False
            self._script_ld = False
        elif tag in ("style", "noscript", "template") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        if self._in_script:
            self._script_buf.append(data)
            return
        if self._skip:
            return
        if self._h is not None:
            self._h[1].append(data)
        if self._a is not None:
            self._a["text"].append(data)
        if self._btn is not None:
            self._btn.append(data)
        self.text.append(data)


def jsonld_types(raws):
    types, invalid = set(), 0

    def walk(x):
        if isinstance(x, dict):
            t = x.get("@type")
            if t:
                types.update(t if isinstance(t, list) else [t])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for raw in raws:
        try:
            walk(json.loads(raw))
        except Exception:
            invalid += 1
    return sorted(types), invalid


NON_CODE_SCRIPT = re.compile(r"type\s*=\s*[\"']?(?:application/(?:ld\+)?json|text/template|text/html|importmap|speculationrules)", re.I)


def code_surface(html):
    """What a tracker or a consent tool shows up in: tags and attributes, and executable script bodies.

    Visible text, JSON-LD and other data blocks are left out, so an article that merely talks about Matomo
    or a class named `sticky-nav` is not read as an installed tool.
    """
    bodies = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.I | re.S):
        if not NON_CODE_SCRIPT.search(m.group(1)):
            bodies.append(m.group(2))
    # a plain link to hotjar.com or posthog.com is not an installed tool: <a> tags are left out
    tags = [t for t in re.findall(r"<[a-zA-Z][^>]*>", html) if not re.match(r"<a\b", t, re.I)]
    return "\n".join(tags + bodies)


def mixed_content_count(html):
    """Resources an https page loads over http: images, scripts, frames, media, stylesheets, icons. A link to an http page is not one."""
    n = len(re.findall(r"""url\(\s*["']?http://(?!www\.w3\.org)""", html, re.I)) + len(re.findall(r"""@import\s+(?:url\(\s*)?["']?http://""", html, re.I))
    for t in re.findall(r"<(?:img|script|iframe|source|video|audio|embed|object|link)\b[^>]*>", html, re.I):
        is_link = t[:5].lower() == "<link"
        if is_link and not re.search(r"""rel=["']?[^"'>]*(?:stylesheet|preload|icon)""", t, re.I):
            continue
        if is_link:
            if re.search(r"""\bhref=["']?\s*http://""", t, re.I):
                n += 1
            continue
        urls = []
        for m in re.finditer(r"""(?<![\w-])(?:src|data|poster)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""", t, re.I):
            urls.append(next(g for g in m.groups() if g is not None))
        for m in re.finditer(r"""\bsrcset=(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""", t, re.I):
            val = next(g for g in m.groups() if g is not None)
            urls += [cand.strip().split()[0] for cand in val.split(",") if cand.strip()]
        if any(re.match(r"\s*http://(?!www\.w3\.org)", u, re.I) for u in urls):
            n += 1
    return n


AI_ROBOTS = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "Claude-User", "PerplexityBot",
             "Perplexity-User", "CCBot", "Google-Extended", "Applebot-Extended", "Bytespider")


def robots_disallows_all(robots_body, token="SiteAuditSkill"):
    """True when the rules that apply to this crawler close the whole site (`Disallow: /` or `/*`, and no Allow rule).
    Same parser as the crawler (robotsrules): the group for the crawler's own name wins over `*`."""
    rb = robotsrules.Robots(200, robots_body or "", token)
    return not any(rb.allowed(p) for p in ("/", "/index.html", "/a", "/a/b/c", "/blog/post-1")) and not any(allow for _, allow, _ in rb.rules)


def ai_robot_decisions(status, robots_body):
    """For each known AI crawler: may it fetch `/`? Google-Extended and Applebot-Extended are robots.txt tokens (a control
    for AI use), not crawlers with their own traffic. No robots.txt (4xx) allows all; 5xx closes everything."""
    out = {}
    for tok in AI_ROBOTS:
        rb = robotsrules.Robots(status, robots_body or "", tok)
        out[tok] = {"allowed_on_root": rb.allowed("/"), "own_group": rb.own_group}
    return out


def same_url(a, b):
    """Same page, ignoring a trailing slash, the case of scheme and host, and the fragment."""
    def norm(u):
        x = urllib.parse.urlparse(u)
        return (x.scheme.lower(), x.netloc.lower(), x.path.rstrip("/") or "/", x.query)
    return norm(a) == norm(b)


def probe(base, path, ua):
    r = fetch(base + path, ua, timeout=15)
    body = r["body"] if r["status"] == 200 else ""
    return {"status": r["status"], "bytes": len(body), "final_url": r["final_url"], "head": body[:160].replace("\n", " ") or None}


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    safenet.private_output(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out")
    ap.add_argument("--ua", default=DEFAULT_UA)
    args = ap.parse_args()
    url = safenet.start_url(args.url)
    if not urllib.parse.urlparse(url).path:
        url += "/"

    r = fetch(url, args.ua, error_body=True)
    bw = botwall.detect(r["status"], r["headers"], r["body"]) if not r["error"] else None
    f = {"url": url, "final_url": r["final_url"], "status": r["status"], "error": r["error"],
         "redirect_chain": r["chain"], "ttfb_ms": r["ttfb_ms"], "html_bytes_transferred": r["bytes"], "html_truncated": bool(r.get("truncated"))}
    if bw:
        f["bot_wall"] = bw
    if r["error"] or r["status"] >= 400 or (bw and bw["confidence"] == "high"):
        out = json.dumps(f, ensure_ascii=False, indent=2)
        (_write(args.out, out) if args.out else print(out))
        if bw:
            print(f"page not audited: {botwall.one_line(bw)}. {botwall.GUIDANCE}", file=sys.stderr)
        else:
            print(f"page unreachable: status={r['status']} error={r['error']}", file=sys.stderr)
        return 1

    if bw:
        print(f"warning: {botwall.one_line(bw)} (confidence {bw['confidence']}). Look at the screens before you trust this page.", file=sys.stderr)
    html = r["body"]
    h = r["headers"]
    p = PageParser(r["final_url"])
    p.feed(html)
    parsed = urllib.parse.urlparse(r["final_url"])
    base = f"{parsed.scheme}://{parsed.netloc}"
    site_host = parsed.netloc.lower().removeprefix("www.")

    canon = next((l.get("href") for l in p.links_head if "canonical" in l.get("rel", "").lower()), None)
    canon_abs = urllib.parse.urljoin(r["final_url"], canon) if canon else None
    surface = code_surface(html)
    hreflang = [l.get("hreflang") for l in p.links_head if l.get("rel", "").lower() == "alternate" and l.get("hreflang")]
    title = " ".join((p.title or "").split()) or None
    desc = p.meta.get("description")
    words = len(re.findall(r"\w+", " ".join(p.text)))
    h1s = [t for lv, t in p.headings if lv == 1]
    outline = [{"level": lv, "text": t[:120]} for lv, t in p.headings][:60]

    internal = external = empty = generic = nofollow = 0
    ext_hosts = {}
    for a in p.links:
        href = (a["href"] or "").strip()
        if not href or href == "#" or href.lower().startswith("javascript:"):
            empty += 1
            continue
        if href.startswith(("tel:", "mailto:")):
            continue
        target = urllib.parse.urlparse(urllib.parse.urljoin(r["final_url"], href))
        if target.netloc.lower().removeprefix("www.") == site_host:
            internal += 1
        else:
            external += 1
            ext_hosts[target.netloc] = ext_hosts.get(target.netloc, 0) + 1
        txt = (a["text"] or a["aria"]).strip().lower()
        if txt in GENERIC_ANCHORS:
            generic += 1
        if "nofollow" in a["rel"].lower():
            nofollow += 1

    imgs = p.images
    script_hosts = {}
    for s in p.scripts:
        sh = urllib.parse.urlparse(urllib.parse.urljoin(r["final_url"], s)).netloc.lower()
        if sh and sh.removeprefix("www.") != site_host:
            script_hosts[sh] = script_hosts.get(sh, 0) + 1
    types, invalid_ld = jsonld_types(p.jsonld_raw)
    cta_words = re.compile(r"(rejoindre|essayer|commencer|réserver|reserver|acheter|télécharger|telecharger|s'inscrire|inscription|demander|contact|devis|obtenir|get started|sign up|try|buy|book|download|join|start|subscribe)", re.I)
    def cta_text(t):
        if not t:
            return None
        if len(t) < 60:
            return t if cta_words.search(t) else None
        m = cta_words.search(t)  # long card-like links: keep the phrase around the call to action word
        return t[m.start(): m.start() + 40].strip() if m else None
    ctas = [x for x in (cta_text(t) for t in ([a["text"] for a in p.links] + p.buttons)) if x]
    seen, cta_unique = set(), []
    for t in ctas:
        if t.lower() not in seen:
            seen.add(t.lower())
            cta_unique.append(t)

    f.update({
        "title": title, "title_len": len(title) if title else 0,
        "meta_description": desc, "meta_description_len": len(desc) if desc else 0,
        "canonical": canon, "canonical_resolved": canon_abs,
        "canonical_is_self": (same_url(canon_abs, r["final_url"])) if canon else None,
        "html_lang": p.html_lang, "doctype": p.has_doctype, "charset": p.charset,
        "meta_robots": p.meta.get("robots"), "viewport": p.meta.get("viewport"),
        "hreflang": hreflang,
        "open_graph": sorted(k for k in p.meta if k.startswith("og:")),
        "twitter": sorted(k for k in p.meta if k.startswith("twitter:")),
        "h1_count_raw": len(h1s), "h1_texts": h1s, "headings": outline,
        "word_count_visible_raw_html": words,
        "html_bytes_decoded": len(html.encode()),
        "text_to_html_ratio_pct": round(100 * len(" ".join(p.text).encode()) / max(1, len(html.encode())), 1),
        "images": {"count": len(imgs),
                   "missing_alt_attr": sum(1 for i in imgs if "alt" not in i),
                   "empty_alt": sum(1 for i in imgs if i.get("alt") == "" and "alt" in i),
                   "lazy": sum(1 for i in imgs if i.get("loading", "").lower() == "lazy"),
                   "without_dimensions": sum(1 for i in imgs if not (i.get("width") and i.get("height"))),
                   "modern_format": sum(1 for i in imgs if re.search(r"\.(webp|avif)(\?|$)", i.get("src", ""), re.I))},
        "links": {"internal": internal, "external": external, "empty_or_hash": empty,
                  "generic_anchor_text": generic, "nofollow": nofollow, "top_external_hosts": dict(sorted(ext_hosts.items(), key=lambda x: -x[1])[:8])},
        "forms": p.forms, "buttons_count": len(p.buttons), "cta_candidates": cta_unique[:15],
        "tel_mailto_links": p.tel_mailto, "iframes": p.iframes, "videos": p.videos,
        "structured_data": {"jsonld_types": types, "jsonld_blocks": len(p.jsonld_raw), "invalid_jsonld_blocks": invalid_ld},
        "assets": {"external_scripts": len(p.scripts), "stylesheets": p.stylesheets,
                   "inline_script_kb": round(p.inline_script_bytes / 1024, 1),
                   "third_party_script_hosts": dict(sorted(script_hosts.items(), key=lambda x: -x[1])[:12])},
        "mixed_content_http_resources": mixed_content_count(html) if parsed.scheme == "https" else 0,
        "trackers_detected": sorted(k for k, rx in TRACKERS.items() if re.search(rx, surface, re.I)),
        "consent_tool_detected": sorted(k for k, rx in CONSENT.items() if re.search(rx, surface, re.I)),
        "headers": {k: h.get(k) for k in (
            "strict-transport-security", "content-security-policy", "x-frame-options", "x-content-type-options",
            "referrer-policy", "permissions-policy", "cross-origin-opener-policy", "cache-control", "content-encoding",
            "server", "x-powered-by", "cf-cache-status", "age", "link")},
    })

    # Site level probes
    sec = {}
    rb = fetch(base + "/robots.txt", args.ua, timeout=15)
    robots_body = rb["body"] if rb["status"] == 200 else ""
    sec["robots.txt"] = {"status": rb["status"], "bytes": len(robots_body), "final_url": rb["final_url"], "head": robots_body[:160].replace("\n", " ") or None}
    sec["robots_txt_full"] = robots_body[:20000]     # whole file (capped): references/ai-visibility.md reads the rules here
    sitemap_lines = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_body)
    sec["robots_sitemaps_declared"] = sitemap_lines
    sec["robots_disallow_all"] = robots_disallows_all(robots_body)
    sec["ai_crawlers_robots"] = ai_robot_decisions(rb["status"], robots_body)
    for pth in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/llms.txt"):
        sec[pth] = probe(base, pth, args.ua)
    miss = fetch(f"{base}/{uuid.uuid4().hex[:12]}-site-audit-404-test", args.ua, timeout=15)
    sec["soft_404_test"] = {"status": miss["status"], "final_url": miss["final_url"], "hops": len(miss["chain"]),
                            "expected": "404 (a 200, or a redirect to the home page, is a soft 404)"}
    http_try = fetch("http://" + parsed.netloc + "/", args.ua, timeout=15)
    sec["http_to_https"] = {"final_url": http_try["final_url"], "hops": len(http_try["chain"]), "ok": http_try["final_url"].startswith("https://")}
    alt_host = parsed.netloc[4:] if parsed.netloc.startswith("www.") else "www." + parsed.netloc
    alt = fetch(f"{parsed.scheme}://{alt_host}/", args.ua, timeout=15, want_body=False)
    sec["alt_host_" + alt_host] = {"status": alt["status"], "final_url": alt["final_url"], "hops": len(alt["chain"])}
    f["site_level"] = sec

    out = json.dumps(f, ensure_ascii=False, indent=2)
    if args.out:
        _write(args.out, out)
        print("written:", args.out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
