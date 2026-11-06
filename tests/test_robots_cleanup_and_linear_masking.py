"""Cases that used to pass unnoticed: the crawler following a redirect into an area robots.txt closes, the browser tools leaving a
detached Chrome behind or ignoring a short TMPDIR, the proxy holding a framed response open, masking rules that take
quadratic time on hostile text, over-masking of ordinary sentences, and a few names, units and answers that were wrong.
"""
import http.server
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_fix_tracker import SCRIPTS  # noqa: E402
from test_psi import run as psi_run  # noqa: E402

sys.path.insert(0, SCRIPTS)
import consistency  # noqa: E402
import fix_tracker  # noqa: E402
import netguard  # noqa: E402
import redact  # noqa: E402
import safenet  # noqa: E402


def serve(handler_cls):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stop(srv):
    srv.shutdown()
    srv.server_close()


class TheCrawlerNeverEntersAForbiddenAreaThroughARedirect(unittest.TestCase):
    def test_no_request_reaches_the_forbidden_path_and_the_link_is_not_called_broken(self):
        hits = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.do_GET()

            def do_GET(self):
                hits.append((self.command, self.path))
                if self.path == "/robots.txt":
                    body, ctype, code = b"User-agent: *\nDisallow: /private\n", "text/plain", 200
                elif self.path == "/":
                    body = b'<html><head><title>Home page of the test site</title></head><body><h1>Home</h1><a href="/go-private">Offer</a></body></html>'
                    ctype, code = "text/html", 200
                elif self.path == "/go-private":
                    self.send_response(302)
                    self.send_header("Location", "/private/offer")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                else:
                    body, ctype, code = b"secret", "text/html", 200
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = serve(H)
        self.addCleanup(stop, srv)
        def crawl(*extra):
            hits.clear()
            with tempfile.TemporaryDirectory() as tmp:
                r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "crawl.py"), f"http://127.0.0.1:{srv.server_address[1]}/", "--out", tmp,
                                    "--delay", "0", "--workers", "2", *extra], capture_output=True, text=True, timeout=90)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(os.path.join(tmp, "summary.json"), encoding="utf-8") as fh:
                    return json.load(fh)["issues"]
        issues = crawl("--max-pages", "1")                    # the link is only checked, not crawled
        self.assertEqual([h for h in hits if h[1].startswith("/private")], [], "robots.txt closes this area, even to a redirect")
        self.assertEqual([h for h in hits if h[1] == "/go-private"], [("HEAD", "/go-private")], "one check, no GET fallback")
        self.assertEqual(issues["broken_internal_links_not_crawled"], [])
        self.assertTrue(any("/go-private" in u for u in issues["links_redirecting_to_forbidden_areas"]))
        issues = crawl()                                      # the link is crawled as a page
        self.assertEqual([h for h in hits if h[1].startswith("/private")], [])
        self.assertEqual(issues["error_pages"], [])
        self.assertTrue(any("/go-private" in u for u in issues["links_redirecting_to_forbidden_areas"]))


FAKE_LIGHTHOUSE = """#!/bin/sh
# hangs the way a real Lighthouse does: a Chrome in a session of its own, with a profile folder under TMPDIR
OUT=""
for a in "$@"; do case "$a" in --output-path=*) OUT="${a#--output-path=}";; esac; done
echo "$TMPDIR" > "$FAKE_LH_HANG.tmpdir"
setsid "$FAKE_PY" -c "import time; time.sleep(300)" "$TMPDIR/lighthouse.profile" >/dev/null 2>&1 </dev/null &
echo $! > "$FAKE_LH_HANG"
wait
"""


