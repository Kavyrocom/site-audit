"""Regression cases for the filtering proxy, robots.txt, the crawler, facts, redaction, the fix tracker and the report.
Each one was reproduced before it was fixed (data leaving through the evidence files is in test_personal_data_and_leaks.py).

The "public site, private target" cases need a public-looking site on a machine with none: they patch safenet so
that 127.0.0.1 and 127.0.0.3 count as public while 127.0.0.2 (also loopback) is the private service that must never be
reached, then run the real scripts, and a real Chrome, in this process.
"""
import http.client
import http.server
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import build_report  # noqa: E402
import consistency  # noqa: E402
import crawl  # noqa: E402
import devtools  # noqa: E402
import facts  # noqa: E402
import netguard  # noqa: E402
import psi  # noqa: E402
import redact  # noqa: E402
import render  # noqa: E402
import robotsrules  # noqa: E402
import safenet  # noqa: E402

_REAL_IS_PUBLIC = safenet._is_public


def pretend_public(*addrs):
    return mock.patch.object(safenet, "_is_public", lambda a: a in addrs or _REAL_IS_PUBLIC(a))


class Recorder:
    """A tiny HTTP server on one loopback address that records every path asked of it."""

    def __init__(self, host, port, routes):
        self.hits = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                outer.hits.append(self.path)
                code, ctype, body = routes(self.path)
                data = body.encode() if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_GET

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer((host, port), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def run_main(module, argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["x"] + argv), redirect_stdout(out), redirect_stderr(err):
        try:
            code = module.main()
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------------------------------------------
class TheProxyJudgesEveryConnection(unittest.TestCase):
    """netguard.py: what Chrome (or Lighthouse) is allowed to reach, whatever the page does to get there."""

    def setUp(self):
        self.internal = Recorder("127.0.0.2", 0, lambda p: (200, "text/html", "INTERNAL-SECRET"))
        self.site = Recorder("127.0.0.1", self.internal.port, lambda p: (200, "text/html", "public site"))   # same port number, another address
        self.addCleanup(self.internal.close)
        self.addCleanup(self.site.close)

    def through_proxy(self, proxy, request_line):
        s = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)
        s.sendall(request_line.encode() + b"\r\n\r\n")
        data = b""
        s.settimeout(5)
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        s.close()
        return data.decode("latin-1")

    def test_a_private_address_is_refused_for_http_and_for_connect(self):
        with pretend_public("127.0.0.1"):
            proxy = netguard.GuardProxy(allow_private=False)
            self.addCleanup(proxy.stop)
            port = self.internal.port
            ok = self.through_proxy(proxy, f"GET http://127.0.0.1:{port}/ok HTTP/1.1\r\nHost: 127.0.0.1:{port}")
            self.assertIn("200", ok.split("\r\n")[0])
            self.assertIn("public site", ok)
            for line in (f"GET http://127.0.0.2:{port}/secret HTTP/1.1\r\nHost: 127.0.0.2:{port}",
                         f"CONNECT 127.0.0.2:{port} HTTP/1.1\r\nHost: 127.0.0.2:{port}",
                         f"GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\nHost: 169.254.169.254",
                         f"GET http://[::1]:{port}/x HTTP/1.1\r\nHost: [::1]:{port}"):
                reply = self.through_proxy(proxy, line)
                self.assertIn(" 403 ", reply.split("\r\n")[0] + " ", line)
                self.assertNotIn("INTERNAL-SECRET", reply)
            self.assertEqual(self.internal.hits, [], "the private service must not even be requested")
            self.assertTrue(proxy.refused)

    def test_an_audit_that_starts_on_a_private_host_may_stay_there(self):
        proxy = netguard.GuardProxy(allow_private=True)
        self.addCleanup(proxy.stop)
        reply = self.through_proxy(proxy, f"GET http://127.0.0.2:{self.internal.port}/x HTTP/1.1\r\nHost: x")
        self.assertIn("INTERNAL-SECRET", reply)

    def test_a_dns_answer_that_changes_between_check_and_connection_gets_nothing(self):
        """Rebinding: the name resolves to a public address when judged, to a private one when connected. The proxy
        resolves once and connects to the address it judged, so the second answer never matters."""
        answers = iter([["127.0.0.1"], ["127.0.0.2"], ["127.0.0.2"]])
        with pretend_public("127.0.0.1"), mock.patch.object(safenet, "_resolve", lambda host: next(answers, ["127.0.0.2"])):
            proxy = netguard.GuardProxy(allow_private=False)
            self.addCleanup(proxy.stop)
            reply = self.through_proxy(proxy, f"GET http://rebind.example:{self.internal.port}/x HTTP/1.1\r\nHost: rebind.example")
            self.assertIn("public site", reply)
            self.assertEqual(self.internal.hits, [])


