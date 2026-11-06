"""access_check.py (read-only access tests, secrets by variable name) and lh_site.py (settings guard), without real services."""
import base64
import getpass
import http.server
import json
import os
import pathlib
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "skills", "site-audit", "scripts")
USER, PW = "audit-bot", "abcd efgh ijkl mnop"


def run(script, *args, env=None):
    e = {"PATH": os.environ.get("PATH", "")}
    e.update(env or {})
    return subprocess.run([sys.executable, "-I", os.path.join(S, script), *args], capture_output=True, text=True, timeout=90, env=e)


class WpServer:
    def __init__(self, caps=None, auth=True):
        outer = self
        self.seen_auth = []
        self.writes = []
        self.caps = caps if caps is not None else {"edit_pages": True, "edit_published_pages": True, "activate_plugins": True, "manage_options": False}
        want = "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()

        class H(http.server.BaseHTTPRequestHandler):
            def _j(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                p = self.path.split("?")[0]
                outer.seen_auth.append(self.headers.get("Authorization"))
                if p == "/wp-json/":
                    return self._j(200, {"name": "Fixture WP", "namespaces": ["wp/v2"]})
                if self.headers.get("Authorization") != want:
                    return self._j(401, {"code": "rest_not_logged_in"})
                if p == "/wp-json/wp/v2/users/me":
                    return self._j(200, {"roles": ["administrator"], "capabilities": outer.caps})
                if p == "/wp-json/wp/v2/plugins":
                    return self._j(200, [{"status": "active"}, {"status": "active"}, {"status": "inactive"}])
                self._j(404, {})

            def do_POST(self):
                outer.writes.append(self.path)
                self._j(500, {})
            do_PUT = do_DELETE = do_PATCH = do_POST

            def log_message(self, *a):
                pass
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class AccessTests(unittest.TestCase):
    def test_wp_ok_reads_only_and_never_prints_the_password(self):
        w = WpServer()
        try:
            r = run("access_check.py", "wp", "--url", w.url, "--user-env", "U", "--pass-env", "P", env={"U": USER, "P": PW})
        finally:
            w.close()
        j = json.loads(r.stdout)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(j["ok"])
        self.assertTrue(j["capabilities"]["can_manage_plugins"])
        self.assertEqual(j["capabilities"]["plugins_active"], 2)
        self.assertEqual(w.writes, [])
        self.assertNotIn(PW, r.stdout + r.stderr)

    def test_wp_missing_variable_says_what_to_ask(self):
        r = run("access_check.py", "wp", "--url", "https://example.invalid", "--user-env", "NOPE_U", "--pass-env", "NOPE_P")
        j = json.loads(r.stdout)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(j["ok"])
        self.assertIn("application password", j["next_step"])
        self.assertIn("Never paste", j["next_step"])

    def test_wp_wrong_password_is_401_with_next_step(self):
        w = WpServer()
        try:
            r = run("access_check.py", "wp", "--url", w.url, "--user-env", "U", "--pass-env", "P", env={"U": USER, "P": "wrong"})
        finally:
            w.close()
        j = json.loads(r.stdout)
        self.assertEqual(r.returncode, 2)
        self.assertIn("401", j["detail"])
        self.assertIn("application password", j["next_step"])

    def test_wp_refuses_a_password_over_plain_http_on_a_real_host(self):
        r = run("access_check.py", "wp", "--url", "http://example.com", "--user-env", "U", "--pass-env", "P", env={"U": USER, "P": PW})
        j = json.loads(r.stdout)
        self.assertEqual(r.returncode, 2)
        self.assertIn("plain http", j["detail"])
        self.assertNotIn(PW, r.stdout + r.stderr)

    def test_files_reports_capabilities(self):
        with tempfile.TemporaryDirectory() as t:
            pathlib.Path(t, "index.html").write_text("<h1>x</h1>")
            os.mkdir(os.path.join(t, ".git"))
            r = run("access_check.py", "files", "--path", t)
            j = json.loads(r.stdout)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(j["capabilities"]["static_html"])
            self.assertTrue(j["capabilities"]["git"])
            self.assertFalse(j["capabilities"]["wordpress"])
        r = run("access_check.py", "files", "--path", "/nonexistent/path")
        self.assertEqual(r.returncode, 2)

    def test_ssh_rejects_injection_in_host_user_and_path(self):
        for args in (("--host", "a;rm -rf /", "--user", "u"), ("--host", "h", "--user", "u;id"), ("--host", "h", "--user", "u", "--webroot", "/var/www; reboot")):
            r = run("access_check.py", "ssh", *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("invalid", json.loads(r.stdout)["detail"])

    def test_ssh_unreachable_gives_a_next_step(self):
        r = run("access_check.py", "ssh", "--host", "127.0.0.1", "--user", "nobody-here", "--port", "1")
        j = json.loads(r.stdout)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(j["ok"])
        self.assertTrue(j["next_step"])

    def test_ftp_refuses_plain_ftp_to_a_real_host(self):
        r = run("access_check.py", "ftp", "--host", "ftp.example.com", "--user-env", "U", "--pass-env", "P", env={"U": USER, "P": PW})
        j = json.loads(r.stdout)
        self.assertEqual(r.returncode, 2)
        self.assertIn("plain FTP", j["detail"])


SSHD = shutil.which("sshd") or ("/usr/sbin/sshd" if os.path.exists("/usr/sbin/sshd") else None)


@unittest.skipUnless(SSHD and shutil.which("ssh") and shutil.which("ssh-keygen"), "sshd/ssh not installed")
class SshAgainstARealServerTests(unittest.TestCase):
    """A throwaway sshd on a high port: the success path, a wrong key, and an unconfirmed host key."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sa-ssh-")
        t = cls.tmp
        for n in ("hostkey", "clientkey", "otherkey"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", os.path.join(t, n)], check=True)
        shutil.copy(os.path.join(t, "clientkey.pub"), os.path.join(t, "authorized_keys"))
        os.chmod(os.path.join(t, "authorized_keys"), 0o600)
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        with open(os.path.join(t, "sshd_config"), "w") as fh:
            fh.write(f"Port {cls.port}\nListenAddress 127.0.0.1\nHostKey {t}/hostkey\nAuthorizedKeysFile {t}/authorized_keys\nPasswordAuthentication no\n"
                     f"PubkeyAuthentication yes\nUsePAM {'yes' if os.geteuid() == 0 else 'no'}\nPidFile {t}/sshd.pid\nStrictModes no\n")
        with open(os.path.join(t, "known_hosts"), "w") as fh:
            fh.write(f"[127.0.0.1]:{cls.port} " + " ".join(pathlib.Path(t, "hostkey.pub").read_text().split()[:2]) + "\n")
        open(os.path.join(t, "empty_known"), "w").close()
        cls.proc = subprocess.Popen([SSHD, "-D", "-f", os.path.join(t, "sshd_config"), "-E", os.path.join(t, "sshd.log")])
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.user = getpass.getuser()

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ssh(self, key, known):
        r = run("access_check.py", "ssh", "--host", "127.0.0.1", "--user", self.user, "--port", str(self.port), "--key", os.path.join(self.tmp, key),
                "--known-hosts", os.path.join(self.tmp, known), "--webroot", self.tmp)
        return r, json.loads(r.stdout)

    def test_good_key_reads_and_reports_capabilities(self):
        r, j = self.ssh("clientkey", "known_hosts")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(j["ok"])
        self.assertEqual(j["capabilities"]["whoami"], self.user)
        self.assertTrue(j["capabilities"]["webroot_readable"])

    def test_wrong_key_says_what_to_ask(self):
        r, j = self.ssh("otherkey", "known_hosts")
        self.assertEqual(r.returncode, 2)
        self.assertIn("permission denied", j["detail"])
        self.assertIn("public key", j["next_step"])

    def test_unconfirmed_host_key_is_never_accepted_blindly(self):
        r, j = self.ssh("clientkey", "empty_known")
        self.assertEqual(r.returncode, 2)
        self.assertIn("host key not known", j["detail"])
        self.assertIn("Do not accept it blindly", j["next_step"])


def stub_unlighthouse(tmp, cpu):
    """A fake unlighthouse-ci that writes the files the real one writes, with the CPU slowdown we choose."""
    path = os.path.join(tmp, "bin")
    os.makedirs(path)
    script = f'''#!{sys.executable}
import json, os, sys
out = sys.argv[sys.argv.index("--output-path") + 1]
os.makedirs(os.path.join(out, "reports", "start"), exist_ok=True)
routes = [{{"path": "/", "score": 0.9, "categories": {{"performance": {{"score": 0.99}}, "seo": {{"score": 1}}}}, "metrics": {{"largest-contentful-paint": {{"numericValue": 900}}, "total-blocking-time": {{"numericValue": 26}}, "cumulative-layout-shift": {{"numericValue": 0}}}}}},
          {{"path": "/start/", "score": 0.7, "categories": {{"performance": {{"score": 0.6}}, "seo": {{"score": 0.9}}}}, "metrics": {{"largest-contentful-paint": {{"numericValue": 3000}}, "total-blocking-time": {{"numericValue": 700}}, "cumulative-layout-shift": {{"numericValue": 0.12}}}}}}]
json.dump({{"summary": {{}}, "routes": routes, "metadata": {{}}}}, open(os.path.join(out, "ci-result.json"), "w"))
for d in ("reports", os.path.join("reports", "start")):
    json.dump({{"configSettings": {{"formFactor": "mobile", "throttlingMethod": "simulate", "throttling": {{"cpuSlowdownMultiplier": {cpu}}}}}}}, open(os.path.join(out, d, "lighthouse.json"), "w"))
'''
    exe = os.path.join(path, "unlighthouse-ci")
    with open(exe, "w") as fh:
        fh.write(script)
    os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
    return path


class LhSiteTests(unittest.TestCase):
    def go(self, cpu):
        with tempfile.TemporaryDirectory() as t:
            binp = stub_unlighthouse(t, cpu)
            out = os.path.join(t, "o")
            r = run("lh_site.py", "--site", "https://example.test", "--paths", "/,/start/", "--out", out, env={"PATH": binp + os.pathsep + os.environ.get("PATH", "")})
            with open(os.path.join(out, "lh-site.json"), encoding="utf-8") as fh:
                return r, json.load(fh), pathlib.Path(out, "unlighthouse.config.mjs").read_text()

    def test_comparable_when_the_cpu_slowdown_is_applied(self):
        r, j, cfg = self.go(4)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(j["comparable"])
        self.assertEqual([p["path"] for p in j["pages"]], ["/start/", "/"])        # worst first
        self.assertEqual(j["pages"][0]["tbt_ms"], 700)
        self.assertIn("cpuSlowdownMultiplier: 4", cfg)                               # the config we write restores the slowdown
        self.assertIn("maxConcurrency: 1", cfg)

    def test_refuses_to_call_it_comparable_when_the_slowdown_is_missing(self):
        r, j, _ = self.go(1)
        self.assertEqual(r.returncode, 4)
        self.assertFalse(j["comparable"])
        self.assertIn("do not quote", j["note"])

    def test_missing_tool_is_explained(self):
        r = run("lh_site.py", "--site", "https://example.test", "--paths", "/", "--out", tempfile.mkdtemp(), env={"PATH": "/nonexistent"})
        self.assertEqual(r.returncode, 3)
        self.assertIn("npm install -g unlighthouse", r.stderr)


if __name__ == "__main__":
    unittest.main()
