#!/usr/bin/env python3
"""What the browser's DevTools show for a first-time visitor: network, cookies, console, before any consent.

Usage:
    python3 -I devtools.py <url> [--out dir] [--desktop] [--settle 6] [--throttle] [--after-refuse]
                                 [--tracker-host HOST ...]

Needs only Chrome or Chromium (CHROME_PATH if not found) and Python 3.9+. It drives Chrome through the DevTools
Protocol, like render.py. A fresh browser profile is used, so the page is seen as a visitor who never came
before: no cookie, no consent given.

Writes <out>/devtools.json and prints a summary. It records, without clicking anything:
  requests    every request, size by type, third parties by host and category (analytics, ads, session replay,
              tag manager, chat, consent tool, fonts, embeds...), failed requests, mixed content
  cookies     name, domain, lifetime and flags (never the value), which ones come from known trackers
  consent     trackers that fired and cookies that were set BEFORE any interaction; the consent signal that
              Google tags send (gcs=G100 means denied); the cookie banner and its buttons
  console     errors and warnings, uncaught exceptions
  lab vitals  LCP element, CLS, main-thread busy time and script time (one unthrottled run on this machine: indicative, not comparable
              with Lighthouse unless you pass --throttle; use lh_median.py for scores)
--after-refuse: after the first snapshot, clicks the refuse button of the cookie banner it detected ("Tout refuser",
"Reject all"...) and records what still fires or is set afterwards. The click can only land inside that banner, on a
real button (never a form, a submit button or a link that leaves the page). Without a detected banner nothing is
clicked. It never clicks accept, never fills or submits a form. A banner in a closed shadow root or a cross-origin
iframe cannot be read: the script says so instead of concluding there is none.
The measuring machine's location can change what a banner shows (EU or not): say where it ran.
"""
import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402
from render import CDP, DESKTOP_UA, MOBILE_UA, WS, Chrome, find_chrome  # noqa: E402

