"""Two families of rules: what an audit that starts on a private host may still reach, and what the evidence files
mask (user tables, street addresses, database hosts, tracking ids). Values that have the format of a real key are
assembled at run time, never stored.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import netguard  # noqa: E402
import redact  # noqa: E402
import safenet  # noqa: E402


def red(text):
    return redact.redact(text)[0]


class AnAuditOnAPrivateHostStaysOnThatHost(unittest.TestCase):
    def setUp(self):
        self._saved = dict(safenet._AUDIT)
        self.addCleanup(lambda: safenet._AUDIT.update(self._saved))

    def test_link_local_and_metadata_are_never_allowed(self):
        safenet._AUDIT["start_addrs"] = set()
        for addr in ("169.254.169.254", "169.254.1.1", "fe80::1", "::ffff:169.254.169.254"):
            self.assertFalse(safenet.private_allowed(addr), addr)
        self.assertIsNotNone(safenet.check("http://169.254.169.254/latest/meta-data/", True))
        safenet._AUDIT["start_addrs"] = {"169.254.169.254", "127.0.0.1"}          # even when the audit "starts" there
        self.assertFalse(safenet.private_allowed("169.254.169.254"))
        self.assertTrue(safenet.private_allowed("127.0.0.1"))

    def test_only_the_start_host_is_allowed_once_it_is_recorded(self):
        safenet._AUDIT["start_addrs"] = {"192.168.1.20"}
        self.assertTrue(safenet.private_allowed("192.168.1.20"))
        for addr in ("192.168.1.21", "10.0.0.5", "127.0.0.1"):
            self.assertFalse(safenet.private_allowed(addr), addr)
        self.assertIsNone(safenet.check("http://192.168.1.20/page", True))
        self.assertIsNotNone(safenet.check("http://10.0.0.5/", True))

    def test_a_loopback_start_allows_the_rest_of_loopback_only(self):
        safenet._AUDIT["start_addrs"] = {"127.0.0.1"}
        self.assertTrue(safenet.private_allowed("127.0.0.2"))
        self.assertTrue(safenet.private_allowed("::1"))
        self.assertFalse(safenet.private_allowed("10.1.1.1"))

    def test_public_addresses_are_unaffected(self):
        safenet._AUDIT["start_addrs"] = {"192.168.1.20"}
        self.assertIsNone(safenet.check("http://93.184.216.34/", True))

    def test_the_proxy_dial_applies_the_same_rule(self):
        safenet._AUDIT["start_addrs"] = {"127.0.0.1"}
        sock, why = netguard.dial("169.254.169.254", 80, True, timeout=1)
        self.assertIsNone(sock)
        self.assertIn("refused", why)
        sock, why = netguard.dial("10.255.255.1", 80, True, timeout=1)
        self.assertIsNone(sock)
        self.assertIn("refused", why)
        self.assertEqual(why.count("10.255.255.1"), 1)   # the host as asked, not repeated as the address it resolved to

    def test_set_audit_start_records_the_addresses_of_a_private_start_only(self):
        safenet.set_audit_start("http://127.0.0.1:9/")
        self.assertIn("127.0.0.1", safenet._AUDIT["start_addrs"])
        safenet.set_audit_start("http://93.184.216.34/")
        self.assertEqual(safenet._AUDIT["start_addrs"], set())


class EvidenceMasksWhatTheLastReviewShowedWasMissing(unittest.TestCase):
    def test_a_mailchimp_style_key_is_masked(self):
        key = "0123456789abcdef" * 2 + "-us" + "21"
        self.assertNotIn(key, red(f"list sync used {key} yesterday"))
        self.assertNotIn(key, red(f"MAILCHIMP_API={key}"))

    def test_a_user_table_keeps_only_the_ids(self):
        boxed = ("+----+------------+--------------+\n| ID | user_login | display_name |\n+----+------------+--------------+\n"
                 "| 1  | alice      | Alice Martin |\n| 2  | bob        | Bob Durand   |\n+----+------------+--------------+\n")
        out = red(boxed)
        for leaked in ("alice", "Alice", "Martin", "bob", "Durand"):
            self.assertNotIn(leaked, out)
        self.assertIn("user_login", out)           # the header is the evidence
        csv = red("ID,user_login,display_name,user_email\n1,alice,Alice Martin,a@x.example\n2,bob,Bob D,b@x.example\n")
        for leaked in ("alice", "Martin", "bob", "x.example"):
            self.assertNotIn(leaked, csv)

    def test_a_key_value_line_is_not_taken_for_a_table(self):
        out = red("user_login: jdoe | display_name = Jane Doe\nstatus=ok&a=1")
        self.assertNotIn("jdoe", out)
        self.assertIn("status=ok&a=1", out)

    def test_french_street_addresses_and_postal_fields(self):
        for text in ("Livraison au 12 rue des Lilas, 44000 Nantes ce matin.", "Siège : 3 bis avenue Victor Hugo.", "billing_address_1: 8 impasse du Kiwi", "siret: 12345678901234"):
            out = red(text)
            self.assertNotIn("Lilas", out)
            self.assertNotIn("Victor", out)
            self.assertNotIn("Kiwi", out)
            self.assertNotIn("12345678901234", out)
        self.assertEqual(red("Open the place du marché stand"), "Open the place du marché stand")

    def test_an_internal_database_host_is_masked_but_localhost_is_kept(self):
        self.assertNotIn("db-internal-7", red("DB_HOST=db-internal-7.example.test"))
        self.assertNotIn("db-internal-7", red("define('DB_HOST', 'db-internal-7.example.test');"))
        self.assertIn("localhost", red("db_host: localhost"))
        self.assertNotIn("shop_rw", red("DB_USER=shop_rw"))

    def test_tracking_ids_in_a_query_string_and_a_log_time_that_is_not_an_address(self):
        out = red('127.0.0.1 - - [05/Nov/2026:07:46:12 +0100] "GET /?mc_eid=abc123&fbclid=zzz9 HTTP/1.1" 200 12')
        self.assertNotIn("abc123", out)
        self.assertNotIn("zzz9", out)
        self.assertIn("2026:07:46:12", out)         # a time, not an IPv6 address
        self.assertIn("[IP]", red("client 2001:db8:0:0:0:0:0:1 connected"))

    def test_masking_twice_changes_nothing(self):
        for text in ("billing_address_1: 8 impasse du Kiwi\nsiret: 12345678901234\nuser_login: carol", "DB_HOST=db-internal-7.example.test",
                     "ID,user_login\n1,alice"):
            once = red(text)
            self.assertEqual(red(once), once)
            self.assertEqual(redact.sensitive_kinds(once), ([], []))


class AnUnignoredAuditFolderInsideARepositoryIsReported(unittest.TestCase):
    def run_git(self, cwd, *args):
        subprocess.run(["git", "-C", cwd, *args], capture_output=True, check=True,
                       env={"PATH": os.environ.get("PATH", ""), "HOME": cwd, "GIT_CONFIG_NOSYSTEM": "1"})

    def test_warning_when_not_ignored_and_silence_when_ignored_or_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_git(tmp, "init", "-q", ".")
            out = os.path.join(tmp, "audit")
            os.makedirs(out)
            self.assertIn("not ignored", safenet.private_output(os.path.join(out, "report.md")) or "")
            with open(os.path.join(tmp, ".gitignore"), "w", encoding="utf-8") as fh:
                fh.write("audit/\n")
            self.assertIsNone(safenet.private_output(os.path.join(out, "report.md")))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(safenet.private_output(os.path.join(tmp, "report.md")))

    def test_the_site_audit_folder_protects_itself_and_says_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_git(tmp, "init", "-q", ".")
            folder = os.path.join(tmp, "site-audit-example.test-2026-11-06")
            os.makedirs(folder)
            self.assertIsNone(safenet.private_output(os.path.join(folder, "report.md")))
            with open(os.path.join(folder, ".gitignore"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "*\n")


if __name__ == "__main__":
    unittest.main()