# --------------------------------------------------------------------------------------------------------------
@unittest.skipUnless(render.find_chrome(), "Chrome/Chromium not installed")
class ChromeCannotBeUsedToReachAnInternalService(unittest.TestCase):
    """The blocking case: a cross-site iframe, a service worker or a WebSocket got around the guard
    that only watched the requests of the page itself, and the internal page ended up in the report's screenshots."""

    @classmethod
    def setUpClass(cls):
        cls.internal = Recorder("127.0.0.2", 0, lambda p: (200, "text/html", "<html><body><h1>INTERNAL-SECRET-42</h1></body></html>"))
        iport = cls.internal.port
        third_hits = []

        def third(path):
            third_hits.append(path)
            return 200, "text/html", (f"<html><body><p>third site</p><img src='http://127.0.0.2:{iport}/oopif-img'>"
                                      f"<script>fetch('http://127.0.0.2:{iport}/oopif-fetch').catch(()=>0);"
                                      f"setTimeout(()=>{{location.href='http://127.0.0.2:{iport}/oopif-nav'}}, 300);</script></body></html>")
        cls.third = Recorder("127.0.0.3", 0, third)

        def site(path):
            if path == "/sw.js":
                return 200, "application/javascript", f"self.addEventListener('fetch',e=>{{}});fetch('http://127.0.0.2:{iport}/sw-fetch').catch(()=>0);"
            if path == "/oopif":
                return 200, "text/html", f"<html><body><h1>site</h1><iframe src='http://127.0.0.3:{cls.third.port}/frame' width=300 height=200></iframe></body></html>"
            if path == "/swpage":
                return 200, "text/html", "<html><body><h1>site</h1><script>navigator.serviceWorker.register('/sw.js').catch(()=>0)</script></body></html>"
            if path == "/ws":
                return 200, "text/html", f"<html><body><h1>site</h1><script>try{{new WebSocket('ws://127.0.0.2:{iport}/ws-secret')}}catch(e){{}}</script></body></html>"
            if path == "/prefetch":
                return 200, "text/html", f"<html><head><link rel=preconnect href='http://127.0.0.2:{iport}'><link rel=prefetch href='http://127.0.0.2:{iport}/prefetch'></head><body><h1>site</h1></body></html>"
            return 404, "text/plain", "no"
        cls.site = Recorder("127.0.0.1", 0, site)

    @classmethod
    def tearDownClass(cls):
        for s in (cls.internal, cls.third, cls.site):
            s.close()

    def reset(self):
        self.internal.hits.clear()

    def check(self, module, path, extra=()):
        self.reset()
        with tempfile.TemporaryDirectory() as tmp, pretend_public("127.0.0.1", "127.0.0.3"):
            argv = [f"http://127.0.0.1:{self.site.port}{path}", "--out", tmp, "--settle", "1.2", *extra]
            code, out, err = run_main(module, argv)
            text = ""
            for name in ("rendered-mobile.txt", "devtools.json"):
                p = os.path.join(tmp, name)
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as fh:
                        text += fh.read()
            self.assertNotIn("INTERNAL-SECRET-42", text, f"{module.__name__} {path}")
            self.assertEqual(self.internal.hits, [], f"{module.__name__} {path}: the internal service was requested")

    def test_render_cross_site_iframe(self):
        self.check(render, "/oopif", ("--max-slices", "1"))

    def test_render_service_worker(self):
        self.check(render, "/swpage", ("--max-slices", "1"))

    def test_render_websocket(self):
        self.check(render, "/ws", ("--max-slices", "1"))

    def test_render_preconnect_and_prefetch(self):
        self.check(render, "/prefetch", ("--max-slices", "1"))

    def test_devtools_cross_site_iframe(self):
        self.check(devtools, "/oopif")

    def test_devtools_service_worker(self):
        self.check(devtools, "/swpage")

    def test_devtools_websocket(self):
        self.check(devtools, "/ws")

    def test_the_audited_site_itself_still_works_through_the_proxy(self):
        with tempfile.TemporaryDirectory() as tmp, pretend_public("127.0.0.1", "127.0.0.3"):
            code, out, err = run_main(render, [f"http://127.0.0.1:{self.site.port}/oopif", "--out", tmp, "--settle", "0.8", "--max-slices", "1"])
            self.assertEqual(code, 0, err)
            with open(os.path.join(tmp, "rendered-mobile.txt"), encoding="utf-8") as fh:
                self.assertIn("site", fh.read())
            with open(os.path.join(tmp, "rendered.json"), encoding="utf-8") as fh:
                self.assertGreater(json.load(fh)["guard_connections"], 0, "Chrome did not go through the filtering proxy")