class ADetachedChromeAndALongTmpdir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        path = os.path.join(self.tmp, "lighthouse")
        with open(path, "w") as fh:
            fh.write(FAKE_LIGHTHOUSE)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)

    def run_it(self, tmpdir):
        pidfile = os.path.join(self.tmp, "child.pid")
        env = {"PATH": self.tmp + os.pathsep + os.environ.get("PATH", ""), "FAKE_LH_HANG": pidfile, "TMPDIR": tmpdir, "FAKE_PY": sys.executable}
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "lh_median.py"), "http://127.0.0.1:9/", "--runs", "1", "--timeout", "2",
                            "--out", os.path.join(self.tmp, "lh")], capture_output=True, text=True, timeout=90, env=env)
        return r, pidfile

    @unittest.skipUnless(__import__("shutil").which("setsid"), "setsid not installed")
    def test_a_chrome_in_its_own_session_is_stopped_with_the_timeout(self):
        r, pidfile = self.run_it(self.tmp)
        self.assertIn("timeout", r.stderr)
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
        self.assertFalse(alive, "the killing of the tool's own group does not reach a Chrome that started its own session")

    @unittest.skipUnless(__import__("shutil").which("setsid"), "setsid not installed")
    def test_the_tool_gets_a_short_tmpdir_when_the_usual_one_is_long(self):
        long_dir = os.path.join(self.tmp, "d" * 60, "e" * 60)
        os.makedirs(long_dir)
        r, pidfile = self.run_it(long_dir)
        with open(pidfile + ".tmpdir") as fh:
            seen = fh.read().strip()
        try:
            with open(pidfile) as fh:
                os.kill(int(fh.read().strip()), 9)
        except (OSError, ValueError):
            pass
        self.assertLessEqual(len(seen), 40, f"Chrome fails on a socket path longer than about 100 characters: {seen}")
        self.assertNotEqual(seen, long_dir)


