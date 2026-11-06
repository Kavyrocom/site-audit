"""Regression cases for: a response head that never ends, a redirect to a path robots.txt forbids, one request clock for
all crawler workers, accented URLs, mixed content, the proxy relaying one request per connection, the Google data when
one call fails, contradictions the detector used to miss, and a refused `init --force` that used to lose the state.
"""
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_fix_tracker import Env, SCRIPTS, example  # noqa: E402
from test_guard_proxy_and_tracker import pretend_public  # noqa: E402
from test_psi import psi_body, run as psi_run  # noqa: E402

sys.path.insert(0, SCRIPTS)
import consistency  # noqa: E402
import crawl  # noqa: E402
import devtools  # noqa: E402
import facts  # noqa: E402
import netguard  # noqa: E402
import redact  # noqa: E402
import robotsrules  # noqa: E402
import safenet  # noqa: E402


def serve(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stop(srv):
    srv.shutdown()
    srv.server_close()


class AResponseThatNeverEndsIsCutOnTime(unittest.TestCase):
    def test_a_status_line_and_headers_sent_one_byte_at_a_time(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        done = threading.Event()

        def drip():
            while not done.is_set():
                try:
                    listener.settimeout(0.5)
                    c, _ = listener.accept()
                except OSError:
                    continue
                try:
                    c.recv(4096)
                    for ch in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 200:
                        if done.is_set():
                            break
                        c.sendall(bytes([ch]))
                        time.sleep(0.3)
                except OSError:
                    pass
                finally:
                    c.close()
        threading.Thread(target=drip, daemon=True).start()
        self.addCleanup(listener.close)
        self.addCleanup(done.set)
        t = time.monotonic()
        r = facts.fetch(f"http://127.0.0.1:{listener.getsockname()[1]}/", facts.DEFAULT_UA, timeout=2, allow_private=True)
        self.assertEqual(r["status"], 0)
        self.assertLess(time.monotonic() - t, 5, "the whole head must arrive within the timeout, not each byte")


class ARedirectCannotLeadWhereRobotsForbids(unittest.TestCase):
    def test_the_hop_check_stops_the_redirect_before_it_is_requested(self):
        hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == "/go":
                    self.send_response(302)
                    self.send_header("Location", "/forbidden/page")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"ok")

            def log_message(self, *a):
                pass
        srv = serve(H)
        self.addCleanup(stop, srv)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        r = facts.fetch(base + "/go", facts.DEFAULT_UA, allow_private=True, hop_check=lambda u: "robots forbids" if "/forbidden" in u else None)
        self.assertEqual(r["status"], 0)
        self.assertIn("robots forbids", r["error"])
        self.assertNotIn("/forbidden/page", hits)
        self.assertEqual(facts.fetch(base + "/go", facts.DEFAULT_UA, allow_private=True)["status"], 200)

    def test_the_crawler_exits_1_when_nothing_could_be_crawled(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = serve(H)
        self.addCleanup(stop, srv)
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "crawl.py"), f"http://127.0.0.1:{srv.server_address[1]}/", "--out", tmp],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("nothing was crawled", r.stderr)


class OneClockForAllWorkers(unittest.TestCase):
    def test_four_workers_never_fire_closer_than_the_gap(self):
        pacer = crawl.Pacer(0.15)
        stamps = []

        def worker():
            for _ in range(3):
                pacer.wait()
                stamps.append(time.monotonic())
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stamps.sort()
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertEqual(len(stamps), 12)
        self.assertGreaterEqual(min(gaps), 0.13)


class WhatTheFactsScriptReads(unittest.TestCase):
    def test_accents_and_spaces_in_a_url_are_percent_encoded(self):
        self.assertEqual(facts.to_uri("http://x.test/café/a b?x=é y"), "http://x.test/caf%C3%A9/a%20b?x=%C3%A9%20y")
        self.assertEqual(facts.to_uri("http://x.test/plain?a=1&b=2"), "http://x.test/plain?a=1&b=2")

    def test_mixed_content_counts_poster_css_and_spaced_attributes_not_data_src(self):
        html = ('<video poster="http://a.test/p.png"></video><div style="background:url(http://a.test/b.png)"></div>'
                '<style>@import "http://a.test/c.css";</style><img src = "http://a.test/z.png"><img data-src="http://a.test/lazy.png">')
        self.assertEqual(facts.mixed_content_count(html), 4)

    def test_a_robots_file_that_closes_only_the_home_page_does_not_close_the_site(self):
        self.assertFalse(facts.robots_disallows_all("User-agent: *\nDisallow: /$\n"))
        self.assertTrue(facts.robots_disallows_all("User-agent: *\nDisallow: /\n"))

    def test_robots_rules_read_raw_and_percent_encoded_paths_alike(self):
        r = robotsrules.Robots(200, "User-agent: *\nDisallow: /café\nDisallow: /caf%C3%A9-2\n", "SiteAuditSkill")
        for url in ("http://x/café", "http://x/caf%C3%A9", "http://x/café-2"):
            self.assertFalse(r.allowed(url), url)
        self.assertTrue(r.allowed("http://x/other"))


