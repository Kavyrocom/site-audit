"""redact.py: secrets are masked, the setting names and the useful facts stay."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "site-audit", "scripts", "redact.py")


def red(text):
    r = subprocess.run([sys.executable, "-I", SCRIPT], input=text, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


SECRETS = [
    "s3cr3tP4ssw0rd!x", "abcdef0123456789abcdef0123456789", "hunter2hunter2", ("ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"),
    ("AKIA" + "ABCDEFGHIJKLMNOP"), ("sk_l" + "ive_abcdefghijklmnop1234"), ("AIza" + "SyA-abcdefghijklmnopqrstuvwxyz01234"),
    ("eyJh" + "bGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"), "dXNlcjpzZWNyZXRwYXNz", "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC",
    "abcd efgh ijkl mnop qrst uvwx",
]


class RedactTests(unittest.TestCase):
    def test_wp_config_values_are_masked_names_kept(self):
        out = red("define( 'DB_NAME', 'wp_site' );\ndefine( 'DB_PASSWORD', 's3cr3tP4ssw0rd!x' );\ndefine('AUTH_KEY', 'abcdef0123456789abcdef0123456789');\n"
                  "define('WP_DEBUG', true);\n$table_prefix = 'wp_';\n")
        self.assertNotIn("s3cr3tP4ssw0rd!x", out)
        self.assertNotIn("abcdef0123456789abcdef0123456789", out)
        self.assertIn("DB_PASSWORD", out)
        self.assertIn("AUTH_KEY", out)
        self.assertIn("WP_DEBUG', true", out)                 # not a secret: useful evidence
        self.assertIn("DB_NAME', 'wp_site'", out)

    def test_env_files_headers_urls_and_tokens(self):
        text = ("DB_PASSWORD=hunter2hunter2\nAPP_URL=https://example.test\nSTRIPE_SECRET: " + ("sk_l" + "ive_abcdefghijklmnop1234") + "\n"
                "Authorization: Bearer " + ("eyJh" + "bGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r") + "\n"
                "Authorization: Basic dXNlcjpzZWNyZXRwYXNz\n"
                "origin = https://deploy:s3cr3tP4ssw0rd!x@git.example.test/site.git\n"
                "https://api.example.test/v1/items?page=2&api_key=abcdef0123456789abcdef0123456789&limit=5\n"
                "token " + ("ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789") + " and " + ("AKIA" + "ABCDEFGHIJKLMNOP") + " and " + ("AIza" + "SyA-abcdefghijklmnopqrstuvwxyz01234") + "\n")
        out = red(text)
        for s in SECRETS[:9]:
            self.assertNotIn(s, out, s)
        self.assertIn("APP_URL=https://example.test", out)
        self.assertIn("page=2", out)
        self.assertIn("limit=5", out)
        self.assertIn("git.example.test/site.git", out)

    def test_private_key_block_and_app_password(self):
        out = red("-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nabc\n-----END RSA " + "PRIVATE KEY-----\nuser: bot\napp password: \"abcd efgh ijkl mnop qrst uvwx\"\n")
        self.assertNotIn("MIIEvQIBADANBgkqhkiG9w0BAQEFAASC", out)
        self.assertNotIn("abcd efgh ijkl mnop qrst uvwx", out)
        self.assertIn("user: bot", out)

    def test_harmless_text_is_untouched(self):
        text = ("PHP 8.3.12 (cli)\nwordpress 6.8.1\nplugin akismet 5.3 active update available\nserver: nginx/1.24.0\nnginx: configuration file /etc/nginx/nginx.conf test is successful\n"
                "keyboard layout: fr\nmonkey patch applied\nTotal 25 plugins, 18 active\nautoload size 1.2 MB\n")
        self.assertEqual(red(text), text)


def j(*parts):
    """Build a realistic-looking secret at run time, so no whole secret is stored in this repository."""
    return "".join(parts)


class MoreWaysASecretLeaks(unittest.TestCase):
    """Each case below slipped through an earlier version (found by an independent review)."""

    def check(self, text, *secrets, keep=()):
        out = red(text)
        for s in secrets:
            self.assertNotIn(s, out, f"leaked {s!r} in {out!r}")
        for k in keep:
            self.assertIn(k, out)
        self.assertEqual(red(out), out, "masking twice must change nothing")
        return out

    def test_json_keys(self):
        self.check('{"db_password": "Hunter2Secret", "db_host": "localhost"}', "Hunter2Secret", keep=("db_host", "localhost"))
        self.check('{"AUTH_KEY": "put your unique phrase here 123"}', "put your unique phrase", keep=("AUTH_KEY",))

    def test_quoted_value_with_spaces(self):
        self.check("DB_PASSWORD='two words secret'", "two words secret", keep=("DB_PASSWORD",))
        self.check('api_key: "my long api key value"', "my long api key value")

    def test_mysql_flag_without_a_space(self):
        self.check("mysql -u root -pHunter2Secret wpdb", "Hunter2Secret", keep=("mysql -u root", "wpdb"))
        self.check("mysqldump --password=Hunter2Secret db", "Hunter2Secret")

    def test_provider_key_formats(self):
        for key in (j("glp", "at-abcdEFGH1234ijklMNOP"), j("sk-", "ant-api03-abcdEFGH1234ijklMNOPqrstUVWX"),
                    j("sk-", "proj-abcdEFGH1234ijklMNOPqrstUVWX"), j("n", "pm_abcdEFGH1234ijklMNOPqrstUVWX567890"),
                    j("h", "f_abcdEFGH1234ijklMNOPqrstUVWX567890"), j("ya", "29.abcdEFGH1234ijklMNOPqrst"),
                    j("whs", "ec_abcdEFGH1234ijkl5678"), j("SG", ".abcdEFGH1234ijkl.mnopQRST5678uvwx")):
            self.check(f"here is the thing: {key} and more", key)

    def test_wordpress_app_password_wherever_it_stands(self):
        pw = "abcd EFGH ijkl MNOP qrst UVWX"  # mixed case, as WordPress issues them
        self.check(f"the pw is {pw} then more words\nnext line", pw, "abcd EFGH ijkl")
        self.check(f"first line\n{pw}\nlast line", pw)
        self.check(f"{pw}", pw)

    def test_jwt_and_authorization_headers(self):
        jwt = j("ey", "JhbGciOiJIUzI1NiJ9.", "eyJzdWIiOiIxMjM0NTY3ODkwIn0.", "dBjftJeZ4CVPmB92K27uhbUJU1p1r")
        self.check(f"token seen: {jwt}", jwt)
        self.check("Authorization: Basic dXNlcjpzZWNyZXRwYXNz", "dXNlcjpzZWNyZXRwYXNz", keep=("Authorization",))
        self.check("authorization: Bearer abc123def456ghi789", "abc123def456ghi789")
        self.check("X-Api-Key: abc123def456ghi789", "abc123def456ghi789")

    def test_cookie_headers_keep_the_names_only(self):
        out = self.check("Cookie: wordpress_logged_in_x=abc123def456; _ga=GA1.2.3.4\nSet-Cookie: sid=zzz999yyy888; Path=/; HttpOnly",
                         "abc123def456", "zzz999yyy888", keep=("wordpress_logged_in_x=", "sid=", "Path=/"))

    def test_plain_sentences(self):
        self.check("the GTM password is Hunter2Secret", "Hunter2Secret")
        self.check("mot de passe : Hunter2Secret", "Hunter2Secret")
        self.check("token = abc123def456ghi789", "abc123def456ghi789")

    def test_unterminated_private_key_block_is_masked_to_the_end(self):
        self.check("-----BEGIN OPENSSH " + "PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\nAAAAB3NzaC1yc2EAAAADAQAB", "b3BlbnNzaC1rZXktdjEAAAAA")

    def test_cli_writes_the_file_itself_and_reports_the_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "internal.txt")
            r = subprocess.run([sys.executable, "-I", SCRIPT, "--out", target], input="DB_PASSWORD=Hunter2Secret\nWP_DEBUG=false\n",
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "")
            with open(target, encoding="utf-8") as fh:
                body = fh.read()
            self.assertNotIn("Hunter2Secret", body)
            self.assertIn("WP_DEBUG=false", body)
            self.assertIn("1 value(s) masked", r.stderr)

    def test_everyday_text_is_left_alone(self):
        text = ("This long sentence has four letter words only some very much like this one here.\n"
                "Total 25 plugins\nkeyboard layout: fr\nPHP 8.3.12\nwp-content/uploads/2026/11/img.jpg\n"
                "Cookie policy page: /cookies\nstatus: active\n")
        self.assertEqual(red(text), text)


if __name__ == "__main__":
    unittest.main()
