#!/usr/bin/env python3
"""Render the page like a visitor: screens while scrolling + the text and buttons AFTER JavaScript ran.

Usage:
    python3 -I render.py <url> [--out shots] [--max-slices 8] [--start 1] [--settle 2.5]

Needs only Chrome or Chromium (set CHROME_PATH if it is not found) and Python 3.9+ (stdlib only: this file
contains a tiny WebSocket client to talk to Chrome's DevTools Protocol).

Produces, in <out>/:
    mobile-01.png ... mobile-NN.png   390x844 screens at successive scroll positions (what a phone user sees)
    desktop-01.png ...                1440x900, up to 3 screens
    rendered.json                     per profile: page height, total screens, which screens were captured,
                                      visible text, headings (with the screen they sit on), buttons and links with
                                      position and size, fixed/sticky elements (cookie banners, chat bubbles)
                                      with the share of the screen they cover, small tap targets, word counts
    rendered-mobile.txt               the visible text of the page after JavaScript, in reading order
Long page? `--start 9 --max-slices 8 --out shots-2` captures screens 9 to 16 (use `total_screens`, and the
`screen` number of each heading, to choose). Look at the sections that carry proof, price, FAQ or the last call to action.
Read-only: it never clicks, types or submits. Cookie banners are left as they are, on purpose: they are what
visitors see first.
Why this exists: facts.py reads the initial HTML only. Many pages build their text and buttons with JavaScript,
and a plain full-height screenshot misleads (100vh sections, scroll-reveal animations not triggered).
"""
import argparse
import base64
import json
import math
import os
import platform
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402
import netguard  # noqa: E402

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
DESKTOP_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


class Chrome:
    """A headless Chrome with a fresh profile, started for one audit and always cleaned up.

    The profile lives in a SHORT folder: Chrome opens a unix socket inside it and fails with a silent
    "path too long" when TMPDIR is a deep path. Chrome's own error output is kept and shown if it does not start.
    Running as root, Chrome only starts with --no-sandbox: a rendering-engine flaw in a hostile page would then
    run with root's rights, so the script says so and the README tells to audit unknown sites as a normal user.
    """

    def __init__(self, chrome, prefix, flags=(), guard=True):
        self.proxy = netguard.GuardProxy() if guard else None
        flags = (*flags, *(self.proxy.flags() if self.proxy else ()))
        base = tempfile.gettempdir()
        if len(base) > 40 and os.access("/tmp", os.W_OK):
            base = "/tmp"
        if base != tempfile.gettempdir():
            os.putenv("TMPDIR", base)      # Chrome puts a socket under TMPDIR and fails silently when that path is long
        self.prof = tempfile.mkdtemp(prefix=prefix, dir=base)
        self.errfile = os.path.join(self.prof + ".err")
        cmd = [chrome, "--headless=new", "--disable-gpu", *flags, "--remote-debugging-port=0", f"--user-data-dir={self.prof}",
               "--no-first-run", "--no-default-browser-check", "--disable-extensions", "about:blank"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.insert(2, "--no-sandbox")
            print("note: running as root, so Chrome starts without its sandbox. Audit sites you do not trust as a normal user.", file=sys.stderr)
        self.err = open(self.errfile, "wb")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=self.err)
        port_file = os.path.join(self.prof, "DevToolsActivePort")
        for _ in range(100):
            if os.path.exists(port_file):
                with open(port_file) as fh:
                    parts = fh.read().split()
                if len(parts) >= 2:
                    self.port = int(parts[0])
                    return
            if self.proc.poll() is not None:
                break
            time.sleep(0.15)
        tail = self._stderr_tail()
        self.close()
        sys.exit("Chrome did not start (no DevTools port)." + (f" Chrome said: {tail}" if tail else "")
                 + (" Set TMPDIR to a short folder such as /tmp and try again." if "too long" in tail.lower() or len(self.prof) > 80 else ""))

    def _stderr_tail(self):
        try:
            self.err.flush()
            with open(self.errfile, "rb") as fh:
                return " ".join(fh.read()[-400:].decode("utf-8", "replace").split())
        except OSError:
            return ""

    def close(self):
        if self.proxy:
            self.proxy.stop()
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        finally:
            try:
                self.err.close()
            except OSError:
                pass
            shutil.rmtree(self.prof, ignore_errors=True)
            try:
                os.remove(self.errfile)
            except OSError:
                pass