CATEGORIES = [
    ("session_replay", ("hotjar.", "clarity.ms", "fullstory.com", "mouseflow.", "crazyegg.", "luckyorange.", "smartlook.", "logrocket.")),
    ("tag_manager", ("googletagmanager.com", "tealiumiq.com", "tags.tiqcdn.com", "segment.com/analytics.js", "cdn.segment.com")),
    ("analytics", ("google-analytics.com", "analytics.google.com", "plausible.io", "posthog", "matomo", "piwik", "mixpanel.com", "heap-api", "heapanalytics.com",
                   "amplitude.com", "segment.io", "simpleanalyticscdn", "umami", "statcounter.com", "hs-analytics.net", "hubspot.com/__ptq", "clicky.com",
                   "fathom", "cloudflareinsights.com")),
    ("ads", ("doubleclick.net", "googleadservices.com", "googlesyndication.com", "connect.facebook.net", "facebook.com/tr", "ads-twitter.com", "analytics.twitter.com",
             "snap.licdn.com", "px.ads.linkedin.com", "linkedin.com/px", "analytics.tiktok.com", "bat.bing.com", "criteo.", "taboola.", "outbrain.", "adroll.",
             "ct.pinterest.com", "sc-static.net", "snapchat.com", "adnxs.com", "rubiconproject.com", "amazon-adsystem.com", "googleads.g.doubleclick.net")),
    ("consent_tool", ("cookiebot.com", "cookieyes.com", "onetrust.com", "cookielaw.org", "didomi.io", "axeptio.eu", "usercentrics.eu", "iubenda.com", "termly.io",
                      "osano.com", "complianz", "cookie-script.com", "cookiefirst.com", "consentmanager.net", "trustarc.com")),
    ("chat_crm", ("intercom.io", "intercomcdn.com", "crisp.chat", "drift.com", "tawk.to", "hs-scripts.com", "hsforms.", "hubspot.com", "zendesk.com", "zdassets.com",
                  "freshchat.com", "tidio.", "livechatinc.com", "hs-banner.com", "hsadspixel.net", "calendly.com", "typeform.com")),
    ("fonts", ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit.net", "fonts.bunny.net", "fontawesome.com", "use.fontawesome.com")),
    ("captcha", ("google.com/recaptcha", "gstatic.com/recaptcha", "hcaptcha.com", "challenges.cloudflare.com", "turnstile")),
    ("payment", ("stripe.com", "stripe.network", "paypal.com", "paypalobjects.com", "js.mollie.com", "adyen.com", "klarna.com")),
    ("embed", ("youtube.com", "youtube-nocookie.com", "ytimg.com", "vimeo.com", "vimeocdn.com", "twitter.com", "platform.twitter.com", "instagram.com", "cdninstagram.com",
               "maps.googleapis.com", "google.com/maps", "maps.gstatic.com", "spotify.com", "soundcloud.com", "wistia.", "loom.com")),
    ("cdn_library", ("cdnjs.cloudflare.com", "jsdelivr.net", "unpkg.com", "bootstrapcdn.com", "code.jquery.com", "gstatic.com", "ajax.googleapis.com", "stackpath.bootstrapcdn.com")),
]
TRACKING = {"analytics", "ads", "session_replay"}
TRACKER_COOKIE = re.compile(r"^(_ga(_.*)?|_gid|_gat.*|_gcl_.*|_fbp|_fbc|fr|_hj.*|hjSession.*|ajs_.*|_clck|_clsk|_uet.*|_tt_.*|_ttp|_pin_.*|_pinterest.*|li_.*|lidc|bcookie|"
                            r"IDE|test_cookie|NID|ph_.*|__ph.*|mp_.*|_pk_.*|_hjid|_omappvid|__hs.*|hubspotutk|_rdt_.*|__utm.*|_mkto_.*|intercom-.*|__stripe_.*)$", re.I)
SENSITIVE_COOKIE = re.compile(r"sess|token|auth|login|jwt|sid\b|csrf", re.I)
REFUSE = re.compile(r"^\s*(tout refuser|refuser tout|tout rejeter|refuser|rejeter|continuer sans accepter|non merci|reject all|reject|decline all|decline|deny all|deny|refuse all|refuse|only necessary|uniquement les cookies? n[ée]cessaires?|seulement les cookies? essentiels?)(?:\s+(?:les\s+)?(?:cookies?|non[ -]essentiels?|optionnels?))?\s*[.!]?\s*$", re.I)
ACCEPT = re.compile(r"^\s*(tout accepter|accepter tout|accepter|j'accepte|ok|d'accord|accept all|accept|allow all|agree|i agree)\s*[.!]?\s*$", re.I)

PERF_JS = r"""(() => { const sa = window.__sa = {lcp: null, cls: 0, shifts: 0};
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) sa.lcp = {t: Math.round(e.startTime), size: e.size, tag: e.element ? e.element.tagName.toLowerCase() : null,
        url: e.url || null, text: e.element ? (e.element.innerText || '').slice(0, 80) : null}; }).observe({type: 'largest-contentful-paint', buffered: true}); } catch (e) {}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) { sa.cls += e.value; sa.shifts++; } }).observe({type: 'layout-shift', buffered: true}); } catch (e) {}
})();"""

READ_JS = r"""(() => { const sa = window.__sa || {}; const n = performance.getEntriesByType('navigation')[0] || {};
  return {sa: {lcp: sa.lcp || null, cls: sa.cls || 0, shifts: sa.shifts || 0},
    nav: {ttfb: Math.round(n.responseStart || 0), dcl: Math.round(n.domContentLoadedEventEnd || 0), load: Math.round(n.loadEventEnd || 0)},
    storage: {local: Object.keys(localStorage), session: Object.keys(sessionStorage)}}; })()"""

# Shared by the banner detection and the refuse click, so that the click can only ever land inside a banner that
# the detection found: the same elements, the same rules. It reads the page and open shadow roots.
BANNER_LIB = r"""
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const sig = /cookie|consent|gdpr|rgpd|cmp|didomi|onetrust|cookiebot|axeptio|cookieyes|complianz|cc-window|tarteaucitron|privacy|usercentrics|osano|termly|quantcast|trustarc|iubenda|klaro|borlabs|cookiefirst|cookiehub|sirdata|sourcepoint|consentmanager/i;
  const deep = (root, sel) => { let out = [...root.querySelectorAll(sel)]; if (root.shadowRoot) out = out.concat(deep(root.shadowRoot, sel));
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) out = out.concat(deep(el.shadowRoot, sel)); return out; };
  const inside = (el, outer) => { for (let x = el.parentNode || el.host; x; x = x.parentNode || x.host) if (x === outer) return true; return false; };
  const label = el => clean(el.innerText || el.value || el.getAttribute('aria-label'));
  // A control that can only change the banner. Not tied to a form in ANY way (inside one, or pointing at one with the
  // form= attribute: el.form is the form that owns it), and not a link that leaves the page (an <a> is accepted only
  // without an address or with a # address). A <button> with no form owner does nothing by default, which is the
  // common shape of a banner button. The click is also followed by a navigation block (see the guard in render.py).
  const safe = el => { if (el.form || el.closest('form') || el.hasAttribute('form')) return false;
    if (el.tagName === 'INPUT') return el.type === 'button';
    if (el.tagName === 'A') { const h = (el.getAttribute('href') || '').trim(); return h === '' || h.charAt(0) === '#'; }
    return true; };
  const BTN = 'button,a,[role=button],input[type=button]';
  const choice = /accept|refus|reject|decline|deny|personnalis|param[eé]tr|pr[eé]f[eé]rences|preferences|settings|manage|customi[sz]e|d'accord|agree|allow|continuer sans/i;
  const banners = () => {
    const boxes = deep(document.body, '*').filter(el => sig.test((el.id || '') + ' ' + String(el.className || '') + ' ' + (el.getAttribute('role') || '') + ' ' + (el.getAttribute('aria-label') || '')) && vis(el));
    const top = boxes.filter(el => !boxes.some(o => o !== el && inside(el, o)));
    return top.slice(0, 6).map(b => ({el: b, btns: deep(b, BTN).filter(vis).filter(safe)})).filter(x => x.btns.some(y => choice.test(label(y))));
  };
"""

BANNER_JS = "(() => {" + BANNER_LIB + r"""
  return banners().map(({el, btns}) => { const r = el.getBoundingClientRect();
    return {id: el.id || null, text: clean(el.innerText).slice(0, 220), buttons: btns.map(label).filter(Boolean).slice(0, 8),
            share_of_screen_pct: Math.round(100 * Math.min(r.height, innerHeight) * Math.min(r.width, innerWidth) / (innerHeight * innerWidth))}; });
})()"""

# Consent tools that live in an iframe cannot be read from the page: report them instead of pretending there is no banner.
FRAME_JS = "(() => {" + BANNER_LIB + r"""
  return deep(document, 'iframe').filter(vis).filter(f => sig.test((f.src || '') + ' ' + (f.id || '') + ' ' + (f.title || '') + ' ' + String(f.className || '')))
    .map(f => { try { return new URL(f.src, location.href).host; } catch (e) { return f.id || 'iframe'; } }).slice(0, 5);
})()"""

# Clicks ONE button, only inside a banner the detection found, only if its text is a refusal. Never a form, never a link out.
CLICK_JS = "((src, flags) => {" + BANNER_LIB + r"""
  const re = new RegExp(src, flags);
  for (const {el, btns} of banners()) { const hit = btns.find(x => re.test(label(x))); if (hit) { const t = label(hit); hit.click(); return t; } }
  return null;
})"""


class Rec(CDP):
    """CDP client that keeps the full payload of every event (render.py's keeps only the names)."""

    def __init__(self, ws):
        super().__init__(ws)
        self.msgs = []

    def call(self, method, **params):
        self.n += 1
        i = self.n
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if self._guard(m):
                continue
            if m.get("id") == i:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error'].get('message')}")
                return m.get("result", {})
            if "method" in m:
                self.msgs.append(m)

    def pump(self, seconds, until=None):
        end = time.time() + seconds
        self.ws.s.settimeout(0.5)
        try:
            while time.time() < end:
                if until and any(m["method"] == until for m in self.msgs):
                    return True
                try:
                    m = json.loads(self.ws.recv())
                except socket.timeout:
                    continue
                if self._guard(m):
                    continue
                if "method" in m:
                    self.msgs.append(m)
            return bool(until) and any(m["method"] == until for m in self.msgs)
        finally:
            self.ws.s.settimeout(45)


def reg_domain(host):
    host = host.lower().split(":")[0]
    if re.match(r"^[\d.]+$", host) or host in ("localhost",) or ":" in host:
        return host
    p = host.split(".")
    if len(p) >= 3 and p[-2] in ("co", "com", "org", "net", "gov", "ac") and len(p[-1]) == 2:
        return ".".join(p[-3:])
    return ".".join(p[-2:])


def categorize(url, extra_trackers):
    u = urllib.parse.urlparse(url)
    key = (u.netloc + u.path).lower()
    host = u.hostname or ""
    if any(host == h or host.endswith("." + h) for h in extra_trackers):
        return "analytics"
    for cat, pats in CATEGORIES:
        if any(p in key for p in pats):
            return cat
    return "other"


def google_consent(url):
    """gcs=G1xy in Google tag requests: x = ad_storage, y = analytics_storage (1 granted, 0 denied)."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    g = (q.get("gcs") or [None])[0]
    if g and re.fullmatch(r"G1[01][01]", g):
        return {"gcs": g, "ad_storage": "granted" if g[2] == "1" else "denied", "analytics_storage": "granted" if g[3] == "1" else "denied"}
    return None


def summarize(msgs, page_url, extra_trackers, start=0):
    """Fold Network events into one record per request."""
    reqs = {}
    host = urllib.parse.urlparse(page_url).hostname or ""
    site = reg_domain(host)
    for m in msgs[start:]:
        p, name = m.get("params", {}), m["method"]
        rid = p.get("requestId")
        if name == "Network.requestWillBeSent":
            url = p["request"]["url"]
            if url.startswith(("data:", "blob:", "chrome-extension:", "about:")):
                continue
            reqs[rid] = {"url": url, "type": p.get("type", "Other"), "status": None, "bytes": 0, "failed": None, "mime": None,
                         "initiator": (p.get("initiator") or {}).get("type"), "t": m.get("_i")}
        elif name == "Network.responseReceived" and rid in reqs:
            reqs[rid]["status"] = p["response"].get("status")
            reqs[rid]["mime"] = p["response"].get("mimeType")
        elif name == "Network.loadingFinished" and rid in reqs:
            reqs[rid]["bytes"] = int(p.get("encodedDataLength") or 0)
        elif name == "Network.loadingFailed" and rid in reqs:
            reqs[rid]["failed"] = p.get("blockedReason") or p.get("errorText")
            reqs[rid]["canceled"] = bool(p.get("canceled"))
    out = []
    for r in reqs.values():
        h = urllib.parse.urlparse(r["url"]).hostname or ""
        r["host"] = h
        r["third_party"] = reg_domain(h) != site
        r["category"] = categorize(r["url"], extra_trackers) if r["third_party"] or categorize(r["url"], extra_trackers) in ("analytics", "ads") else "first_party"
        out.append(r)
    return out


def cookie_meta(cookies, site, https):
    out = []
    for c in cookies:
        dom = c.get("domain", "").lstrip(".")
        exp = c.get("expires", -1)
        days = None if c.get("session") or exp in (-1, None) else round((exp - time.time()) / 86400, 1)
        out.append({"name": c["name"], "domain": c.get("domain"), "first_party": reg_domain(dom) == site, "session": bool(c.get("session")),
                    "days_left": days, "secure": bool(c.get("secure")), "http_only": bool(c.get("httpOnly")), "same_site": c.get("sameSite"),
                    "tracker_named": bool(TRACKER_COOKIE.match(c["name"])),
                    "issue": ("sensitive-looking name without HttpOnly" if SENSITIVE_COOKIE.search(c["name"]) and not c.get("httpOnly") else
                              ("no Secure flag on an https site" if https and not c.get("secure") else None))})
    return out


def console_log(msgs):
    seen, out = set(), []
    for m in msgs:
        p, n = m.get("params", {}), m["method"]
        item = None
        if n == "Runtime.consoleAPICalled" and p.get("type") in ("error", "warning", "assert"):
            txt = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
            st = (p.get("stackTrace") or {}).get("callFrames") or [{}]
            item = {"level": p["type"], "text": txt[:240], "source": "console", "url": st[0].get("url"), "line": st[0].get("lineNumber")}
        elif n == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            item = {"level": "exception", "text": ((d.get("exception") or {}).get("description") or d.get("text") or "")[:240], "source": "exception", "url": d.get("url"), "line": d.get("lineNumber")}
        elif n == "Log.entryAdded" and p.get("entry", {}).get("level") in ("error", "warning"):
            e = p["entry"]
            item = {"level": e["level"], "text": (e.get("text") or "")[:240], "source": e.get("source"), "url": e.get("url"), "line": e.get("lineNumber")}
        if item:
            k = (item["level"], item["text"][:120])
            if k not in seen:
                seen.add(k)
                out.append(item)
    return out[:25]


def snapshot(c, page_url, extra_trackers, start, https, site):
    reqs = summarize(c.msgs, page_url, extra_trackers, start)
    ck = cookie_meta(c.call("Network.getAllCookies").get("cookies", []), site, https)
    return reqs, ck


def tracking_view(reqs, cookies):
    trackers = defaultdict(lambda: {"requests": 0, "category": None})
    sig = []
    for r in reqs:
        if r["category"] in TRACKING or r["category"] == "tag_manager":
            t = trackers[r["host"]]
            t["requests"] += 1
            t["category"] = r["category"]
            g = google_consent(r["url"])
            if g and g not in sig:
                sig.append(g)
    return {"tracker_requests": [{"host": h, **v} for h, v in sorted(trackers.items(), key=lambda kv: -kv[1]["requests"])],
            "tracker_cookies": [{k: c[k] for k in ("name", "domain", "first_party", "days_left")} for c in cookies if c["tracker_named"] or (not c["first_party"])],
            "google_consent_signals": sig}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out", default="devtools")
    ap.add_argument("--desktop", action="store_true")
    ap.add_argument("--settle", type=float, default=6.0, help="seconds to wait after load for late tags")
    ap.add_argument("--throttle", action="store_true", help="4x CPU slowdown and slow 4G network, like Lighthouse mobile")
    ap.add_argument("--after-refuse", action="store_true", help="click the banner's refuse button and record what still fires")
    ap.add_argument("--tracker-host", action="append", default=[], help="extra host to treat as an analytics tracker (tests, first-party analytics)")
    a = ap.parse_args()
    url = safenet.start_url(a.url)
    chrome = find_chrome()
    if not chrome:
        sys.exit("Chrome/Chromium not found. Set CHROME_PATH or install Chrome. This step is optional: write 'DevTools check not done' in the report.")
    os.makedirs(a.out, exist_ok=True)
    safenet.private_output(a.out)
    browser = Chrome(chrome, "sa-dt-")
    ws = None
    try:
        port = browser.port
        targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10))
        page = next(t for t in targets if t.get("type") == "page")
        ws = WS("127.0.0.1", port, "/" + page["webSocketDebuggerUrl"].split("/", 3)[3])
        c = Rec(ws)
        for d in ("Page", "Network", "Runtime", "Log", "Performance"):
            c.call(d + ".enable")
        c.guard(url)
        w, h, mobile, ua = (1440, 900, False, DESKTOP_UA) if a.desktop else (390, 844, True, MOBILE_UA)
        c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=mobile)
        c.call("Emulation.setUserAgentOverride", userAgent=ua, acceptLanguage="fr-FR,fr;q=0.9,en;q=0.8")
        if a.throttle:
            c.call("Emulation.setCPUThrottlingRate", rate=4)
            c.call("Network.emulateNetworkConditions", offline=False, latency=150, downloadThroughput=int(1.6 * 1024 * 1024 / 8), uploadThroughput=int(750 * 1024 / 8))
        c.call("Page.addScriptToEvaluateOnNewDocument", source=PERF_JS)
        c.call("Page.navigate", url=url)
        loaded = c.pump(45, until="Page.loadEventFired")
        c.pump(a.settle)
        refused = c.refusal()
        if refused:
            sys.exit(f"refused: the page led to {refused['url']} ({refused['why']}). Nothing from that address was read, nothing written")
        final = c.run_js("location.href") or url
        https = final.startswith("https://")
        site = reg_domain(urllib.parse.urlparse(final).hostname or "")
        reqs, cookies = snapshot(c, final, a.tracker_host, 0, https, site)
        info = c.run_js(READ_JS) or {}
        pm = {m["name"]: m["value"] for m in c.call("Performance.getMetrics").get("metrics", [])}
        banner = c.run_js(BANNER_JS) or []
        frames = c.run_js(FRAME_JS) or []
        pre_msgs = len(c.msgs)
        pre = tracking_view(reqs, cookies)
        # ---- weight, third parties, failures
        by_type = defaultdict(lambda: {"count": 0, "kb": 0.0})
        for r in reqs:
            by_type[r["type"]]["count"] += 1
            by_type[r["type"]]["kb"] += r["bytes"] / 1024
        tp = defaultdict(lambda: {"requests": 0, "kb": 0.0, "category": None})
        for r in reqs:
            if r["third_party"]:
                t = tp[r["host"]]
                t["requests"] += 1
                t["kb"] += r["bytes"] / 1024
                t["category"] = r["category"]
        failed = [{"url": r["url"][:160], "status": r["status"], "failed": r["failed"], "type": r["type"]} for r in reqs
                  if (r["status"] and r["status"] >= 400) or (r["failed"] and not r.get("canceled"))]
        mixed = [r["url"][:160] for r in reqs if https and r["url"].startswith("http://")]
        ms = lambda k: round(pm.get(k, 0) * 1000)
        result = {
            "url": url, "final_url": final, "device": "desktop" if a.desktop else "mobile", "throttled": a.throttle, "load_event": loaded,
            "note": "One run on this machine, no cookie and no consent given. " + ("Throttled like Lighthouse mobile. " if a.throttle else "Unthrottled: do not compare with Lighthouse scores. ") + "A banner can depend on where the machine is located.",
            "timing_ms": {"ttfb": info.get("nav", {}).get("ttfb"), "dom_content_loaded": info.get("nav", {}).get("dcl"), "load": info.get("nav", {}).get("load")},
            "lab_vitals": {"lcp_ms": (info.get("sa", {}).get("lcp") or {}).get("t"), "lcp_element": info.get("sa", {}).get("lcp"),
                           "cls": round(info.get("sa", {}).get("cls", 0), 4), "layout_shifts": info.get("sa", {}).get("shifts")},
            "main_thread": {"busy_ms": ms("TaskDuration"), "script_ms": ms("ScriptDuration"), "layout_ms": ms("LayoutDuration"), "style_ms": ms("RecalcStyleDuration"),
                            "dom_nodes": int(pm.get("Nodes", 0)), "js_heap_mb": round(pm.get("JSHeapUsedSize", 0) / 1048576, 1),
                            "note": "Cumulative Chrome counters from navigation to the end of the wait: how long the main thread worked, not blocking time (use Lighthouse TBT for that)."},
            "requests": {"total": len(reqs), "transfer_kb": round(sum(r["bytes"] for r in reqs) / 1024), "by_type": {k: {"count": v["count"], "kb": round(v["kb"])} for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]["kb"])},
                         "third_party": {"count": sum(1 for r in reqs if r["third_party"]), "kb": round(sum(r["bytes"] for r in reqs if r["third_party"]) / 1024),
                                         "hosts": [{"host": k, "category": v["category"], "requests": v["requests"], "kb": round(v["kb"])} for k, v in sorted(tp.items(), key=lambda kv: -kv[1]["requests"])][:25]}},
            "failed_requests": failed[:20], "mixed_content": mixed[:10],
            "cookies": cookies, "cookie_summary": {"total": len(cookies), "first_party": sum(1 for k in cookies if k["first_party"]), "third_party": sum(1 for k in cookies if not k["first_party"]),
                                                   "tracker_named": sum(1 for k in cookies if k["tracker_named"]), "with_issue": [{"name": k["name"], "issue": k["issue"]} for k in cookies if k["issue"]][:10]},
            "storage_keys": info.get("storage", {}),
            "consent_banner": banner,
            "consent_iframes": frames,
            "blocked_by_guard": c.blocked[:20],
            "blocked_by_proxy": (browser.proxy.refused[:20] if browser.proxy else []),
            "guard_connections": (browser.proxy.served if browser.proxy else None),
            "before_any_interaction": pre,
            "console": console_log(c.msgs[:pre_msgs]),
        }
        if a.after_refuse:
            ref = {"banner_found": bool(banner), "buttons": (banner[0]["buttons"] if banner else []), "clicked": None}
            ref["accept_visible"] = any(ACCEPT.match(b) for b in ref["buttons"])
            ref["refuse_visible"] = any(REFUSE.match(b) for b in ref["buttons"])
            # nothing is clicked unless the detection found a banner, and the click stays inside that banner
            # whatever the click does, the page may not navigate or submit a form afterwards: those requests are failed and recorded
            c.block_navigation = bool(banner)
            clicked = c.run_js(f"({CLICK_JS})({json.dumps(REFUSE.pattern)}, 'i')") if banner else None
            ref["clicked"] = clicked
            if clicked:
                c.pump(a.settle)
                ref["navigation_blocked"] = c.nav_blocked
                ref["requests_other_than_get_after_click"] = [{"method": m["params"]["request"]["method"], "url": m["params"]["request"]["url"][:160]}
                                                              for m in c.msgs[pre_msgs:] if m.get("method") == "Network.requestWillBeSent"
                                                              and m["params"]["request"]["method"] not in ("GET", "HEAD", "OPTIONS")][:10]
                after_reqs, after_cookies = snapshot(c, final, a.tracker_host, pre_msgs, https, site)
                av = tracking_view(after_reqs, after_cookies)
                before_names = {k["name"] for k in cookies}
                tracker_after = [k for k in after_cookies if k["tracker_named"] or not k["first_party"]]
                new_trackers = [t for t in av["tracker_requests"] if t["category"] in TRACKING]
                sig = av["google_consent_signals"]
                denied_only = bool(sig) and all(g["ad_storage"] == "denied" and g["analytics_storage"] == "denied" for g in sig)
                ref["new_tracker_requests"] = av["tracker_requests"]
                ref["google_consent_signals_after"] = sig
                ref["tracker_cookies_set_after"] = [{k: c2[k] for k in ("name", "domain", "first_party")} for c2 in tracker_after if c2["name"] not in before_names]
                ref["tracker_cookies_kept_from_before"] = [{k: c2[k] for k in ("name", "domain", "first_party")} for c2 in tracker_after if c2["name"] in before_names]
                after_banner = c.run_js(BANNER_JS) or []
                first = banner[0] if banner else {}
                ref["banner_still_visible"] = any((first.get("id") and x["id"] == first["id"]) or (not first.get("id") and x["text"][:60] == first.get("text", "")[:60]) for x in after_banner)
                if c.nav_blocked:
                    ref["verdict"] = ("the click tried to leave or submit the page (blocked, nothing was sent): that control is not a plain cookie "
                                      "refusal, so this test is NOT a measurement of the refusal. Look at the screenshots from render.py")
                elif (new_trackers and not denied_only) or ref["tracker_cookies_set_after"]:
                    ref["verdict"] = "refusal not respected: trackers fire or tracker cookies are set after refusing"
                elif new_trackers and denied_only:
                    ref["verdict"] = ("after refusing, only Google pings with consent denied (gcs=G100) were sent. That is how Google's consent mode "
                                      "is designed; whether such pings are acceptable under ePrivacy and the GDPR is a legal question this script does not answer")
                elif ref["tracker_cookies_kept_from_before"]:
                    ref["verdict"] = "nothing new fired after refusing, but tracker cookies set before the choice are still there"
                else:
                    ref["verdict"] = "nothing new fired after refusing"
                if ref["requests_other_than_get_after_click"] and not c.nav_blocked:
                    ref["verdict"] += (f". {len(ref['requests_other_than_get_after_click'])} request(s) other than GET followed the click "
                                       "(listed in requests_other_than_get_after_click): check that they are the consent tool's own call")
            elif not banner:
                ref["verdict"] = ("no cookie banner detected by this script (it reads the page and open shadow roots; a banner in a closed shadow root "
                                  "or inside an iframe is not seen)")
                if frames:
                    ref["verdict"] += f". A consent tool lives in an iframe ({', '.join(frames)}): nothing was clicked, look at the screenshots from render.py"
                elif pre["tracker_requests"] or pre["tracker_cookies"]:
                    ref["verdict"] += ". Trackers fired before any choice: look at the screenshots from render.py before concluding that no refusal is offered"
            else:
                ref["verdict"] = "no refuse button found in the banner: refusing may take several clicks or be impossible"
            result["after_refuse"] = ref
        with open(os.path.join(a.out, "devtools.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        r = result
        v = r["lab_vitals"]
        print(f"{r['device']}{' throttled' if a.throttle else ''}: {r['requests']['total']} requests, {r['requests']['transfer_kb']} KB, third party {r['requests']['third_party']['count']} requests / {r['requests']['third_party']['kb']} KB | "
              f"LCP {v['lcp_ms']} ms, CLS {v['cls']}, main thread busy {r['main_thread']['busy_ms']} ms (scripts {r['main_thread']['script_ms']} ms), {r['main_thread']['dom_nodes']} DOM nodes")
        b = r["before_any_interaction"]
        print(f"before any interaction: {len(b['tracker_requests'])} tracker hosts ({', '.join(t['host'] for t in b['tracker_requests'][:4]) or 'none'}), "
              f"{len(b['tracker_cookies'])} tracker/third-party cookies, google consent signals: {b['google_consent_signals'] or 'none seen'}")
        print(f"banner: {('found, buttons ' + str(r['consent_banner'][0]['buttons'])) if r['consent_banner'] else 'not detected'} | console issues: {len(r['console'])} | failed requests: {len(r['failed_requests'])} | mixed content: {len(r['mixed_content'])}")
        if a.after_refuse:
            print("after refusing:", r["after_refuse"]["verdict"])
        print(f"written: {os.path.join(a.out, 'devtools.json')}")
        return 0
    except StopIteration:
        sys.exit("Chrome started but exposed no page target.")
    except (ConnectionError, RuntimeError, OSError, socket.timeout) as e:
        sys.exit(f"devtools failed: {type(e).__name__}: {e}")
    finally:
        if ws:
            ws.close()
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
