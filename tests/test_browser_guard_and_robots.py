"""Regression cases for the browser guard, robots.txt, redaction and the Lighthouse wrapper. Each one was reproduced before it was fixed.

The "public start, private target" cases need a public-looking start address on a machine with none: they patch
safenet so that 127.0.0.1 counts as public while 127.0.0.2 (also loopback) stays private, then run the real scripts
in this process.
"""
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import crawl  # noqa: E402
import devtools  # noqa: E402
import facts  # noqa: E402
import redact  # noqa: E402
import render  # noqa: E402
import robotsrules  # noqa: E402
import safenet  # noqa: E402

_REAL_IS_PUBLIC = safenet._is_public


def pretend_127_0_0_1_is_public():
    return mock.patch.object(safenet, "_is_public", lambda a: a == "127.0.0.1" or _REAL_IS_PUBLIC(a))


class SharedAddressSpaceIsNotPublic(unittest.TestCase):
    def test_cgnat_and_tailscale_addresses_are_private(self):
        for addr in ("100.64.0.1", "100.64.1.2", "100.127.255.254", "::ffff:100.64.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "127.0.0.1"):
            self.assertFalse(_REAL_IS_PUBLIC(addr), addr)
        for addr in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
            self.assertTrue(_REAL_IS_PUBLIC(addr), addr)


class RobotsAsTheStandardReadsThem(unittest.TestCase):
    def allowed(self, body, url, status=200, token="SiteAuditSkill"):
        return robotsrules.Robots(status, body, token).allowed(url)

    def test_wildcards_and_end_anchor(self):
        self.assertFalse(self.allowed("User-agent: *\nDisallow: /*", "https://x/anything"))
        self.assertFalse(self.allowed("User-agent: *\nDisallow: /*.php$", "https://x/a.php"))
        self.assertTrue(self.allowed("User-agent: *\nDisallow: /*.php$", "https://x/a.php5"))
        self.assertFalse(self.allowed("User-agent: *\nDisallow: /*?", "https://x/p?y=1"))
        self.assertTrue(self.allowed("User-agent: *\nDisallow: /*?", "https://x/p"))

    def test_the_longest_rule_wins_and_allow_wins_a_tie(self):
        body = "User-agent: *\nAllow: /\nDisallow: /private"
        self.assertFalse(self.allowed(body, "https://x/private/a"))
        self.assertTrue(self.allowed(body, "https://x/open"))
        self.assertTrue(self.allowed("User-agent: *\nAllow: /a/b\nDisallow: /a", "https://x/a/b/c"))
        self.assertTrue(self.allowed("User-agent: *\nAllow: /a\nDisallow: /a", "https://x/a"))

    def test_status_of_robots_txt_decides_when_there_is_no_file(self):
        self.assertFalse(self.allowed("", "https://x/a", status=503))
        self.assertFalse(self.allowed("", "https://x/a", status=0))
        self.assertTrue(self.allowed("", "https://x/a", status=404))
        self.assertTrue(self.allowed("User-agent: *\nDisallow:", "https://x/a"))

    def test_our_own_group_wins_over_the_wildcard(self):
        self.assertFalse(self.allowed("User-agent: SiteAuditSkill\nDisallow: /\nUser-agent: *\nAllow: /", "https://x/a"))
        self.assertTrue(self.allowed("User-agent: GPTBot\nDisallow: /\nUser-agent: *\nDisallow: /wp-admin/", "https://x/a"))

    def test_crawl_delay_is_read_from_the_group_that_applies(self):
        self.assertEqual(robotsrules.Robots(200, "User-agent: *\nCrawl-delay: 5\nDisallow: /x", "SiteAuditSkill").crawl_delay(), 5.0)


class FactsFalsePositives(unittest.TestCase):
    def test_a_link_to_an_http_page_is_not_mixed_content(self):
        html = '<a href="http://x.com/a">l</a><img src="http://a/b.png"><link rel="stylesheet" href="http://c/s.css"><link rel="canonical" href="http://d/"><script src="http://e/j.js"></script>'
        self.assertEqual(facts.mixed_content_count(html), 3)
        self.assertEqual(facts.mixed_content_count('<a href="http://x.com">only a link</a>'), 0)

    def test_links_to_a_tool_are_not_the_tool(self):
        surface = facts.code_surface('<p><a href="https://posthog.com/blog">post</a> <a href="https://hotjar.com">h</a> <a href="https://clarity.ms">c</a></p>')
        for name in ("posthog", "hotjar", "clarity"):
            self.assertNotIn(name, surface)
        self.assertIn("hotjar", facts.code_surface('<script src="https://static.hotjar.com/c/hotjar-1.js"></script>'))

    def test_disallow_slash_star_is_disallow_all(self):
        self.assertTrue(facts.robots_disallows_all("User-agent: *\nDisallow: /*"))
        self.assertFalse(facts.robots_disallows_all("User-agent: *\nDisallow: /private"))


class RedactLeaksFound(unittest.TestCase):
    CASES = {
        "WP_APP_PASSWORD=abcd EFGH 1234 ijkl MNOP 5678": ("abcd", "EFGH", "5678"),
        "abcd EFGH 1234 ijkl MNOP 5678": ("abcd", "EFGH", "5678"),
        "Application password: abcd EFGH 1234 ijkl MNOP 5678": ("EFGH", "MNOP", "5678"),
        "0 3 * * * mysqldump -u root --password S3cretPw wp > /b.sql": ("S3cretPw",),
        "curl -u admin:S3cretPw https://site/wp-json": ("S3cretPw",),
        "sshpass -p S3cretPw ssh u@h": ("S3cretPw",),
        "-----BEGIN PGP PRIV" + "ATE KEY BLOCK-----\nlQOYBGXyz123\n-----END PGP PRIV" + "ATE KEY BLOCK-----": ("lQOYBGXyz123",),
        "DefaultEndpointsProtocol=https;AccountName=x;Account" + "Key=Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA==;": ("Zm9vYmFy",),
        "admin:$apr" + "1$Xy12ab$Qk3l1E2pS9eRtYb0vC5m81": ("Xy12ab", "Qk3l1E2pS9"),
        "https://hooks.sl" + "ack.com/services/" + "T0123ABCD/B0456EFGH/" + "AbCdEfGhIjKlMnOpQrStUvWx": ("AbCdEfGh",),
        "bot token 12345678" + ":" + "AAH" + "dqTcvCH1vGWJxfSeofSAs0K5PALDsaw": ("AAHdqTcv",),
        "Authorization: abcdef123456": ("abcdef123456",),
        "mdp S3cretPw": ("S3cretPw",),
        "password: |\n  S3cretPw\nuser: x": ("S3cretPw",),
        "--password=Hunter2x": ("Hunter2x",),
    }

    def test_each_form_is_masked(self):
        for text, secrets in self.CASES.items():
            masked, n = redact.redact(text)
            for s in secrets:
                self.assertNotIn(s, masked, text)

    def test_masking_twice_changes_nothing(self):
        for text in self.CASES:
            once, _ = redact.redact(text)
            self.assertEqual(redact.redact(once)[0], once, text)

    def test_ordinary_text_is_left_alone(self):
        for text in ("password reset link sent", "the password policy requires 12 characters", "six four word text here and then more words", "user: admin"):
            self.assertEqual(redact.redact(text)[0], text)


class FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, s):
        self.sent.append(json.loads(s))