class TheProxyRelaysOneRequestPerConnection(unittest.TestCase):
    def test_a_second_request_on_the_same_connection_never_reaches_the_upstream(self):
        received = []
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        done = threading.Event()

        def upstream():
            try:
                listener.settimeout(5)
                c, _ = listener.accept()
            except OSError:
                return
            c.settimeout(1.5)
            try:
                received.append(c.recv(65536))
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok")
                while not done.is_set():
                    chunk = c.recv(65536)           # a server that keeps its side open and waits for more
                    if not chunk:
                        break
                    received.append(chunk)
            except OSError:
                pass
            finally:
                c.close()
        threading.Thread(target=upstream, daemon=True).start()
        self.addCleanup(listener.close)
        self.addCleanup(done.set)
        proxy = netguard.GuardProxy(allow_private=True)
        self.addCleanup(proxy.stop)
        port = listener.getsockname()[1]
        s = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)
        s.sendall(f"GET http://127.0.0.1:{port}/first HTTP/1.1\r\nHost: x\r\n\r\nGET http://127.0.0.2:{port}/second-for-internal HTTP/1.1\r\nHost: y\r\n\r\n".encode())
        s.settimeout(5)
        data = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        s.close()
        time.sleep(0.5)
        blob = b"".join(received)
        self.assertIn(b"/first", blob)
        self.assertNotIn(b"second-for-internal", blob)
        self.assertIn(b"connection: close", data.lower())
        self.assertNotIn(b"keep-alive", data.lower())


class GoogleDataWhenACallFails(unittest.TestCase):
    def server(self, mode):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                from urllib.parse import parse_qs, urlparse
                q = parse_qs(urlparse(self.path).query)
                if mode == "malformed":
                    body = b"<html>not json</html>"
                    code = 200
                elif q.get("strategy") == ["desktop"]:
                    body, code = json.dumps({"error": {"code": 429, "message": "quota"}}).encode(), 429
                else:
                    body, code = json.dumps(psi_body(q["url"][0])).encode(), 200
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = serve(H)
        self.addCleanup(stop, srv)
        return srv

    def test_an_answer_that_is_not_json_is_an_error_not_a_crash(self):
        r, j = psi_run(self.server("malformed"), "https://example.test/page")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn(j["status"], ("failed", "partial"))
        self.assertNotIn("Traceback", r.stderr)

    def test_one_strategy_answering_is_partial_not_no_key(self):
        r, j = psi_run(self.server("half"), "https://example.test/page", "--strategy", "both", key=None)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(j["status"], "partial")
        self.assertTrue(j["strategies"]["mobile"]["lab"])


class ContradictionsThatWereMissed(unittest.TestCase):
    def read(self, *pages):
        prices, qtys = [], []
        for url, html in pages:
            p = consistency.Blocks()
            p.feed(html)
            p.close()
            prices += consistency.extract_prices(url, p.blocks)
            qtys += consistency.extract_quantities(url, p.blocks)
        return consistency.price_conflicts(prices), consistency.quantity_conflicts(qtys)

    def test_a_label_before_a_colon_is_the_label_of_the_price(self):
        prices, _ = self.read(("a", "<p>Diagnostic : 49 €</p>"), ("b", "<p>Diagnostic : 59 €</p>"))
        self.assertEqual([c["amounts"] for c in prices], [[49.0, 59.0]])

    def test_hours_and_days_are_compared_in_one_unit(self):
        _, q = self.read(("a", "<p>Livraison sous 48 h</p>"), ("b", "<p>Livraison sous 5 jours</p>"))
        self.assertEqual(len(q), 1)
        _, q = self.read(("a", "<p>Livraison sous 48 h</p>"), ("b", "<p>Livraison sous 2 jours</p>"))
        self.assertEqual(q, [])

    def test_an_english_thousands_separator_is_not_a_decimal_point(self):
        prices, _ = self.read(("a", "<p>Plan Pro: $1,200 per year</p>"), ("b", "<p>Plan Pro: $1,200 per year</p>"))
        self.assertEqual(prices, [])
        prices, _ = self.read(("a", "<p>Plan Pro: $1,200 per year</p>"), ("b", "<p>Plan Pro: $1,400 per year</p>"))
        self.assertEqual([c["amounts"] for c in prices], [[1200.0, 1400.0]])

    def test_the_same_table_on_two_pages_is_not_a_conflict(self):
        table = "<table><tr><td>Basic</td><td>10 €</td></tr><tr><td>Pro</td><td>20 €</td></tr></table>"
        prices, _ = self.read(("a", table), ("b", table))
        self.assertEqual(prices, [])

    def test_bad_input_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "consistency.py"), "--out", tmp], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stderr)