# --------------------------------------------------------------------------------------------------------------
class RobotsRulesCannotBeUsedAgainstTheCrawler(unittest.TestCase):
    def allowed(self, body, url, status=200, token="SiteAuditSkill"):
        return robotsrules.Robots(status, body, token).allowed(url)

    def test_a_hostile_rule_with_many_stars_is_answered_at_once(self):
        rule = "/" + "*a" * 40 + "b"
        t = time.monotonic()
        self.assertTrue(self.allowed(f"User-agent: *\nDisallow: {rule}\n", "http://x/" + "a" * 600))
        # a rule longer than 500 characters is cut there: it then forbids at least what the whole rule would
        self.assertFalse(self.allowed(f"User-agent: *\nDisallow: /{'*' * 5000}x\n", "http://x/" + "a" * 3000))
        self.assertLess(time.monotonic() - t, 1.0)

    def test_the_rules_still_match_as_the_standard_says(self):
        body = "User-agent: *\nDisallow: /*.pdf$\nDisallow: /tmp*\nDisallow: /a*b*c\nAllow: /tmp/ok\n"
        self.assertFalse(self.allowed(body, "http://x/f.pdf"))
        self.assertTrue(self.allowed(body, "http://x/f.pdf?x=1"))
        self.assertFalse(self.allowed(body, "http://x/tmpfile"))
        self.assertTrue(self.allowed(body, "http://x/tmp/ok"))
        self.assertFalse(self.allowed(body, "http://x/a-1-b-2-c"))
        self.assertTrue(self.allowed(body, "http://x/a-1-c-2-b"))

    def test_on_a_tie_allow_wins_whatever_the_order(self):
        for order in ("Allow: /page\nDisallow: /page\n", "Disallow: /page\nAllow: /page\n"):
            self.assertTrue(self.allowed("User-agent: *\n" + order, "http://x/page"), order)

    def test_a_byte_order_mark_does_not_hide_the_file(self):
        self.assertFalse(self.allowed("\ufeffUser-agent: *\nDisallow: /private/\n", "http://x/private/a"))

    def test_the_product_token_of_a_user_agent_line_is_what_counts(self):
        body = "User-agent: SiteAuditSkill/1.0\nDisallow: /secret/\n\nUser-agent: *\nAllow: /\n"
        self.assertFalse(self.allowed(body, "http://x/secret/a"))

    def test_percent_encoding_is_compared_in_its_decoded_form(self):
        self.assertFalse(self.allowed("User-agent: *\nDisallow: /private/\n", "http://x/%70rivate/a"))

    def test_429_is_treated_like_a_server_error(self):
        self.assertFalse(self.allowed("", "http://x/", status=429))
        self.assertTrue(self.allowed("", "http://x/", status=404))


