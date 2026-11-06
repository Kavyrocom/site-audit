"""Tests for data leaving through the evidence files and the reports.

Every secret-looking value below is assembled at run time: the repository itself must never contain a string that
has the exact format of a real key (GitHub's secret scanning would flag the public repository).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
EXAMPLE = os.path.join(ROOT, "skills", "site-audit", "templates", "findings.example.json")
sys.path.insert(0, SCRIPTS)
import build_report as br  # noqa: E402
import redact  # noqa: E402


# reserved fictional telephone numbers (the 01 99 00 xx xx range), built here so no tool rewrites them
PHONE_A = "01 99 " + "00 00 02"
PHONE_B = "+33 1 99 " + "00 00 03"


def red(text):
    return redact.redact(text)[0]


class PersonalDataIsMasked(unittest.TestCase):
    def test_email_ip_phone_become_tokens(self):
        out = red("contact jane.doe@client.test from 203.0.113.42 or 2001:db8::7a, call " + PHONE_A + " / " + PHONE_B)
        for gone in ("jane.doe", "203.0.113.42", "2001:db8", PHONE_A, "99 00 00 02"):
            self.assertNotIn(gone, out)
        for kept in ("[EMAIL]", "[IP]", "[PHONE]"):
            self.assertIn(kept, out)

    def test_person_fields_are_masked_to_the_end_of_the_field(self):
        out = red("user_login: jdoe | display_name = Jane Doe\nbilling_email=x%40y.test&phone=" + PHONE_A + "&a=1")
        self.assertNotIn("jdoe", out)
        self.assertNotIn("Jane", out)
        self.assertNotIn("Doe", out)
        self.assertNotIn("99 00 00", out)
        self.assertIn("&a=1", out)

    def test_ordinary_sentences_are_left_alone(self):
        text = "Open the page on a phone: the proof line is visible. Last login: 2026-11-05 on 12:30:45, 3 items, mail: contact us."
        self.assertEqual(red(text), text)

    def test_loopback_and_versions_are_not_personal(self):
        text = "listening on 127.0.0.1 and ::1, nginx/1.18.0, version 5.0.1.2, build 10.20.30.40.50"
        self.assertEqual(red(text), text)

    def test_a_masked_value_is_not_counted_again(self):
        secrets, personal = redact.sensitive_kinds("DB_PASSWORD = [REDACTED] and contact [EMAIL] from [IP]")
        self.assertEqual((secrets, personal), ([], []))


class SecretsThatSlippedThrough(unittest.TestCase):
    def test_long_flag_with_a_prefix(self):
        key = "wJalrXUtnFEMI" + "/K7MDENG/bPxRfiCYEXAMPLEKEY"
        for flag in ("--aws-secret-access-key", "--db-password", "--private-key", "--client-secret"):
            out = red(f"tool {flag} {key} --region eu-west-3")
            self.assertNotIn("K7MDENG", out, flag)
            self.assertIn("--region eu-west-3", out)

    def test_sentry_style_public_key_in_a_dsn(self):
        out = red("dsn https://" + "abcdef0123456789" + "abcdef0123" + "@o123.ingest.sentry.io/456")
        self.assertNotIn("abcdef0123456789", out)
        self.assertIn("o123.ingest.sentry.io/456", out)

    def test_query_secret_keeps_the_closing_quote(self):
        out = red("crontab \"*/5 * * * * curl 'https://x.test/?api_key=SECRETVALUE123'\"")
        self.assertNotIn("SECRETVALUE123", out)
        self.assertTrue(out.endswith("'\""), out)


class BuildReportRefusesLeaks(unittest.TestCase):
    def data(self):
        with open(EXAMPLE, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_secret_in_any_text_is_refused_with_its_path(self):
        d = self.data()
        d["findings"][0]["evidence"] = "wp-config.php: DB_PASSWORD = " + "hunter2hunter2 found in the response"
        errs, _ = br.validate(d)
        self.assertTrue(any("findings[0].evidence" in e and "secret" in e for e in errs), errs)

    def test_a_token_in_a_strength_is_refused_too(self):
        d = self.data()
        d["strengths"][0]["evidence"] = "header " + "ghp" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        errs, _ = br.validate(d)
        self.assertTrue(any("strengths[0].evidence" in e for e in errs), errs)

    def test_personal_data_is_an_error_in_an_inside_audit_and_a_warning_outside(self):
        d = self.data()
        d["findings"][0]["evidence"] = "admin user jane.doe@client.test logged in from 203.0.113.42"
        errs, warns = br.validate(d)
        self.assertEqual([e for e in errs if "personal data" in e], [])
        self.assertTrue(any("personal data" in w for w in warns), warns)
        d["meta"]["audit_depth"] = "external_internal"
        d["meta"]["internal_access"] = ["wp"]
        errs, _ = br.validate(d)
        self.assertTrue(any("personal data" in e and "findings[0].evidence" in e for e in errs), errs)

    def test_cli_exits_2_and_writes_nothing(self):
        d = self.data()
        d["findings"][0]["evidence"] = "DB_PASSWORD = " + "hunter2hunter2"
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "f.json")
            with open(src, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            out = os.path.join(tmp, "report.md")
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), src, "--out", out], capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertFalse(os.path.exists(out))
            self.assertNotIn("hunter2hunter2", p.stderr + p.stdout)

    def test_the_shipped_template_is_clean(self):
        errs, warns = br.validate(self.data())
        self.assertEqual((errs, [w for w in warns if "personal" in w or "secret" in w]), ([], []))


class AuditFolderStaysOutOfGit(unittest.TestCase):
    def run_redact(self, cwd, out):
        return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "redact.py"), "--out", out], input="x=1\n", capture_output=True, text=True, cwd=cwd)

    def test_the_audit_folder_gets_a_gitignore_with_a_star(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "site-audit-site.test-2026-11-05")
            os.makedirs(os.path.join(folder, "internal"))
            self.assertEqual(self.run_redact(tmp, os.path.join(folder, "internal", "a.txt")).returncode, 0)
            with open(os.path.join(folder, ".gitignore"), encoding="utf-8") as fh:
                self.assertEqual(fh.read().strip(), "*")

    def test_somebody_elses_folder_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "my-site")
            os.makedirs(repo)
            self.assertEqual(self.run_redact(repo, os.path.join(repo, "evidence.txt")).returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(repo, ".gitignore")))


class NoRealLookingSecretIsStoredInTheRepository(unittest.TestCase):
    """GitHub secret scanning flags strings with the exact format of real credentials in a public repository."""
    FORMATS = [
        r"https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[A-Za-z0-9]{20,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY",
        r"AccountKey=[A-Za-z0-9+/=]{20,}",
        r"\$apr1\$[A-Za-z0-9./]{4,}\$",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bgh[pousr]_[A-Za-z0-9]{30,}",
        r"\bAIza[0-9A-Za-z_\-]{35}\b",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"\bsk-ant-[A-Za-z0-9_\-]{16,}",
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.",
    ]

    def test_no_file_contains_a_real_format_secret(self):
        found = []
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in files:
                if name == os.path.basename(__file__):
                    continue
                path = os.path.join(base, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                except (UnicodeDecodeError, OSError):
                    continue
                for rx in self.FORMATS:
                    for m in re.finditer(rx, text):
                        if os.path.basename(path) == "redact.py" and name == "redact.py":
                            continue  # the rules themselves are patterns, not secrets
                        found.append(f"{os.path.relpath(path, ROOT)}: {m.group(0)[:8]}...")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