def paused(url, rtype="Document", frame="MAIN", method="GET"):
    return {"method": "Fetch.requestPaused", "params": {"requestId": "r1", "resourceType": rtype, "frameId": frame, "request": {"url": url, "method": method}}}


class BrowserGuardUnit(unittest.TestCase):
    def make(self, private_start=False):
        c = render.CDP(FakeWS())
        c.guard_private = private_start
        c.main_frame = "MAIN"
        return c

    def test_private_and_non_http_requests_are_failed_and_public_ones_continue(self):
        with pretend_127_0_0_1_is_public():
            c = self.make()
            for url, failed in (("http://127.0.0.2:9/x", True), ("file:///etc/passwd", True), ("http://169.254.169.254/latest", True),
                                ("http://127.0.0.1:9/ok", False), ("data:text/plain,hi", False)):
                c.ws.sent.clear()
                self.assertTrue(c._guard(paused(url)))
                self.assertEqual(c.ws.sent[-1]["method"], "Fetch.failRequest" if failed else "Fetch.continueRequest", url)
        self.assertEqual({b["url"][:12] for b in c.blocked}, {"http://127.0", "file:///etc/", "http://169.2"})

    def test_a_private_start_may_stay_private(self):
        c = self.make(private_start=True)
        c._guard(paused("http://127.0.0.2:9/x"))
        self.assertEqual(c.ws.sent[-1]["method"], "Fetch.continueRequest")

    def test_after_the_click_the_page_may_not_navigate_or_submit(self):
        with pretend_127_0_0_1_is_public():
            c = self.make()
            c.block_navigation = True
            c._guard(paused("http://127.0.0.1:9/leave", method="POST"))
            self.assertEqual(c.ws.sent[-1]["method"], "Fetch.failRequest")
            self.assertEqual(c.nav_blocked[0]["method"], "POST")
            c._guard(paused("http://127.0.0.1:9/pixel.gif", rtype="Image"))
            self.assertEqual(c.ws.sent[-1]["method"], "Fetch.continueRequest")

    def test_only_the_page_itself_counts_as_a_refusal(self):
        with pretend_127_0_0_1_is_public():
            c = self.make()
            c._guard(paused("http://127.0.0.2:9/img.png", rtype="Image"))
            self.assertIsNone(c.refusal())
            c._guard(paused("http://127.0.0.2:9/page"))
            self.assertIsNotNone(c.refusal())