def find_chrome():
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    return None


class WS:
    """Minimal RFC 6455 client: text frames, fragmentation, ping/pong. Enough for DevTools."""

    def __init__(self, host, port, path, timeout=45):
        self.s = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise ConnectionError("websocket refused: " + buf.split(b"\r\n")[0].decode(errors="replace"))
        self.rest = buf.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        while len(self.rest) < n:
            chunk = self.s.recv(max(65536, n - len(self.rest)))
            if not chunk:
                raise ConnectionError("websocket closed")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, text):
        data = text.encode()
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        self.s.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if op == 0x8:
                raise ConnectionError("websocket closed by Chrome")
            if op == 0x9:  # ping -> pong
                mask = os.urandom(4)
                self.s.sendall(bytes([0x8A, 0x80 | len(payload)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
                continue
            if op in (0x1, 0x2, 0x0):
                msg += payload
                if fin:
                    return msg.decode("utf-8", "replace")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.events = ws, 0, []
        self.blocked = []            # browser requests the network guard refused
        self.guard_private = None    # None: guard off
        self.main_frame = None
        self.block_navigation = False   # once set, the page itself may not navigate or submit anything
        self.nav_blocked = []
        self._verdicts = {}

    def guard(self, start_url):
        """Judge EVERY request Chrome is about to make (redirects, scripts, images, frames) with safenet, before it goes out.

        A site under audit must not be able to make the audit machine open a private address, a local service or a
        file: URL, by redirect or by script. This is the first layer, for the requests of the page itself. The second
        is the proxy Chrome runs behind (netguard.py), which also covers frames of another site, service workers
        and WebSocket, and connects to the address it judged (no rebinding).
        """
        self.guard_private = safenet.starts_private(start_url)
        self.call("Fetch.enable", patterns=[{"urlPattern": "*"}])
        self.main_frame = ((self.call("Page.getFrameTree").get("frameTree") or {}).get("frame") or {}).get("id")

    def _guard(self, m):
        """True when `m` was a paused request and has been answered (continued or failed)."""
        if m.get("method") != "Fetch.requestPaused" or self.guard_private is None:
            return False
        p = m.get("params") or {}
        url = (p.get("request") or {}).get("url", "")
        u = urllib.parse.urlparse(url)
        key = (u.scheme.lower(), u.hostname or "")
        if key not in self._verdicts:
            self._verdicts[key] = safenet.browser_refusal(url, self.guard_private)
        why = self._verdicts[key]
        if (not why and self.block_navigation and p.get("resourceType") == "Document" and p.get("frameId") == self.main_frame):
            self.nav_blocked.append({"url": url[:200], "method": (p.get("request") or {}).get("method")})
            self.n += 1
            self.ws.send(json.dumps({"id": self.n, "method": "Fetch.failRequest", "params": {"requestId": p.get("requestId"), "errorReason": "BlockedByClient"}}))
            return True
        self.n += 1
        if why:
            self.blocked.append({"url": url[:200], "why": why, "type": p.get("resourceType"), "main_frame": p.get("frameId") == self.main_frame})
        self.ws.send(json.dumps({"id": self.n, "method": "Fetch.failRequest" if why else "Fetch.continueRequest",
                                 "params": {"requestId": p.get("requestId"), **({"errorReason": "BlockedByClient"} if why else {})}}))
        return True

    def refusal(self):
        """The refused request that was the page itself (not an image or a script on it), else None."""
        return next((b for b in self.blocked if b["main_frame"] and b["type"] == "Document"), None)

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
                self.events.append(m["method"])

    def wait_event(self, name, timeout=30):
        end = time.time() + timeout
        self.ws.s.settimeout(1.0)
        try:
            while time.time() < end:
                if name in self.events:
                    return True
                try:
                    m = json.loads(self.ws.recv())
                except socket.timeout:
                    continue
                if self._guard(m):
                    continue
                if "method" in m:
                    self.events.append(m["method"])
            return name in self.events
        finally:
            self.ws.s.settimeout(45)

    def run_js(self, expr):
        # Runs OUR constant snippets (scroll, extraction) inside the page being audited, via CDP Runtime.evaluate.
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError("js error: " + json.dumps(r["exceptionDetails"])[:200])
        return r.get("result", {}).get("value")


EXTRACT_JS = r"""(() => {
  const vh = innerHeight, vw = innerWidth;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const items = [...document.querySelectorAll('a,button,[role=button],input[type=submit]')].filter(vis).map(el => {
    const r = el.getBoundingClientRect();
    return {tag: el.tagName.toLowerCase(), text: clean(el.innerText || el.value || el.getAttribute('aria-label')).slice(0, 90),
            href: el.getAttribute('href'), top: Math.round(r.top + scrollY), w: Math.round(r.width), h: Math.round(r.height)};
  }).filter(x => x.text);
  const fixed = [...document.querySelectorAll('body *')].filter(el => {
    const s = getComputedStyle(el); return (s.position === 'fixed' || s.position === 'sticky') && vis(el); }).map(el => {
    const r = el.getBoundingClientRect();
    return {tag: el.tagName.toLowerCase(), id: el.id || null, class: String(el.className || '').slice(0, 50),
            top: Math.round(r.top), height: Math.round(r.height), width: Math.round(r.width),
            screen_covered_pct: Math.round(100 * Math.min(r.height, vh) * Math.min(r.width, vw) / (vh * vw)),
            text: clean(el.innerText).slice(0, 100)};
  }).filter(x => x.height > 20).slice(0, 12);
  const headings = [...document.querySelectorAll('h1,h2,h3')].filter(vis).map(h => { const top = Math.round(h.getBoundingClientRect().top + scrollY);
    return {level: h.tagName, text: clean(h.innerText).slice(0, 120), top, screen: Math.floor(top / vh) + 1}; }).slice(0, 80);
  const forms = [...document.querySelectorAll('form')].filter(vis).map(f => ({fields: f.querySelectorAll('input:not([type=hidden]):not([type=submit]),select,textarea').length}));
  return {page_height: document.documentElement.scrollHeight, viewport: [vw, vh], title: document.title,
          horizontal_scroll: document.documentElement.scrollWidth > vw + 2,
          text: (document.body.innerText || '').slice(0, 40000), headings, buttons_and_links: items.slice(0, 120),
          fixed_or_sticky: fixed, forms_visible: forms,
          small_tap_targets: items.filter(x => (x.tag === 'a' || x.tag === 'button') && (x.h < 40 || x.w < 40) && x.w * x.h > 0).length};
})()"""


def profile_run(c, name, w, h, mobile, ua, url, out, max_slices, settle, start=1):
    c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=mobile)
    c.call("Emulation.setUserAgentOverride", userAgent=ua)
    c.events.clear()
    c.call("Page.navigate", url=url)
    loaded = c.wait_event("Page.loadEventFired", 40)
    time.sleep(settle)
    height = c.run_js("document.documentElement.scrollHeight") or h
    # scroll through once so reveal-on-scroll content and lazy images get rendered
    y = 0
    while y < min(height, h * (start - 1 + max_slices)):
        c.run_js(f"window.scrollTo(0,{y})")
        time.sleep(0.35)
        y += h // 2
    c.run_js("window.scrollTo(0,0)")
    time.sleep(0.6)
    data = c.run_js(EXTRACT_JS) or {}
    height = data.get("page_height", height)
    total = max(1, math.ceil(height / h))
    first = min(max(1, start), total)
    last = min(total, first + max_slices - 1)
    files = []
    for i in range(first - 1, last):
        c.run_js(f"window.scrollTo(0,{i * h})")
        time.sleep(0.6)
        shot = c.call("Page.captureScreenshot", format="png")
        path = os.path.join(out, f"{name}-{i + 1:02d}.png")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))
        files.append(os.path.basename(path))
    c.run_js("window.scrollTo(0,0)")
    data["load_event_fired"] = loaded
    data["screens"] = files
    data["total_screens"] = total
    data["screens_range"] = [first, last]
    data["screens_cover_page"] = (first == 1 and last == total)
    data["words_rendered"] = len(re.findall(r"\w+", data.get("text", "")))
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="shots")
    ap.add_argument("--max-slices", type=int, default=8)
    ap.add_argument("--start", type=int, default=1, help="first mobile screen to capture (1-based), for long pages")
    ap.add_argument("--settle", type=float, default=2.5, help="seconds to wait after load")
    a = ap.parse_args()
    url = safenet.start_url(a.url)
    chrome = find_chrome()
    if not chrome:
        sys.exit("Chrome/Chromium not found. Set CHROME_PATH or install Chrome. Rendering is optional: write 'rendering not done' in the report.")
    os.makedirs(a.out, exist_ok=True)
    safenet.private_output(a.out)
    browser = Chrome(chrome, "sa-chrome-", ("--hide-scrollbars",))
    ws = None
    try:
        port = browser.port
        targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10))
        page = next(t for t in targets if t.get("type") == "page")
        path = "/" + page["webSocketDebuggerUrl"].split("/", 3)[3]
        ws = WS("127.0.0.1", port, path)
        c = CDP(ws)
        c.call("Page.enable")
        c.guard(url)
        result = {"url": url}
        result["mobile"] = profile_run(c, "mobile", 390, 844, True, MOBILE_UA, url, a.out, a.max_slices, a.settle, a.start)
        refused = c.refusal()
        if refused:
            sys.exit(f"refused: the page led to {refused['url']} ({refused['why']}). Nothing from that address was read; the screens written so far show a browser error page")
        result["desktop"] = profile_run(c, "desktop", 1440, 900, False, DESKTOP_UA, url, a.out, 3, a.settle)
        refused = c.refusal()
        if refused:
            sys.exit(f"refused: the page led to {refused['url']} ({refused['why']}). Nothing from that address was read; the screens written so far show a browser error page")
        if c.blocked:
            result["blocked_requests"] = c.blocked[:20]
        if browser.proxy:
            result["guard_connections"] = browser.proxy.served          # proof that Chrome really went through the filter
            if browser.proxy.refused:
                result["blocked_by_proxy"] = browser.proxy.refused[:20]
        with open(os.path.join(a.out, "rendered-mobile.txt"), "w", encoding="utf-8") as fh:
            fh.write(result["mobile"].get("text", ""))
        for k in ("mobile", "desktop"):
            result[k].pop("text", None) if k == "desktop" else None
        with open(os.path.join(a.out, "rendered.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        m = result["mobile"]
        print(f"mobile: page height {m['page_height']} px = {m['total_screens']} screens, captured {m['screens_range'][0]} to {m['screens_range'][1]}, covers whole page: {m['screens_cover_page']}, "
              f"{m['words_rendered']} words rendered, {len(m['buttons_and_links'])} buttons/links, small tap targets: {m['small_tap_targets']}")
        for f in m["fixed_or_sticky"]:
            print(f"  fixed/sticky: <{f['tag']}> covers {f['screen_covered_pct']}% of the screen, text: {f['text'][:70]!r}")
        print(f"desktop: {len(result['desktop']['screens'])} screens; written to {a.out}/rendered.json and rendered-mobile.txt")
        return 0
    except StopIteration:
        sys.exit("Chrome started but exposed no page target.")
    except (ConnectionError, RuntimeError, OSError, socket.timeout) as e:
        sys.exit(f"render failed: {type(e).__name__}: {e}")
    finally:
        if ws:
            ws.close()
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