class ARefusedForceInitKeepsTheState(unittest.TestCase):
    def test_the_state_is_untouched_when_the_owner_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, example())
            e.init("Alex")
            before = e.read("fix-state.json")
            r = e.run("init", "--findings", e.findings, "--force", "--owner", "agent")
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertEqual(e.read("fix-state.json"), before)
            self.assertEqual([n for n in os.listdir(tmp) if ".bak" in n], [])

    def test_names_that_look_like_a_person_or_not(self):
        import fix_tracker
        for name in ("The owner", "Le propriétaire", "C1aude", "ChatGPT4o", "assistant_ai", "Mr Robot", "user123", "A.I."):
            self.assertTrue(fix_tracker.NOT_A_PERSON.search(name), name)
        for name in ("Claude Moreau", "Patrick Blanchong", "Robert", "Marie-Claire"):
            self.assertFalse(fix_tracker.NOT_A_PERSON.search(name), name)

    def test_a_long_slug_is_not_a_token_but_a_mixed_string_is(self):
        import fix_tracker
        self.assertFalse(fix_tracker.TOKENISH.search("curl https://example.org/blog/very-long-article-slug-about-plumbing-and-more"))
        self.assertFalse(fix_tracker.TOKENISH.search("pas-de-jargon-technique-du-tout-merci"))
        self.assertTrue(fix_tracker.TOKENISH.search("xK9pQ2vLm8Zr4Tn7Wb3Yc6Hd1Fg5Js0A"))


class MoreSecretsAndPersonalDataMasked(unittest.TestCase):
    def test_each_form_the_last_review_found(self):
        cases = {
            "REDIS_URL=redis://:Pa55word@cache:6379/0": "Pa55word",
            "<password>abc123xyz</password>": "abc123xyz",
            '<add key="DB_PASSWORD" value="abc123xyz789" />': "abc123xyz789",
            "identifiants admin / Azerty123!": "Azerty123",
            "Call (415) 555-0132 now": "555-0132",
            '203.0.113.9 - alice [05/Nov/2026:07:46:12 +0100] "GET / HTTP/1.1" 200 5': "alice",
        }
        for text, leaked in cases.items():
            out = redact.redact(text)[0]
            self.assertNotIn(leaked, out, text)
            self.assertEqual(redact.redact(out)[0], out, "masking twice must change nothing")
        self.assertIn("- - [05/Nov", redact.redact('203.0.113.9 - - [05/Nov/2026:07:46:12 +0100] "GET / HTTP/1.1" 200 5')[0].replace("[IP] ", ""))

    def test_a_sentence_about_a_token_is_not_a_leak_but_a_value_is(self):
        for text in ("Token: absent du formulaire de contact", "Secret: aucun", "signature: missing in the header", "Key: the homepage is slow",
                     "Find Your Best Plan With Ease"):
            self.assertEqual(redact.sensitive_kinds(text), ([], []), text)
        for text in ("DB_PASSWORD = hunter2hunter2", "the password is Azerty123!", "password=correcthorsebatterystaple"):
            self.assertTrue(redact.sensitive_kinds(text)[0], text)


class FoldersAndButtons(unittest.TestCase):
    def test_only_a_folder_named_like_an_audit_gets_the_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, expected in (("site-audit-fork", False), ("site-audit-example.test-2026-11-06", True)):
                folder = os.path.join(tmp, name)
                os.makedirs(folder)
                safenet.private_output(os.path.join(folder, "report.md"))
                self.assertEqual(os.path.exists(os.path.join(folder, ".gitignore")), expected, name)

    def test_a_button_that_says_refuse_and_accept_is_not_the_refuse_button(self):
        for label in ("Tout refuser", "Refuser", "Reject all", "Refuser les cookies", "Tout refuser."):
            self.assertTrue(devtools.REFUSE.search(label), label)
        for label in ("Refuser et accepter", "Reject all and continue to pay", "Refuser tout sauf la newsletter"):
            self.assertFalse(devtools.REFUSE.search(label), label)


class APrivateStartIsNotDecidedByDns(unittest.TestCase):
    def test_a_hostile_name_that_resolves_to_a_private_address_keeps_the_guard_on(self):
        with mock.patch.object(safenet, "_resolve", lambda h: ["10.0.0.5"]), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(safenet.ALLOW_PRIVATE_ENV, None)
            self.assertFalse(safenet.starts_private("http://hostile.example/"))
            self.assertIsNotNone(safenet.check("http://hostile.example/", False))


if __name__ == "__main__":
    unittest.main()