class Server:
    """A site on 127.0.0.1 and an 'internal' service on 127.0.0.2. The internal one records every request."""

    def __init__(self, routes):
        self.internal_hits, self.site_hits = [], []
        outer = self

        class Internal(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.internal_hits.append(self.path)
                body = b"<html><body><h1>INTERNAL-SECRET-42</h1></body></html>" if self.path != "/s.xml" else b"<urlset></urlset>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html" if self.path != "/s.xml" else "application/xml")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.internal = http.server.ThreadingHTTPServer(("127.0.0.2", 0), Internal)
        self.iport = self.internal.server_address[1]

        class Site(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.site_hits.append(self.path)
                kind, payload = routes(self.path, outer.iport)
                if kind == "redirect":
                    self.send_response(302)
                    self.send_header("Location", payload)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = payload.encode()
                self.send_response(int(kind) if kind.isdigit() else 200)
                self.send_header("Content-Type", "text/plain" if self.path.endswith("robots.txt") else "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        self.sport = self.site.server_address[1]
        for srv in (self.internal, self.site):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    def close(self):
        for srv in (self.internal, self.site):
            srv.shutdown()
            srv.server_close()


def run_main(module, argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["x"] + argv), redirect_stdout(out), redirect_stderr(err):
        try:
            code = module.main()
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class PublicStartNeverReachesPrivate(unittest.TestCase):
    def test_a_sitemap_declared_in_robots_txt_cannot_point_inside(self):
        def routes(path, iport):
            if path == "/robots.txt":
                return "ok", f"User-agent: *\nAllow: /\nSitemap: http://127.0.0.2:{iport}/s.xml\n"
            if path == "/":
                return "ok", "<html><head><title>t</title></head><body><h1>Hello</h1></body></html>"
            return "404", "no"
        srv = Server(routes)
        self.addCleanup(srv.close)
        with tempfile.TemporaryDirectory() as tmp, pretend_127_0_0_1_is_public():
            run_main(crawl, [f"http://127.0.0.1:{srv.sport}/", "--max-pages", "2", "--delay", "0", "--out", tmp])
        self.assertEqual(srv.internal_hits, [], "a sitemap named by a public site must not make the audit call a private address")

    def test_a_sitemap_index_cannot_point_inside_either(self):
        def routes(path, iport):
            if path == "/robots.txt":
                return "ok", "User-agent: *\nAllow: /\nSitemap: http://127.0.0.1:%d/sitemap.xml\n" % srv.sport
            if path == "/sitemap.xml":
                return "ok", f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>http://127.0.0.2:{iport}/s.xml</loc></sitemap></sitemapindex>'
            if path == "/":
                return "ok", "<html><head><title>t</title></head><body><h1>Hello</h1></body></html>"
            return "404", "no"
        srv = Server(routes)
        self.addCleanup(srv.close)
        with tempfile.TemporaryDirectory() as tmp, pretend_127_0_0_1_is_public():
            run_main(crawl, [f"http://127.0.0.1:{srv.sport}/", "--max-pages", "2", "--delay", "0", "--out", tmp])
        self.assertEqual(srv.internal_hits, [])

    def test_a_503_robots_txt_stops_the_crawl(self):
        def routes(path, iport):
            return ("503", "down") if path == "/robots.txt" else ("ok", "<html><head><title>t</title></head><body><h1>x</h1></body></html>")
        srv = Server(routes)
        self.addCleanup(srv.close)
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_main(crawl, [f"http://127.0.0.1:{srv.sport}/", "--max-pages", "2", "--delay", "0", "--out", tmp])
        self.assertIn("stay away", err)
        self.assertNotIn("/", [p for p in srv.site_hits if p != "/robots.txt" and not p.startswith("/sitemap")], "no page may be fetched")

    def redirect_routes(self, path, iport):
        if path == "/redir":
            return "redirect", f"http://127.0.0.2:{iport}/secret"
        if path == "/jsredir":
            return "ok", f"<html><body><p>x</p><script>location.href='http://127.0.0.2:{iport}/secret'</script></body></html>"
        return "404", "no"

    @unittest.skipUnless(render.find_chrome(), "Chrome/Chromium not installed")
    def test_render_refuses_a_redirect_to_a_private_address(self):
        srv = Server(self.redirect_routes)
        self.addCleanup(srv.close)
        for path in ("/redir", "/jsredir"):
            with tempfile.TemporaryDirectory() as tmp, pretend_127_0_0_1_is_public():
                code, out, err = run_main(render, [f"http://127.0.0.1:{srv.sport}{path}", "--out", tmp, "--settle", "0.5", "--max-slices", "1"])
                self.assertNotEqual(code, 0, path)
                self.assertIn("refused", str(code), path)
                text = ""
                tp = os.path.join(tmp, "rendered-mobile.txt")
                if os.path.exists(tp):
                    with open(tp, encoding="utf-8") as fh:
                        text = fh.read()
                self.assertNotIn("INTERNAL-SECRET-42", text, path)
        self.assertEqual(srv.internal_hits, [], "the private address must not even be requested")

    @unittest.skipUnless(render.find_chrome(), "Chrome/Chromium not installed")
    def test_devtools_refuses_a_redirect_to_a_private_address(self):
        srv = Server(self.redirect_routes)
        self.addCleanup(srv.close)
        with tempfile.TemporaryDirectory() as tmp, pretend_127_0_0_1_is_public():
            code, out, err = run_main(devtools, [f"http://127.0.0.1:{srv.sport}/redir", "--out", tmp, "--settle", "0.5"])
            self.assertIn("refused", str(code))
            self.assertFalse(os.path.exists(os.path.join(tmp, "devtools.json")))
        self.assertEqual(srv.internal_hits, [])


FAKE_LIGHTHOUSE = """#!/bin/sh
# stands in for the real Lighthouse: writes a minimal report, or hangs while leaving a child process behind
OUT=""
for a in "$@"; do case "$a" in --output-path=*) OUT="${a#--output-path=}";; esac; done
if [ -n "$FAKE_LH_HANG" ]; then sleep 300 & echo $! > "$FAKE_LH_HANG"; wait; fi
cat > "$OUT" <<JSON
{"finalDisplayedUrl": "$FAKE_LH_FINAL", "categories": {"performance": {"score": 0.9}}, "audits": {}}
JSON
"""


class LighthouseWrapper(unittest.TestCase):
    def setUp(self):
        import stat
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        path = os.path.join(self.tmp, "lighthouse")
        with open(path, "w") as fh:
            fh.write(FAKE_LIGHTHOUSE)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def run_it(self, extra_env, *args, timeout=60):
        import subprocess
        env = {"PATH": self.tmp + os.pathsep + os.environ.get("PATH", ""), **extra_env}
        return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "lh_median.py"), "http://127.0.0.1:9/", "--runs", "1", "--out", os.path.join(self.tmp, "lh"), *args],
                              capture_output=True, text=True, timeout=timeout, env=env)

    def test_a_report_whose_final_page_is_not_http_is_refused_and_removed(self):
        r = self.run_it({"FAKE_LH_FINAL": "file:///etc/passwd"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "lh", "run1.json")))

    def test_a_normal_report_still_works(self):
        r = self.run_it({"FAKE_LH_FINAL": "http://127.0.0.1:9/"})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_timeout_stops_the_whole_process_group(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        r = self.run_it({"FAKE_LH_FINAL": "http://127.0.0.1:9/", "FAKE_LH_HANG": pidfile}, "--timeout", "2")
        self.assertIn("timeout", r.stderr)
        import time
        with open(pidfile) as fh:
            pid = int(fh.read().strip())
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        if alive:
            os.kill(pid, 9)
        self.assertFalse(alive, "the child Chrome stand-in was left running after the timeout")


if __name__ == "__main__":
    unittest.main()
