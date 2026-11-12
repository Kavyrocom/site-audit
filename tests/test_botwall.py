"""Offline tests: a bot-protection page (challenge, block, verification) is recognised and never audited as the site,
and a real page that merely talks about such things, or carries a passive Cloudflare script, is left alone."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import botwall  # noqa: E402
import facts  # noqa: E402
import render  # noqa: E402

CF_CHALLENGE = ("<!doctype html><html lang='en'><head><title>Just a moment...</title><meta name='robots' content='noindex,nofollow'></head>"
                "<body><h1>Checking your browser before accessing the site.</h1><noscript>Enable JavaScript and cookies to continue</noscript>"
                "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'></script></body></html>")
SUCURI_BLOCK = ("<html><head><title>Sucuri WebSite Firewall - Access Denied</title></head><body><h1>Access Denied - Sucuri Website Firewall</h1>"
                "<p>If you are the site owner, you can whitelist your IP.</p></body></html>")
AKAMAI_BLOCK = ("<HTML><HEAD><TITLE>Access Denied</TITLE></HEAD><BODY><H1>Access Denied</H1>\nYou don't have permission to access "
                "\"http&#58;&#47;&#47;site&#46;example&#47;\" on this server.<P>\nReference&#32;&#35;18&#46;2d4f1c&#46;1700000000&#46;abc123\n</BODY></HTML>")
IMPERVA = "<html><body>Request unsuccessful. Incapsula incident ID: 123-456<script src='/_Incapsula_Resource?SWJIYLWA=1'></script></body></html>"
LONG = " ".join(["word"] * 300)
# A real article about these protections: it quotes the markers but has real content.
ARTICLE = (f"<html><head><title>How Cloudflare challenges work</title></head><body><h1>Just a moment...</h1><p>The page says "
           f"'Checking your browser before accessing' and loads cf_chl_opt. {LONG}</p></body></html>")
# A real page of a site that runs Cloudflare's passive script.
PASSIVE = (f"<html><head><title>Shop</title></head><body><h1>Shop</h1><p>{LONG}</p>"
           "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></body></html>")
# A short real page (a coming-soon page) of a site that runs the same passive script: short is not enough to be a wall.
THIN_PASSIVE = ("<html><head><title>Shop</title></head><body><h1>Shop</h1><p>Opening soon.</p>"
                "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></body></html>")
# A short but real sign-in page that says "verify you are human" once.
LOGIN = "<html><head><title>Sign in</title></head><body><h1>Sign in</h1><form><label>Email <input></label><p>Please verify you are human.</p><button>Go</button></form></body></html>"


class DetectTests(unittest.TestCase):
    def test_cloudflare_header_is_enough(self):
        r = botwall.detect(403, {"CF-Mitigated": "challenge"}, "")
        self.assertEqual((r["vendor"], r["confidence"], r["kind"]), ("cloudflare", "high", "challenge"))

    def test_cloudflare_challenge_page_is_found_whatever_the_status(self):
        for status in (200, 403, 503):
            r = botwall.detect(status, {"server": "cloudflare"}, CF_CHALLENGE)
            self.assertIsNotNone(r, status)
            self.assertEqual((r["vendor"], r["confidence"], r["kind"]), ("cloudflare", "high", "challenge"), status)

    def test_block_pages_of_other_protections(self):
        for body, vendor in ((SUCURI_BLOCK, "sucuri"), (AKAMAI_BLOCK, "akamai"), (IMPERVA, "imperva")):
            r = botwall.detect(403, {}, body)
            self.assertIsNotNone(r, vendor)
            self.assertEqual((r["vendor"], r["confidence"]), (vendor, "high"))
        self.assertEqual(botwall.detect(403, {}, SUCURI_BLOCK)["kind"], "block")

    def test_a_browser_page_is_judged_from_its_title_and_text(self):
        r = botwall.detect(200, {}, "", title="Just a moment...", text="Checking your browser before accessing the site.")
        self.assertEqual((r["vendor"], r["confidence"]), ("cloudflare", "high"))
        self.assertIsNone(botwall.detect(200, {}, "", title="Shop", text=LONG))

    def test_a_real_page_that_quotes_the_markers_is_not_a_wall(self):
        self.assertIsNone(botwall.detect(200, {}, ARTICLE))

    def test_the_passive_cloudflare_script_alone_is_not_a_wall(self):
        self.assertIsNone(botwall.detect(200, {"server": "cloudflare"}, PASSIVE))

    def test_a_short_real_page_with_the_passive_script_is_not_a_wall(self):
        self.assertIsNone(botwall.detect(200, {"server": "cloudflare"}, THIN_PASSIVE))

    def test_a_short_real_page_with_one_generic_phrase_is_not_a_wall(self):
        self.assertIsNone(botwall.detect(200, {}, LOGIN))

    def test_a_refusal_from_a_protection_server_without_site_content_is_medium(self):
        r = botwall.detect(403, {"server": "cloudflare"}, "<h1>Forbidden</h1>")
        self.assertEqual((r["vendor"], r["confidence"], r["kind"]), ("cloudflare", "medium", "block"))

    def test_generic_verification_wording_is_medium_and_needs_two_phrases_when_the_status_is_200(self):
        two = "<html><title>Hold on</title><body>Are you a robot? Please verify you are a human.</body></html>"
        r = botwall.detect(200, {}, two)
        self.assertEqual((r["vendor"], r["confidence"], r["kind"]), (None, "medium", "verification"))

    def test_an_ordinary_404_or_empty_answer_is_nothing(self):
        self.assertIsNone(botwall.detect(404, {"server": "nginx"}, "<h1>Not found</h1>"))
        self.assertIsNone(botwall.detect(404, {"server": "cloudflare"}, ""))        # a plain 404 behind a CDN is not a challenge
        self.assertIsNone(botwall.detect(200, None, None))
        self.assertIsNone(botwall.detect(0, {}, ""))

    def test_the_sentence_names_the_vendor_and_the_way_out(self):
        s = botwall.one_line(botwall.detect(403, {"cf-mitigated": "challenge"}, ""))
        self.assertIn("Cloudflare", s)
        self.assertIn("not the site", s)
        self.assertIn("allow the audit machine's address", botwall.GUIDANCE)
        self.assertNotIn("\u2014", botwall.GUIDANCE + s)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?")[0]
        mode = self.server.mode
        if path == "/robots.txt":
            return self.send(404, "nope", "text/plain")
        if mode == "challenge_200" or (mode == "challenge_403" and path != "/sitemap.xml"):
            code = 200 if mode == "challenge_200" else 403
            return self.send(code, CF_CHALLENGE, "text/html", {"cf-mitigated": "challenge"} if code == 403 else {})
        if mode == "passive_site":
            return self.send(200, PASSIVE, "text/html")
        if mode == "site_with_one_wall" and path == "/b":
            return self.send(403, CF_CHALLENGE, "text/html", {"cf-mitigated": "challenge"})
        if mode in ("site_with_one_wall", "plain_404") and path == "/":
            return self.send(200, f"<html lang='en'><head><title>Home</title><meta name='description' content='Home'><link rel='canonical' href='/'>"
                                  f"<meta name='viewport' content='width=device-width'></head><body><h1>Home</h1><p>{LONG}</p>"
                                  "<a href='/a'>A</a> <a href='/b'>B</a></body></html>", "text/html")
        if mode == "site_with_one_wall" and path == "/a":
            return self.send(200, f"<html lang='en'><head><title>A</title><meta name='description' content='A'></head><body><h1>A</h1><p>{LONG}</p></body></html>", "text/html")
        return self.send(404, "not found", "text/plain")

    def send(self, code, body, ctype, extra=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


class ServerMixin:
    def serve(self, mode):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        srv.mode = mode
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        return f"http://127.0.0.1:{srv.server_port}/"

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), *args], capture_output=True, text=True, timeout=90)



class ServerTests(ServerMixin, unittest.TestCase):
    def test_facts_stops_on_a_403_challenge_and_says_who(self):
        url = self.serve("challenge_403")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "facts.json")
            p = self.run_script("facts.py", url, "--out", out)
            with open(out, encoding="utf-8") as fh:
                f = json.load(fh)
        self.assertEqual(p.returncode, 1)
        self.assertIn("Cloudflare", p.stderr)
        self.assertIn("do not try to get past the protection", p.stderr)
        self.assertEqual(f["bot_wall"]["vendor"], "cloudflare")

    def test_facts_stops_on_a_challenge_served_with_status_200(self):
        url = self.serve("challenge_200")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "facts.json")
            p = self.run_script("facts.py", url, "--out", out)
            with open(out, encoding="utf-8") as fh:
                f = json.load(fh)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(f["bot_wall"]["confidence"], "high")
        self.assertNotIn("title", f)                       # nothing from the protection page is reported as the site's facts
        self.assertNotIn("site_level", f)

    def test_facts_on_a_plain_404_still_says_unreachable_without_a_bot_wall(self):
        url = self.serve("plain_404") + "nothing-here"
        p = self.run_script("facts.py", url)
        self.assertEqual(p.returncode, 1)
        self.assertIn("page unreachable: status=404", p.stderr)
        self.assertNotIn("bot_wall", p.stdout)

    def test_crawl_does_not_audit_a_start_page_that_is_a_challenge(self):
        url = self.serve("challenge_200")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "crawl")
            p = self.run_script("crawl.py", url, "--out", out, "--delay", "0")
            with open(os.path.join(out, "summary.json"), encoding="utf-8") as fh:
                s = json.load(fh)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not the site", p.stderr)
        self.assertEqual(s["pages_blocked_by_bot_protection"], 1)
        self.assertFalse(s["crawl_complete"])
        self.assertTrue(any("start page was not audited" in w for w in s["warnings"]))
        i = s["issues"]
        for key in ("missing_meta_description", "thin_content_under_150_words", "noindex_pages", "canonical_missing", "missing_viewport"):
            self.assertEqual(i[key], [], key)               # the protection page's own faults are not the site's faults

    def test_crawl_sets_aside_one_protected_page_and_keeps_the_others(self):
        url = self.serve("site_with_one_wall")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "crawl")
            p = self.run_script("crawl.py", url, "--out", out, "--delay", "0", "--workers", "1")
            with open(out + "/summary.json", encoding="utf-8") as fh:
                s = json.load(fh)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(s["pages_blocked_by_bot_protection"], 1)
        self.assertEqual(s["issues"]["blocked_by_bot_protection"][0]["vendor"], "cloudflare")
        self.assertTrue(s["issues"]["blocked_by_bot_protection"][0]["url"].endswith("/b"))
        self.assertFalse(any(e["url"].endswith("/b") for e in s["issues"]["error_pages"]))      # not reported as a broken page
        self.assertFalse(s["crawl_complete"])
        self.assertTrue(any("set aside" in w for w in s["warnings"]))
        self.assertEqual(s["issues"]["thin_content_under_150_words"], [])

    def test_fetch_keeps_the_body_of_an_error_only_when_asked(self):
        url = self.serve("challenge_403")
        self.assertEqual(facts.fetch(url, facts.DEFAULT_UA)["body"], "")
        self.assertIn("Just a moment", facts.fetch(url, facts.DEFAULT_UA, error_body=True)["body"])


@unittest.skipUnless(render.find_chrome(), "Chrome/Chromium not available")
class RenderWallTests(ServerMixin, unittest.TestCase):
    def test_render_flags_a_challenge_page_and_stops(self):
        url = self.serve("challenge_200")
        with tempfile.TemporaryDirectory() as tmp:
            p = self.run_script("render.py", url, "--out", os.path.join(tmp, "shots"))
            with open(os.path.join(tmp, "shots", "rendered.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(data["bot_wall"]["vendor"], "cloudflare")
        self.assertIn("do not judge UX, conversion or copy", p.stderr)

    def test_render_leaves_a_real_page_with_the_passive_script_alone(self):
        url = self.serve("passive_site")
        with tempfile.TemporaryDirectory() as tmp:
            p = self.run_script("render.py", url, "--out", os.path.join(tmp, "shots"))
            with open(os.path.join(tmp, "shots", "rendered.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("bot_wall", data)


if __name__ == "__main__":
    unittest.main()
