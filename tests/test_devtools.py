"""devtools.py: what a first-time visitor's browser sees (network, cookies, console), and the refuse-button test."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
from render import find_chrome  # noqa: E402

GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

BAD = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Fixture</title></head><body>
<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;background:#eee;padding:12px">Nous utilisons des cookies.
<button id="accept">Tout accepter</button> <button id="refuse">Tout refuser</button></div>
<h1>Hello</h1>
<script>
document.cookie = "_ga=GA1.1.1; path=/; max-age=31536000";
document.cookie = "session_token=abc; path=/";
new Image().src = "http://localhost:__PORT__/pixel.gif?pre=1";
fetch("/missing.json");
console.error("boom from fixture");
setTimeout(function () { throw new Error("late exception"); }, 100);
var t = Date.now(); while (Date.now() - t < 160) {}
document.getElementById('accept').addEventListener('click', function () { fetch('/accepted'); });
document.getElementById('refuse').addEventListener('click', function () {
  document.getElementById('cookie-banner').style.display = 'none';
  new Image().src = "http://localhost:__PORT__/pixel.gif?after=1";
});
</script></body></html>"""

GOOD = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Good</title></head><body>
<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies.
<button id="accept">Accepter</button> <button id="refuse">Refuser</button></div><h1>Hello</h1>
<script>document.getElementById('refuse').addEventListener('click', function () { document.getElementById('cookie-banner').style.display = 'none'; });
document.getElementById('accept').addEventListener('click', function () { fetch('/accepted'); });</script></body></html>"""

KEEPS = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Keeps</title></head><body>
<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept">Accepter</button> <button id="refuse">Refuser</button></div><h1>Hello</h1>
<script>document.cookie = "_ga=GA1.1.2; path=/"; document.getElementById('refuse').addEventListener('click', function () { document.getElementById('cookie-banner').style.display = 'none'; });</script></body></html>"""

LATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Late</title></head><body>
<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept">Accepter</button> <button id="refuse">Refuser</button></div><h1>Hello</h1>
<script>document.getElementById('refuse').addEventListener('click', function () { document.getElementById('cookie-banner').style.display = 'none'; document.cookie = "_fbp=fb.1.1.1; path=/"; });</script></body></html>"""

NOBANNER = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>NoBanner</title></head><body><h1>Hello</h1>
<script>document.cookie = "_ga=GA1.1.3; path=/";</script><footer id="cookie-footer"><a href="/legal">Mentions légales</a></footer></body></html>"""