class TheCrawlerKeepsToRobotsAndToItsManners(unittest.TestCase):
    def serve(self, routes):
        srv = Recorder("127.0.0.1", 0, routes)
        self.addCleanup(srv.close)
        return srv

    def test_a_link_robots_forbids_is_never_requested_not_even_to_check_it(self):
        def routes(p):
            if p == "/robots.txt":
                return 200, "text/plain", "User-agent: *\nDisallow: /private/\n"
            if p in ("/", "/index.html"):
                return 200, "text/html", "<html><head><title>t</title></head><body><h1>t</h1><a href='/private/x'>x</a><a href='/private/y'>y</a><a href='/open'>o</a></body></html>"
            return 200, "text/html", "<html><head><title>o</title></head><body><h1>o</h1></body></html>"
        srv = self.serve(routes)
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_main(crawl, [f"http://127.0.0.1:{srv.port}/", "--out", tmp, "--max-pages", "5"])
            self.assertEqual(code, 0, err)
        self.assertEqual([p for p in srv.hits if p.startswith("/private")], [])

    def test_a_robots_file_that_answers_503_stops_everything_sitemap_included(self):
        def routes(p):
            return (503, "text/plain", "busy") if p == "/robots.txt" else (200, "text/html", "<html><body>x</body></html>")
        srv = self.serve(routes)
        with tempfile.TemporaryDirectory() as tmp:
            run_main(crawl, [f"http://127.0.0.1:{srv.port}/", "--out", tmp, "--max-pages", "3"])
        self.assertEqual([p for p in srv.hits if p != "/robots.txt"], [])

    def test_workers_and_delay_have_a_floor_and_a_ceiling(self):
        seen = {}
        orig = crawl.ThreadPoolExecutor

        def spy(max_workers=None, **kw):
            seen["workers"] = max(seen.get("workers", 0), max_workers or 0)
            return orig(max_workers=max_workers, **kw)
        srv = self.serve(lambda p: (404, "text/plain", "") if p == "/robots.txt" else (200, "text/html", "<html><head><title>t</title></head><body><h1>t</h1><a href='/a'>a</a></body></html>"))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(crawl, "ThreadPoolExecutor", spy):
            run_main(crawl, [f"http://127.0.0.1:{srv.port}/", "--out", tmp, "--max-pages", "3", "--workers", "50", "--delay", "0"])
        self.assertLessEqual(seen["workers"], crawl.MAX_WORKERS)

    def test_a_gzipped_sitemap_is_read(self):
        import gzip
        xml = "<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>http://127.0.0.1:{p}/gz-page</loc></url></urlset>"
        holder = {}

        def routes(p):
            if p == "/robots.txt":
                return 200, "text/plain", f"Sitemap: http://127.0.0.1:{holder['port']}/sitemap.xml.gz\n"
            if p == "/sitemap.xml.gz":
                return 200, "application/gzip", gzip.compress(xml.format(p=holder["port"]).encode())
            return 200, "text/html", "<html><head><title>t</title></head><body><h1>t</h1></body></html>"
        srv = self.serve(routes)
        holder["port"] = srv.port
        with tempfile.TemporaryDirectory() as tmp:
            run_main(crawl, [f"http://127.0.0.1:{srv.port}/", "--out", tmp, "--max-pages", "4"])
            with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as fh:
                summary = json.load(fh)
        self.assertIn("/gz-page", json.dumps(summary))


