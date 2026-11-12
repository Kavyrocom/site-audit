#!/usr/bin/env python3
"""Is the answer a bot-protection page (a challenge, a block) instead of the site itself? (stdlib only, no network)

A site behind a firewall or a bot filter may answer an automated visitor with a "Just a moment..." page, a captcha or a
block page. Read as if it were the site, that page gives a false audit: "no description, thin content, noindex".
The scripts call `detect()` on what they received and stop, or set the page aside, when the answer is a protection page.

    detect(status, headers, html="", title=None, text=None) -> None | {
        "vendor": "cloudflare" | ... | None,   # who runs the protection, when the page says so
        "kind": "challenge" | "block" | "verification",
        "confidence": "high" | "medium",
        "signals": [short strings: what was seen],
        "http_status": int }

`high`   a header that only a protection sends, or a marker of a known protection on a page that is too thin to be a
         real page (150 visible words or fewer). The scripts stop on it.
`medium` a status that refuses (401, 403, 429, 503) from a server that names a protection, or generic wording ("verify
         you are human") on a thin page. The scripts report it and keep going (a login page can say the same words).

What this module does NOT do: it never tries to pass a challenge or to look like a person. A protection that stops the
audit is the owner's decision: the way out is to allow the audit machine's address in the protection, or to audit a
copy of the site. See references/technical.md.
"""
import re

THIN_WORDS = 150            # a real page has more visible text than this; a challenge or block page has far less
MAX_SCAN = 200_000          # characters of the page that are read

# Headers only a protection sends: (header, regex on its value) -> vendor
HEADER_SIGNS = (
    ("cf-mitigated", r"challenge", "cloudflare"),
    ("x-amzn-waf-action", r"challenge|captcha", "aws_waf"),
    ("x-vercel-mitigated", r"challenge|deny", "vercel"),
)

# Markers of one named protection, written in the page itself. Matched on the lower-cased HTML.
VENDOR_MARKERS = (
    ("cloudflare", r"<title>\s*just a moment\.{0,3}\s*</title>"),
    ("cloudflare", r"cf_chl_opt|cf-chl-widget|/cdn-cgi/challenge-platform/h/[a-z]/orchestrate/"),
    ("cloudflare", r"checking your browser before accessing"),
    ("cloudflare", r"attention required!\s*\|\s*cloudflare"),
    ("cloudflare", r"verifying you are human\. this may take a few seconds"),
    ("cloudflare", r"(?:you have been blocked|you are unable to access).{0,400}cloudflare ray id|cloudflare ray id.{0,400}you have been blocked"),
    ("sucuri", r"sucuri website firewall"),
    ("imperva", r"_incapsula_resource|incapsula incident id|request unsuccessful\. incapsula"),
    ("datadome", r"captcha-delivery\.com"),
    ("human_security", r"px-captcha|_pxcaptcha|press (?:&amp;|&) hold to confirm you are a human"),
    ("akamai", r"access denied.{0,300}reference(?:\s|&#32;)*(?:#|&#35;|&#x23;)\s*[0-9a-f]{1,3}(?:\.|&#46;)[0-9a-f]+"),
    ("vercel", r"vercel security checkpoint|we're verifying your browser"),
    ("anubis", r"making sure you.re not a bot|protected by anubis"),
    ("aws_waf", r"awswafintegration|token\.awswaf\.com|awswafcookiedomainlist"),
)

# Wording that protections use but that an ordinary page may also contain: never enough alone on a page with content.
GENERIC_MARKERS = (
    r"verify (?:that )?you are (?:a )?human",
    r"are you a robot",
    r"enable javascript and cookies to continue",
    r"checking if the site connection is secure",
    r"pardon our interruption",
    r"please verify you are a human",
    r"unusual traffic from your computer network",
    r"access to this page has been denied",
)

REFUSING = (401, 403, 429, 503)
SERVER_VENDORS = (("cloudflare", "cloudflare"), ("sucuri", "sucuri"), ("akamaighost", "akamai"), ("akamai", "akamai"),
                  ("imperva", "imperva"), ("incapsula", "imperva"), ("datadome", "datadome"))

_SCRIPT_STYLE = re.compile(r"(?is)<(script|style|template)\b.*?</\1\s*>")
_TAG = re.compile(r"(?s)<[^>]*>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title\s*>")


def visible_words(html):
    """Number of words a visitor can read in this HTML (scripts and styles left out; <noscript> kept)."""
    text = _TAG.sub(" ", _SCRIPT_STYLE.sub(" ", html or ""))
    return len(re.findall(r"\w+", text))


def _vendor_from_server(headers):
    server = ((headers or {}).get("server") or "").lower()
    for needle, vendor in SERVER_VENDORS:
        if needle in server:
            return vendor
    if any(k.startswith("x-sucuri") for k in (headers or {})):
        return "sucuri"
    return None


def detect(status, headers, html="", title=None, text=None):
    """See the module docstring. `text` is the visible text when the caller already has it (a browser's page);
    otherwise it is taken from `html`."""
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    body = (html or "")[:MAX_SCAN]
    low = body.lower()
    if title is None:
        m = _TITLE.search(body)
        title = " ".join(m.group(1).split()) if m else ""
    words = len(re.findall(r"\w+", text)) if text is not None else visible_words(body)
    thin = words <= THIN_WORDS
    if text is not None:
        low += "\n" + text.lower()
    low = "<title>" + (title or "").lower() + "</title>\n" + low if title and "<title" not in low else low

    def found(kind, vendor, confidence, signals):
        return {"vendor": vendor, "kind": kind, "confidence": confidence, "signals": signals, "http_status": status}

    for header, rx, vendor in HEADER_SIGNS:
        value = headers.get(header)
        if value and re.search(rx, value, re.I):
            return found("challenge", vendor, "high", [f"header {header}: {value[:40]}"])

    if thin:
        hits = [(vendor, rx) for vendor, rx in VENDOR_MARKERS if re.search(rx, low, re.S)]
        if hits:
            vendors = sorted({v for v, _ in hits})
            kind = "block" if status in REFUSING and not re.search(r"just a moment|checking your browser|verifying you are human|performing security|making sure", low) else "challenge"
            return found(kind, vendors[0], "high",
                         [f"{v} marker on a page of {words} visible words" for v in vendors])

    server_vendor = _vendor_from_server(headers)
    if status in REFUSING and server_vendor and thin:
        return found("block", server_vendor, "medium",
                     [f"HTTP {status} from a {server_vendor} server, {words} visible words, no site content"])

    if thin:
        generic = [rx for rx in GENERIC_MARKERS if re.search(rx, low)]
        if generic and (len(generic) >= 2 or status in REFUSING):
            return found("verification", None, "medium",
                         [f"{len(generic)} wording(s) used by verification pages, {words} visible words"])
    return None


def one_line(bw):
    """A sentence for the person: what was seen, in plain words."""
    who = {"cloudflare": "Cloudflare", "aws_waf": "AWS WAF", "sucuri": "Sucuri", "imperva": "Imperva", "datadome": "DataDome",
           "human_security": "HUMAN (PerimeterX)", "akamai": "Akamai", "vercel": "Vercel", "anubis": "Anubis"}.get(bw.get("vendor"), "a bot protection")
    what = {"challenge": "a challenge page", "block": "a block page", "verification": "a verification page"}[bw["kind"]]
    return f"the answer is {what} from {who} (HTTP {bw['http_status']}), not the site"


GUIDANCE = ("Do not audit from this answer, and do not try to get past the protection. Ask the owner to allow the audit "
            "machine's address in the protection (or to give a copy of the site that is not behind it), then run again.")