NOREFUSE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>NoRefuse</title></head><body>
<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies.
<button id="accept">Tout accepter</button> <button id="custom">Personnaliser</button></div><h1>Hello</h1>
<script>document.getElementById('accept').addEventListener('click', function () { fetch('/accepted'); });</script></body></html>"""


HEAD = '<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Fixture</title></head><body>'
# A page with no cookie banner but a form whose button says "Refuser": the script must not click it (it did, once).
FORM_REFUSE = HEAD + '<h1>Devis</h1><form method="post" action="/devis-refuse"><button type="submit">Refuser le devis</button></form></body></html>'
# A newsletter pop-up with "Non merci" is not a cookie banner.
NEWSLETTER = HEAD + '<div id="newsletter-popup" style="position:fixed;bottom:0;padding:12px">Notre lettre <button>Non merci</button></div><h1>Hello</h1></body></html>'
# A real banner next to a form that also offers a "Refuser" submit button: only the banner's button may be clicked.
BANNER_AND_FORM = HEAD + ('<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept">Accepter</button> '
                          '<button id="refuse">Refuser</button></div><form method="post" action="/devis-refuse"><button type="submit">Refuser</button></form>'
                          '<script>document.getElementById("refuse").addEventListener("click", function () { document.getElementById("cookie-banner").style.display = "none"; });</script></body></html>')
# A banner inside an open shadow root (how some consent tools are built).
SHADOW = HEAD + ('<h1>Hello</h1><div id="consent-host"></div><script>const r = document.getElementById("consent-host").attachShadow({mode: "open"});'
                 'r.innerHTML = "<div id=\'cookie-box\' style=\'position:fixed;bottom:0;left:0;right:0;padding:12px\'>Cookies <button>Tout accepter</button> <button id=\'no\'>Tout refuser</button></div>";'
                 'r.getElementById("no").addEventListener("click", function () { r.getElementById("cookie-box").style.display = "none"; fetch("/refused-in-shadow"); });</script></body></html>')
# A consent tool served from another origin in an iframe cannot be read.
FRAME = HEAD + '<h1>Hello</h1><iframe id="consent-frame" title="consent" src="/frame-content" style="position:fixed;bottom:0;left:0;width:100%;height:120px"></iframe></body></html>'
# The refuse control is a link to the cookie policy page: clicking it would leave the page.
LINK_ONLY = HEAD + '<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept">Accepter</button> <a href="/cookie-policy">Refuser</a></div><h1>Hello</h1></body></html>'


# A refuse button tied to a form elsewhere on the page by the form= attribute: it submits that form when clicked.
FORM_ATTR = HEAD + ('<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept" type="button">Accepter</button> '
                    '<button form="danger">Refuser</button></div><form id="danger" method="post" action="/danger-delete"></form><h1>Hello</h1></body></html>')
# A link made to look like a button: clicking it leaves the page.
ROLE_LINK = HEAD + ('<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept" type="button">Accepter</button> '
                    '<a role="button" href="/danger-leave">Refuser</a></div><h1>Hello</h1></body></html>')
# A harmless-looking button whose script navigates away: the click is made, but the navigation is blocked and reported.
NAV_BUTTON = HEAD + ('<div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;padding:12px">Cookies. <button id="accept">Accepter</button> '
                     '<button id="refuse" onclick="location.href=\'/danger-script-nav\'">Refuser</button></div><h1>Hello</h1></body></html>')


class Fixture:
    def __init__(self):
        self.hits = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                path = self.path.split("?")[0]
                pages = {"/": BAD, "/good": GOOD, "/norefuse": NOREFUSE, "/keeps": KEEPS, "/nobanner": NOBANNER, "/late": LATE,
                         "/form-refuse": FORM_REFUSE, "/newsletter": NEWSLETTER, "/banner-and-form": BANNER_AND_FORM, "/shadow": SHADOW,
                         "/frame": FRAME, "/frame-content": '<html><body><button>Tout refuser</button></body></html>', "/link-only": LINK_ONLY,
                         "/form-attr": FORM_ATTR, "/role-link": ROLE_LINK, "/nav-button": NAV_BUTTON}
                if path in pages:
                    body = pages[path].replace("__PORT__", str(outer.port)).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                elif path == "/pixel.gif":
                    body = GIF
                    self.send_response(200)
                    self.send_header("Content-Type", "image/gif")
                else:
                    body = b"{}"
                    self.send_response(404 if path != "/accepted" else 200)
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                outer.hits.append("POST " + self.path)
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = b"<html><body>received</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def run(self, path, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "devtools.py"), f"http://127.0.0.1:{self.port}{path}", "--out", tmp,
                                "--settle", "1.5", "--tracker-host", "localhost", *extra], capture_output=True, text=True, timeout=120)
            self.last = r
            assert r.returncode == 0, r.stderr
            with open(os.path.join(tmp, "devtools.json"), encoding="utf-8") as fh:
                return json.load(fh)


@unittest.skipUnless(find_chrome(), "Chrome/Chromium not installed")
class DevtoolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = Fixture()
        cls.bad = cls.f.run("/", "--after-refuse")

    @classmethod
    def tearDownClass(cls):
        cls.f.srv.shutdown()
        cls.f.srv.server_close()

    def test_network_and_third_parties(self):
        d = self.bad
        self.assertTrue(d["load_event"])
        self.assertGreaterEqual(d["requests"]["total"], 3)
        hosts = {h["host"]: h for h in d["requests"]["third_party"]["hosts"]}
        self.assertIn("localhost", hosts)
        self.assertEqual(hosts["localhost"]["category"], "analytics")
        self.assertTrue(any("/missing.json" in r["url"] and r["status"] == 404 for r in d["failed_requests"]))

    def test_cookies_values_never_stored(self):
        d = self.bad
        names = {c["name"]: c for c in d["cookies"]}
        self.assertTrue(names["_ga"]["tracker_named"])
        self.assertEqual(names["session_token"]["issue"], "sensitive-looking name without HttpOnly")
        self.assertNotIn("GA1.1.1", json.dumps(d))
        self.assertNotIn('"abc"', json.dumps(d))

    def test_console_and_main_thread(self):
        texts = " | ".join(c["text"] for c in self.bad["console"])
        self.assertIn("boom from fixture", texts)
        self.assertIn("late exception", texts)
        mt = self.bad["main_thread"]
        self.assertGreaterEqual(mt["script_ms"], 120)             # the fixture busy-loops for 160 ms
        self.assertGreaterEqual(mt["busy_ms"], mt["script_ms"])
        self.assertGreater(mt["dom_nodes"], 5)

    def test_before_any_interaction(self):
        b = self.bad["before_any_interaction"]
        self.assertTrue(any(t["host"] == "localhost" for t in b["tracker_requests"]))
        self.assertTrue(any(c["name"] == "_ga" for c in b["tracker_cookies"]))
        banner = self.bad["consent_banner"]
        self.assertTrue(banner)
        self.assertIn("Tout refuser", banner[0]["buttons"])

    def test_refusal_not_respected_is_detected_and_accept_never_clicked(self):
        r = self.bad["after_refuse"]
        self.assertEqual(r["clicked"], "Tout refuser")
        self.assertTrue(r["verdict"].startswith("refusal not respected"))
        self.assertTrue(any(t["host"] == "localhost" for t in r["new_tracker_requests"]))
        self.assertTrue(any(c["name"] == "_ga" for c in r["tracker_cookies_kept_from_before"]))   # set before the choice, still there
        self.assertEqual(r["tracker_cookies_set_after"], [])                                         # nothing new was set by the click
        self.assertFalse(r["banner_still_visible"])
        self.assertNotIn("/accepted", self.f.hits)

    def test_clean_site_and_missing_refuse_button(self):
        good = self.f.run("/good", "--after-refuse")
        self.assertEqual(good["after_refuse"]["verdict"], "nothing new fired after refusing")
        self.assertEqual(good["before_any_interaction"]["tracker_requests"], [])
        keeps = self.f.run("/keeps", "--after-refuse")
        self.assertIn("tracker cookies set before the choice are still there", keeps["after_refuse"]["verdict"])
        late = self.f.run("/late", "--after-refuse")                                                    # the click itself sets a tracker cookie
        self.assertTrue(late["after_refuse"]["verdict"].startswith("refusal not respected"))
        self.assertTrue(any(c["name"] == "_fbp" for c in late["after_refuse"]["tracker_cookies_set_after"]))
        nb = self.f.run("/nobanner", "--after-refuse")                                                  # a footer link is not a banner
        self.assertEqual(nb["consent_banner"], [])
        self.assertTrue(nb["after_refuse"]["verdict"].startswith("no cookie banner detected by this script"), nb["after_refuse"]["verdict"])
        self.assertIsNone(nb["after_refuse"]["clicked"])
        nor = self.f.run("/norefuse", "--after-refuse")
        self.assertIsNone(nor["after_refuse"]["clicked"])
        self.assertIn("no refuse button", nor["after_refuse"]["verdict"])
        self.assertFalse(nor["after_refuse"]["refuse_visible"])
        self.assertTrue(nor["after_refuse"]["accept_visible"])
        self.assertNotIn("/accepted", self.f.hits)               # it never clicks accept

    def test_a_form_button_saying_refuse_is_never_clicked_when_there_is_no_banner(self):
        d = self.f.run("/form-refuse", "--after-refuse")
        self.assertIsNone(d["after_refuse"]["clicked"])
        self.assertNotIn("POST /devis-refuse", self.f.hits)

    def test_a_newsletter_popup_is_not_a_cookie_banner(self):
        d = self.f.run("/newsletter", "--after-refuse")
        self.assertEqual(d["consent_banner"], [])
        self.assertIsNone(d["after_refuse"]["clicked"])

    def test_only_the_banner_button_is_clicked_never_the_form_submit(self):
        d = self.f.run("/banner-and-form", "--after-refuse")
        self.assertEqual(d["after_refuse"]["clicked"], "Refuser")
        self.assertTrue(d["after_refuse"]["banner_still_visible"] is False)
        self.assertNotIn("POST /devis-refuse", self.f.hits)

    def test_a_banner_in_an_open_shadow_root_is_found_and_refused(self):
        d = self.f.run("/shadow", "--after-refuse")
        self.assertTrue(d["consent_banner"], "the banner inside the shadow root must be seen")
        self.assertEqual(d["after_refuse"]["clicked"], "Tout refuser")
        self.assertIn("/refused-in-shadow", self.f.hits)

    def test_a_consent_iframe_is_reported_not_ignored(self):
        d = self.f.run("/frame", "--after-refuse")
        self.assertTrue(d["consent_iframes"])
        self.assertIsNone(d["after_refuse"]["clicked"])
        self.assertIn("iframe", d["after_refuse"]["verdict"])

    def test_a_button_tied_to_a_form_by_the_form_attribute_is_never_clicked(self):
        d = self.f.run("/form-attr", "--after-refuse")
        self.assertIsNone(d["after_refuse"]["clicked"])
        self.assertNotIn("POST /danger-delete", self.f.hits)

    def test_a_link_dressed_as_a_button_is_never_clicked(self):
        d = self.f.run("/role-link", "--after-refuse")
        self.assertIsNone(d["after_refuse"]["clicked"])
        self.assertNotIn("/danger-leave", self.f.hits)

    def test_a_click_that_navigates_is_blocked_and_the_result_says_it_is_not_a_measurement(self):
        d = self.f.run("/nav-button", "--after-refuse")
        self.assertEqual(d["after_refuse"]["clicked"], "Refuser")
        self.assertNotIn("/danger-script-nav", self.f.hits)
        self.assertTrue(d["after_refuse"]["navigation_blocked"])
        self.assertIn("NOT a measurement", d["after_refuse"]["verdict"])

    def test_a_refuse_link_that_leaves_the_page_is_not_followed(self):
        d = self.f.run("/link-only", "--after-refuse")
        self.assertIsNone(d["after_refuse"]["clicked"])
        self.assertNotIn("/cookie-policy", self.f.hits)
        self.assertIn("no refuse button", d["after_refuse"]["verdict"])


if __name__ == "__main__":
    unittest.main()