# --------------------------------------------------------------------------------------------------------------
class FactsReadWhatTheSiteSaysOnce(unittest.TestCase):
    def test_an_http_resource_is_counted_whatever_the_quoting_or_the_srcset_candidate(self):
        html = ("<img src=http://a.example/x.png><img srcset='https://a.example/1.png 1x, http://a.example/2.png 2x'>"
                "<a href='http://z.example/'>link</a><img src='https://ok.example/y.png'><script src=\"http://www.w3.org/x\"></script>")
        self.assertEqual(facts.mixed_content_count(html), 2)

    def test_the_robots_decision_of_the_audit_is_the_one_of_the_crawler(self):
        self.assertTrue(facts.robots_disallows_all("User-agent: *\nDisallow: /*\n"))
        self.assertFalse(facts.robots_disallows_all("User-agent: SiteAuditSkill\nAllow: /\n\nUser-agent: *\nDisallow: /\n"))
        self.assertFalse(facts.robots_disallows_all("User-agent: *\nDisallow: /\nAllow: /public\n"))

    def test_each_ai_robot_gets_its_own_answer(self):
        d = facts.ai_robot_decisions(200, "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
        self.assertFalse(d["GPTBot"]["allowed_on_root"])
        self.assertTrue(d["GPTBot"]["own_group"])
        self.assertTrue(d["ClaudeBot"]["allowed_on_root"])
        self.assertFalse(d["ClaudeBot"]["own_group"])
        self.assertTrue(all(v["allowed_on_root"] for v in facts.ai_robot_decisions(404, "").values()))
        self.assertFalse(any(v["allowed_on_root"] for v in facts.ai_robot_decisions(503, "").values()))
        for tok in ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "Perplexity-User", "Google-Extended", "Applebot-Extended"):
            self.assertIn(tok, d)

    def test_a_server_that_drips_one_byte_at_a_time_is_cut_at_the_deadline(self):
        def routes(p):
            return 200, "text/html", "x"

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", "100000")
                self.end_headers()
                try:
                    for _ in range(100000):
                        self.wfile.write(b"x")
                        self.wfile.flush()
                        time.sleep(0.3)
                except OSError:
                    pass

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        t = time.monotonic()
        r = facts.fetch(f"http://127.0.0.1:{srv.server_address[1]}/", "ua", timeout=3, allow_private=True)
        self.assertLess(time.monotonic() - t, 6.0)
        self.assertTrue(r["truncated"])


class ConsistencyReadsSentencesNotSevenWords(unittest.TestCase):
    def blocks(self, text):
        return [{"text": text, "heading": "", "row_label": None}]

    def test_a_price_in_a_long_paragraph_meets_the_same_price_stated_alone(self):
        home = "Nous accompagnons les artisans de la région depuis longtemps et nous proposons un diagnostic à 49 € TTC pour démarrer sans engagement, avec un expert dédié."
        prices = consistency.extract_prices("/", self.blocks(home)) + consistency.extract_prices("/tarifs", self.blocks("Diagnostic à 59 € TTC"))
        self.assertEqual(len(consistency.price_conflicts(prices)), 1)

    def test_a_delay_in_a_long_paragraph_meets_the_same_delay_stated_alone(self):
        long_ = "Nous sommes une équipe passionnée qui répond à toutes vos questions. Réponse sous 24 heures, du lundi au vendredi, par e-mail ou par téléphone."
        qs = consistency.extract_quantities("/", self.blocks(long_)) + consistency.extract_quantities("/contact", self.blocks("Réponse sous 48 heures."))
        self.assertEqual(len(consistency.quantity_conflicts(qs)), 1)

    def test_two_different_plans_are_still_not_a_conflict(self):
        prices = consistency.extract_prices("/", self.blocks("Formule Essentiel à 49 € TTC")) + consistency.extract_prices("/t", self.blocks("Formule Premium à 99 € TTC"))
        self.assertEqual(consistency.price_conflicts(prices), [])


# --------------------------------------------------------------------------------------------------------------
class RedactLeavesOrdinaryTextAlone(unittest.TestCase):
    def test_ordinary_sentences_and_notes_are_not_masked(self):
        for text in ("What does your site look like on mobile", "keyword: plombier paris", "Tests passed: 172", "Design tokens: colors",
                     "token_expiry: 3", "The salted caramel", "Number of keywords: 40"):
            self.assertEqual(redact.redact(text)[0], text, text)

    def test_real_secrets_are_still_masked(self):
        for text, secret in (("DB_PASSWORD=abc12345", "abc12345"), ("access_token: abc123def", "abc123def"), ("session_id=abc123xyz", "abc123xyz"),
                             ("admin:$y$j9T$abc$def", "j9T"), ("admin:{SHA}W6ph5Mm5Pz8GgiULbPgzG37mj9g=", "W6ph5"),
                             ("https://x.example/b?sig=abcdef%2Bghi&se=1", "abcdef"), ("abcD efgh ijkl mnop qr5t uvwx", "qr5t")):
            self.assertNotIn(secret, redact.redact(text)[0], text)

    def test_the_output_folder_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "internal", "sub", "x.txt")
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "redact.py"), "--out", target], input="DB_PASSWORD=hunter2hunter2", capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(target, encoding="utf-8") as fh:
                self.assertNotIn("hunter2", fh.read())


