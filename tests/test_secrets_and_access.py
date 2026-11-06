"""Secrets never stored, a GO needs a person's name, an access is proven by a real check, credentials never follow
a redirect. Cases found by an independent review of the repository."""
import json
import os
from datetime import datetime, timedelta, timezone
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_fix_tracker import Env, SCRIPTS, two_agent_actions  # noqa: E402

sys.path.insert(0, SCRIPTS)
import access_check  # noqa: E402
import safenet  # noqa: E402


def utc_now(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def fake_token():
    """Assembled at run time: no whole realistic secret is stored in this repository."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def write_check(path, sealed=True, **fields):
    """A file like the one access_check.py --out writes (sealed), or one written by hand (not sealed)."""
    body = {"ok": True, "type": "wp", "detail": "authenticated as role(s) ['editor']", "capabilities": {}, "checked_at": utc_now()}
    body.update(fields)
    if sealed:
        safenet.seal(body)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    return path


def ready_env(tmp, owner="Alex"):
    e = Env(tmp, two_agent_actions())
    e.init(owner)
    e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_ENV", "--note", "verified: GET /wp-json 200")
    e.run("provide", "--need", "consent_rules", "--note", "decided: nothing fires before consent")
    return e


class NoSecretIsEverStored(unittest.TestCase):
    def assert_refused_and_absent(self, r, e, *secrets):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for name in ("fix-state.json", "fix-log.md"):
            p = os.path.join(e.tmp, name)
            if os.path.exists(p):
                for s in secrets:
                    self.assertNotIn(s, e.read(name), f"{s!r} found in {name}")

    def test_token_in_ref_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            tok = fake_token()
            r = e.run("provide", "--need", "tag_manager_access", "--ref", tok, "--note", "verified: GET /wp-json 200")
            self.assert_refused_and_absent(r, e, tok)

    def test_token_in_proof_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = ready_env(tmp)
            e.run("approve", "--id", "F1", "--by", "Alex")
            tok = fake_token()
            r = e.run("done", "--id", "F1", "--proof", f"verified using {tok} on the container")
            self.assert_refused_and_absent(r, e, tok)

    def test_password_written_in_a_sentence_is_refused_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            for cmd in (("provide", "--need", "consent_rules", "--note", "the GTM password is Hunter2Secret"),
                        ("handoff", "--id", "F1", "--note", "mot de passe : Hunter2Secret"),
                        ("defer", "--id", "F1", "--reason", "token = abc123def456ghi789"),
                        ("fail", "--id", "F1", "--reason", "password=Hunter2Secret")):
                r = e.run(*cmd)
                self.assert_refused_and_absent(r, e, "Hunter2Secret", "abc123def456ghi789")

    def test_an_ordinary_note_still_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            r = e.run("provide", "--need", "consent_rules", "--note", "Decided: analytics only after consent, ads never")
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_wall_of_output_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = ready_env(tmp)
            e.run("approve", "--id", "F1", "--by", "Alex")
            r = e.run("done", "--id", "F1", "--proof", "line of output " * 80)
            self.assertEqual(r.returncode, 2)


class AnAccessIsProvenNotClaimed(unittest.TestCase):
    def provide(self, note, ref="GTM_ENV"):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            return e.run("provide", "--need", "tag_manager_access", "--ref", ref, "--note", note)

    def test_words_that_contain_tested_do_not_count(self):
        for note in ("untested, not checked", "not tested yet", "verified but failed with 403", "checked: HTTP 401", "tested, timeout",
                     "verified: 200 (not really tested)", "vérifié : ok, mais erreur d'authentification", "checked ok, échec de connexion", "verified OK - password rejected"):
            self.assertEqual(self.provide(note).returncode, 2, note)

    def test_a_real_probe_sentence_counts(self):
        for note in ("verified: GET /wp-json 200", "tested the container export: ok", "checked, read call returned true"):
            self.assertEqual(self.provide(note).returncode, 0, note)

    def test_a_note_that_hides_a_password_without_a_sign_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            for note in ("mdp hunter2!", "pw = hunter2", "mdp hunter2! identifiants admin S3cretPw2024", "login admin S3cretPw2024"):
                self.assertEqual(e.run("provide", "--need", "consent_rules", "--note", note).returncode, 2, note)

    def test_the_json_of_a_successful_access_check_is_the_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            good = write_check(os.path.join(tmp, "good.json"))
            r = e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", good)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("access_check.py wp: ok", e.read("fix-state.json"))

    def test_a_hand_written_or_old_check_is_not_a_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            tries = {
                "hand_written.json": write_check(os.path.join(tmp, "hand_written.json"), sealed=False),
                "edited_after_the_seal.json": None,
                "no_time.json": write_check(os.path.join(tmp, "no_time.json"), checked_at=""),
                "old.json": write_check(os.path.join(tmp, "old.json"), checked_at=utc_now(60 * 24)),
                "future.json": write_check(os.path.join(tmp, "future.json"), checked_at=utc_now(-600)),
            }
            path = write_check(os.path.join(tmp, "edited_after_the_seal.json"), ok=False)
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["ok"] = True                                   # someone flips the result and keeps the old seal
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            tries["edited_after_the_seal.json"] = path
            for name, path in tries.items():
                r = e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", path)
                self.assertEqual(r.returncode, 2, name)
            self.assertIn("seal", e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", tries["hand_written.json"]).stderr)

    def test_a_failed_or_missing_check_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            bad = write_check(os.path.join(tmp, "bad.json"), ok=False, detail="credentials rejected (HTTP 401)")     # sealed and fresh, but it failed
            r = e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", bad)
            self.assertEqual(r.returncode, 2)
            self.assertIn("did not succeed", r.stderr)
            self.assertEqual(e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", os.path.join(tmp, "nope.json")).returncode, 2)

    def test_the_type_of_the_check_must_be_the_one_the_need_declares(self):
        d = two_agent_actions()
        for f in d["findings"]:
            for nd in f["execution"]["needs"]:
                if nd["id"] == "tag_manager_access":
                    nd["check_type"] = "ssh"
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, d)
            e.init()
            wrong = write_check(os.path.join(tmp, "files.json"), type="files")
            r = e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", wrong)
            self.assertEqual(r.returncode, 2)
            self.assertIn("'ssh' check", r.stderr)
            right = write_check(os.path.join(tmp, "ssh.json"), type="ssh")
            self.assertEqual(e.run("provide", "--need", "tag_manager_access", "--ref", "WP_ENV", "--check", right).returncode, 0)

    def test_a_ref_must_be_a_variable_that_exists_or_a_vault_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            for ref in ("hunter2", "NOT_SET_ANYWHERE_1"):
                r = e.run("provide", "--need", "tag_manager_access", "--ref", ref, "--note", "verified: GET /wp-json 200")
                self.assertEqual(r.returncode, 2, ref)
                self.assertIn("not a variable of this environment", r.stderr)
            self.assertEqual(e.run("provide", "--need", "tag_manager_access", "--ref", "vault:site/login", "--note", "verified: GET /wp-json 200").returncode, 0)


class AGoComesFromAPerson(unittest.TestCase):
    def test_agent_like_names_are_refused_and_people_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = ready_env(tmp, owner="Claude Moreau")
            for who in ("agent", "Claude Code", "claude", "Hermes agent", "the assistant", "me", "GPT-5 bot", "codex", "Claude Opus", "Claude Sonnet 4.5",
                        "ChatGPT", "Sonnet", "Opus", "Mistral", "Le Chat", "the user", "l'utilisateur", "utilisateur", "Gemini"):
                self.assertEqual(e.run("approve", "--id", "F1", "--by", who).returncode, 2, who)
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "Claude Moreau").returncode, 0)

    def test_an_owner_declared_at_init_is_the_only_name_that_can_approve(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", e.findings, "--state", e.state, "--owner", "Alex"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_ENV", "--note", "verified: GET /wp-json 200")
            e.run("provide", "--need", "consent_rules", "--note", "decided: nothing fires before consent")
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "Quelqu'un d'autre").returncode, 2)
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "Claude").returncode, 2)
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "alex").returncode, 0)
            bad = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", e.findings, "--state", e.state + "2", "--owner", "ChatGPT"],
                                 capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)

    def test_init_force_keeps_a_backup_and_leaves_a_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = ready_env(tmp)
            e.run("approve", "--id", "F1", "--by", "Alex")
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", e.findings, "--state", e.state, "--owner", "Alex", "--force"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            backups = [n for n in os.listdir(tmp) if n.startswith("fix-state.json.bak-")]
            self.assertEqual(len(backups), 1)
            self.assertIn("approved: 1", e.read("fix-log.md"))
            with open(os.path.join(tmp, backups[0]), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["actions"][0]["approved_by"], "Alex")


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.seen.append((self.server.server_port, self.path, bool(self.headers.get("Authorization"))))
        port2 = self.server.other_port
        if self.path.startswith("/wp-json/wp/v2/users/me") and self.server.redirect_authed:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.2:{port2}/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/wp-json/" and self.server.redirect_first:
            self.send_response(301)
            self.send_header("Location", f"http://127.0.0.2:{port2}/wp-json/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({"name": "t", "namespaces": ["wp/v2"], "roles": ["editor"], "capabilities": {"edit_pages": True}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CredentialsNeverFollowARedirect(unittest.TestCase):
    def start(self, redirect_authed=False, redirect_first=False):
        Handler.seen = []
        other = ThreadingHTTPServer(("127.0.0.2", 0), Handler)
        main = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        for srv in (main, other):
            srv.other_port = other.server_port
            srv.redirect_authed, srv.redirect_first = redirect_authed, redirect_first
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.addCleanup(srv.shutdown)
            self.addCleanup(srv.server_close)
        return main.server_port, other.server_port

    def check(self, port):
        env = dict(os.environ, SA_TEST_USER="bot", SA_TEST_PW="not-a-real-password-1")
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "access_check.py"), "wp", "--url", f"http://127.0.0.1:{port}",
                            "--user-env", "SA_TEST_USER", "--pass-env", "SA_TEST_PW"], capture_output=True, text=True, env=env, timeout=60)
        return r, json.loads(r.stdout)

    def test_a_redirect_on_the_authenticated_call_never_carries_the_password(self):
        main, other = self.start(redirect_authed=True)
        r, j = self.check(main)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(j["ok"])
        self.assertIn("redirect", j["detail"])
        self.assertEqual([s for s in Handler.seen if s[0] == other], [], "the other host must not be contacted at all")

    def test_a_redirect_on_the_first_call_is_reported_with_its_destination(self):
        main, other = self.start(redirect_first=True)
        r, j = self.check(main)
        self.assertEqual(r.returncode, 2)
        self.assertIn("127.0.0.2", j["detail"])
        self.assertEqual([s for s in Handler.seen if s[0] == other], [])

    def test_without_a_redirect_it_works_and_out_writes_the_json(self):
        main, _ = self.start()
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "check.json")
            env = dict(os.environ, SA_TEST_USER="bot", SA_TEST_PW="not-a-real-password-1")
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "access_check.py"), "wp", "--url", f"http://127.0.0.1:{main}",
                                "--user-env", "SA_TEST_USER", "--pass-env", "SA_TEST_PW", "--out", target], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            with open(target, encoding="utf-8") as fh:
                self.assertTrue(json.load(fh)["ok"])
            self.assertNotIn("not-a-real-password-1", r.stdout + r.stderr)


class FtpsChecksTheCertificate(unittest.TestCase):
    def test_tls_context_verifies_certificate_and_name(self):
        captured = {}

        class Stop(Exception):
            pass

        def fake(*args, **kwargs):
            captured.update(kwargs)
            raise ssl.SSLError("stop here")

        args = mock.Mock(host="ftp.example.com", user_env="SA_FTP_U", pass_env="SA_FTP_P", port=21, tls=True)
        with mock.patch.dict(os.environ, {"SA_FTP_U": "u", "SA_FTP_P": "p"}), mock.patch("ftplib.FTP_TLS", fake), mock.patch("builtins.print"):
            code = access_check.check_ftp(args)
        ctx = captured["context"]
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(code, 2)


class SshArgumentsAreValidated(unittest.TestCase):
    def test_option_looking_host_and_user_never_reach_ssh(self):
        for host, user in (("-oProxyCommand=touch /tmp/x", "root"), ("host;rm", "root"), ("ok.example", "-oProxyCommand=x"), ("ok.example", "a b")):
            with mock.patch("subprocess.run") as run, mock.patch("builtins.print"):
                a = mock.Mock(host=host, user=user, webroot=None, key=None, known_hosts=None, port=22)
                self.assertEqual(access_check.check_ssh(a), 2, (host, user))
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