class TheProxyDoesNotHoldAFramedResponseOpen(unittest.TestCase):
    def talk(self, request, upstream_reply):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)
        done = threading.Event()

        def upstream():
            try:
                listener.settimeout(5)
                c, _ = listener.accept()
                c.recv(65536)
                c.sendall(upstream_reply)
                done.wait(20)                       # keeps its side open, as a keep-alive server does
                c.close()
            except OSError:
                pass
        threading.Thread(target=upstream, daemon=True).start()
        self.addCleanup(listener.close)
        self.addCleanup(done.set)
        proxy = netguard.GuardProxy(allow_private=True)
        self.addCleanup(proxy.stop)
        s = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)
        s.sendall(request.format(port=listener.getsockname()[1]).encode())
        s.settimeout(8)
        t0, data = time.monotonic(), b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        s.close()
        return time.monotonic() - t0, data

    def test_the_client_is_released_once_the_announced_length_has_been_sent(self):
        took, data = self.talk("GET http://127.0.0.1:{port}/a HTTP/1.1\r\nHost: x\r\n\r\n", b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok")
        self.assertTrue(data.endswith(b"ok"), data)
        self.assertLess(took, 5, "the response was complete: nothing more to wait for")

    def test_a_head_answer_has_no_body_to_wait_for(self):
        took, data = self.talk("HEAD http://127.0.0.1:{port}/a HTTP/1.1\r\nHost: x\r\n\r\n", b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\n\r\n")
        self.assertIn(b"200 OK", data)
        self.assertLess(took, 5)


class MaskingStaysFastOnHostileText(unittest.TestCase):
    UNITS = ["a-", "a.", "pass-", "key-", "1.2.3.", "http://a:", "u:$1$", "\n", "x\n", "user_login\n", "Cookie:\n", "password=", "12 rue a ", "<password>", "-u ", "a@b."]

    def test_every_rule_is_linear_enough_on_80_kb_of_one_repeated_pattern(self):
        code = "import sys; sys.path.insert(0, sys.argv[2]); import redact; redact.redact(sys.argv[1] * (80000 // len(sys.argv[1])))"
        for unit in self.UNITS:
            t0 = time.monotonic()
            try:
                subprocess.run([sys.executable, "-I", "-c", code, unit, SCRIPTS], timeout=20, capture_output=True, check=True)
            except subprocess.TimeoutExpired:
                self.fail(f"{unit!r} x {80000 // len(unit)} took more than 20 s: a rule goes quadratic")
            self.assertLess(time.monotonic() - t0, 8, f"{unit!r}: too slow")


class OrdinarySentencesAreNotMasked(unittest.TestCase):
    def test_a_sentence_that_mentions_a_user_table_does_not_erase_the_lines_after_it(self):
        text = "Le tableau user_login liste les comptes.\nLa page d'accueil charge 3 Mo.\nLe score mobile est de 41."
        self.assertEqual(redact.redact(text)[0], text)
        self.assertEqual(redact.sensitive_kinds(text), ([], []))

    def test_a_real_user_table_is_still_masked(self):
        out = redact.redact("ID,user_login,display_name\n1,alice,Alice Martin\n")[0]
        self.assertNotIn("alice", out)
        self.assertNotIn("Martin", out)

    def test_words_that_look_like_a_street_but_name_none_are_left_alone(self):
        for text in ("Étape 3 avenue : le plan prévoit 2 chemin de fer.", "Le site a 4 cours et 3 passage piétons"):
            self.assertEqual(redact.redact(text)[0], text)
        street = "12 rue " + "de la Paix"                  # built here so that no address stands in the file itself
        self.assertNotIn("Paix", redact.redact(street + ", 75002 Paris")[0])
        self.assertNotIn("Paix", redact.redact("Livraison " + street + " ce matin")[0])
        self.assertEqual(redact.redact("Il y a 2 chemin de fer ici")[0], "Il y a 2 chemin de fer ici")      # an article, but no name after it
        self.assertNotIn("Victor", redact.redact("7 bis avenue " + "Victor Hugo")[0])
        self.assertNotIn("Dupont", redact.redact("5 avenue " + "Dupont a ouvert hier")[0])


class SmallerCorrections(unittest.TestCase):
    def test_a_year_is_twelve_months(self):
        def promise(url, text):
            p = consistency.Blocks()
            p.feed(f"<p>{text}</p>")
            p.close()
            return consistency.extract_quantities(url, p.blocks)
        self.assertEqual(consistency.quantity_conflicts(promise("a", "Garantie 2 ans") + promise("b", "Garantie 24 mois")), [])
        self.assertTrue(consistency.quantity_conflicts(promise("a", "Garantie 2 ans") + promise("b", "Garantie 36 mois")))

    def test_a_dot_localhost_name_means_this_machine_whatever_the_resolver_says(self):
        with mock.patch.object(safenet, "_resolve", lambda h: ["10.0.0.5"]):
            self.assertFalse(safenet.set_audit_start("http://evil.localhost/"))
            self.assertEqual(safenet._AUDIT["start_addrs"], set())
        with mock.patch.object(safenet, "_resolve", lambda h: ["127.0.0.1", "93.184.216.34"]):
            self.assertTrue(safenet.set_audit_start("http://evil2.localhost/"))
            self.assertEqual(safenet._AUDIT["start_addrs"], {"127.0.0.1"})
        safenet._AUDIT.update(allow_private=None, start_addrs=set())

    def test_real_names_that_contain_a_model_name_are_accepted_but_the_models_are_not(self):
        for name in ("Jean Mistral", "Kimi Leroy", "Lucie Hermes", "Gemini Duval", "Claude Moreau", "Rob Otto", "Ai Nakamura"):
            self.assertFalse(fix_tracker.NOT_A_PERSON.search(name), name)
        for name in ("Gemini", "Gemini Pro", "Hermes Agent", "Kimi", "Mistral Large", "Claude Code", "ChatGPT 5", "Paul Agent"):
            self.assertTrue(fix_tracker.NOT_A_PERSON.search(name), name)

    def test_a_psi_answer_that_is_json_but_not_an_object_is_an_error_not_a_crash(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"[]")

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.do_GET()

            def log_message(self, *a):
                pass
        srv = serve(H)
        self.addCleanup(stop, srv)
        r, j = psi_run(srv, "https://example.test/page")
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(j["status"], ("failed", "partial"))


if __name__ == "__main__":
    unittest.main()