# --------------------------------------------------------------------------------------------------------------
FAKE_LH = """#!/bin/sh
OUT=""
for a in "$@"; do case "$a" in --output-path=*) OUT="${a#--output-path=}";; esac; done
if [ -n "$FAKE_LH_NULL" ]; then
cat > "$OUT" <<JSON
{"finalDisplayedUrl": "http://127.0.0.1:9/", "runtimeError": {"code": "NO_FCP"}, "categories": {"performance": {"score": null}}, "audits": {}}
JSON
else
cat > "$OUT" <<JSON
{"finalDisplayedUrl": "http://127.0.0.1:9/", "categories": {"performance": {"score": 0.9}}, "audits": {}}
JSON
fi
"""


class LighthouseThatCannotScoreIsNotAMedian(unittest.TestCase):
    def run_it(self, env_extra):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        path = os.path.join(tmp, "lighthouse")
        with open(path, "w") as fh:
            fh.write(FAKE_LH)
        os.chmod(path, 0o755)
        env = {"PATH": tmp + os.pathsep + os.environ.get("PATH", ""), **env_extra}
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "lh_median.py"), "http://127.0.0.1:9/", "--runs", "2", "--out", os.path.join(tmp, "lh")],
                           capture_output=True, text=True, timeout=60, env=env)
        return r, tmp

    def test_runs_without_a_performance_score_are_ignored_not_a_crash(self):
        r, tmp = self.run_it({"FAKE_LH_NULL": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("no run produced a performance score", r.stderr)

    def test_good_runs_are_counted_and_the_failed_ones_reported(self):
        r, tmp = self.run_it({})
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(tmp, "lh", "summary.json"), encoding="utf-8") as fh:
            s = json.load(fh)
        self.assertEqual(s["runs_failed"], 0)
        self.assertEqual(s["runs_ok"], 2)
        self.assertIn("guard_connections", s)


class PsiNeverSaysOkAfterAFailure(unittest.TestCase):
    def test_a_key_with_every_call_failing_is_failed_and_exits_4(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(psi, "http", lambda *a, **k: (500, {"error": {"message": "boom"}})), \
                mock.patch.dict(os.environ, {"PSI_TEST_KEY": "k"}):
            code, out, err = run_main(psi, ["https://example.org/", "--key-env", "PSI_TEST_KEY", "--out", tmp])
            with open(os.path.join(tmp, "psi.json"), encoding="utf-8") as fh:
                res = json.load(fh)
        self.assertEqual(code, 4)
        self.assertEqual(res["status"], "failed")


# --------------------------------------------------------------------------------------------------------------
class TheTrackerHoldsTheLine(unittest.TestCase):
    def setUp(self):
        from test_fix_tracker import Env, two_agent_actions
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        d = two_agent_actions()
        d["findings"][0]["execution"]["mode"] = "agent"
        self.e = Env(self.tmp, d)
        self.e.init()
        self.e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_ENV", "--note", "verified: GET /wp-json 200")
        self.e.run("provide", "--need", "consent_rules", "--note", "decided: nothing fires before consent")
        self.e.run("provide", "--need", "real_proof", "--note", "Customer quote with permission to publish it")

    def test_skipping_ahead_by_deferring_needs_the_owner_and_their_words(self):
        e = self.e
        self.assertEqual(e.run("defer", "--id", "F1", "--reason", "x").returncode, 2)                         # no --by
        self.assertEqual(e.run("defer", "--id", "F1", "--by", "Quelqu'un", "--reason", "he said to skip").returncode, 2)
        self.assertEqual(e.run("defer", "--id", "F1", "--by", "Alex", "--reason", "x").returncode, 2)          # no words
        self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex").returncode, 2)
        self.assertEqual(e.run("defer", "--id", "F1", "--by", "Alex", "--reason", "Alex: skip it, later").returncode, 0)
        self.assertIn("deferred by Alex", e.read("fix-log.md"))

    def test_one_go_at_a_time(self):
        e = self.e
        self.assertEqual(e.run("approve", "--id", "F1", "--by", "Alex").returncode, 0)
        r = e.run("approve", "--id", "F2", "--by", "Alex", "--out-of-order", "--reason", "Alex: both")
        self.assertEqual(r.returncode, 2)
        self.assertIn("One GO at a time", r.stderr)
        self.assertEqual(e.run("done", "--id", "F1", "--proof", "checked: 200 on the page").returncode, 0)
        self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex").returncode, 0)

    def test_the_owner_is_required_at_init_and_pseudo_names_are_refused(self):
        from test_fix_tracker import Env, two_agent_actions
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            base = [sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", e.findings, "--state", e.state]
            self.assertEqual(subprocess.run(base, capture_output=True, text=True).returncode, 2)
            for who in ("owner", "client", "GO", "yes", "admin", "root", "Fable ChatGPT"):
                self.assertEqual(subprocess.run(base + ["--owner", who], capture_output=True, text=True).returncode, 2, who)
            self.assertEqual(subprocess.run(base + ["--owner", "Alex"], capture_output=True, text=True).returncode, 0)

    def test_two_rebuilds_in_the_same_second_keep_both_backups(self):
        e = self.e
        for _ in range(3):
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", e.findings, "--state", e.state, "--owner", "Alex", "--force"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len([n for n in os.listdir(self.tmp) if n.startswith("fix-state.json.bak-")]), 3)

    def test_ordinary_notes_that_contain_a_word_like_a_secret_name_are_accepted(self):
        e = self.e
        for note in ("What does your site look like on mobile", "keyword: plombier paris", "Tests passed: 172"):
            r = e.run("provide", "--need", "real_proof", "--note", note)
            self.assertEqual(r.returncode, 0, note + " " + r.stderr)
        self.assertEqual(e.run("provide", "--need", "real_proof", "--note", "contact: jane.doe" + chr(64) + "example.test").returncode, 2)       # personal data stays out of the log


class TheReportKeepsItsPromises(unittest.TestCase):
    def example(self):
        with open(os.path.join(ROOT, "skills", "site-audit", "templates", "findings.example.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_core_domain_left_out_without_a_word_is_a_warning(self):
        d = self.example()
        d["not_measured"] = []
        errs, warns = build_report.validate(d)
        self.assertEqual(errs, [])
        self.assertTrue(any("left out without a word" in w for w in warns), warns)
        d["not_measured"] = ["ux: screens not viewed", "copy: not read", "ux and copy were not looked at"]
        errs, warns = build_report.validate(d)
        self.assertFalse(any("left out without a word" in w for w in warns), warns)

    def test_an_action_plan_with_ticked_boxes_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = os.path.join(tmp, "findings.json")
            with open(findings, "w", encoding="utf-8") as fh:
                json.dump(self.example(), fh)
            args = [sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), findings, "--out", os.path.join(tmp, "report.md")]
            self.assertEqual(subprocess.run(args, capture_output=True, text=True).returncode, 0)
            plan = os.path.join(tmp, "action-plan.md")
            with open(plan, encoding="utf-8") as fh:
                text = fh.read()
            with open(plan, "w", encoding="utf-8") as fh:
                fh.write(text.replace("### - [ ]", "### - [x]", 1))
            r = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn("ticked", r.stderr)
            with open(plan, encoding="utf-8") as fh:
                self.assertIn("### - [x]", fh.read())
            self.assertEqual(subprocess.run(args + ["--overwrite-plan"], capture_output=True, text=True).returncode, 0)

    def test_one_action_is_written_in_the_singular(self):
        d = self.example()
        text = build_report.render_plan(d, 80, build_report.compute(d)[4])
        self.assertNotIn("actions 1)", text)
        self.assertNotIn("(actions 1,", text)


class TheSkillCarriesItsLicence(unittest.TestCase):
    def test_the_licence_travels_with_the_skill_folder(self):
        path = os.path.join(ROOT, "skills", "site-audit", "LICENSE")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as a, open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as b:
            self.assertEqual(a.read(), b.read())


if __name__ == "__main__":
    unittest.main()
