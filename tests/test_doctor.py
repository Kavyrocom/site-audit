"""doctor.py: a read-only check of what this machine can run. It must never print a key, never fail on a missing optional
piece, and say what is lost and how to fix it."""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import doctor  # noqa: E402


def run(env_extra=None, *args, drop=()):
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "doctor.py"), *args], capture_output=True, text=True, env=env, timeout=90)


class DoctorTests(unittest.TestCase):
    def test_json_lists_every_check_and_what_can_run(self):
        p = run(None, "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        d = json.loads(p.stdout)
        names = [c["name"] for c in d["checks"]]
        for n in ("python", "chrome", "lighthouse", "unlighthouse", "google_api_key", "system", "user", "work_folder"):
            self.assertIn(n, names)
        self.assertTrue(d["ok"])
        self.assertIn("facts, crawl, consistency, report (HTML only)", d["can_run"])
        for c in d["checks"]:
            self.assertIn(c["status"], ("ok", "missing", "optional", "warning"))
            if c["status"] in ("missing", "optional"):
                self.assertTrue(c["how_to_fix"], c["name"])            # a missing piece always says how to get it
                self.assertTrue(c["without_it"], c["name"])            # and what is lost without it

    def test_a_machine_with_nothing_installed_still_exits_zero_and_says_what_is_lost(self):
        p = run({"PATH": "/nonexistent", "CHROME_PATH": ""}, "--json", drop=("PAGESPEED_API_KEY", "PSI_API_KEY", "GOOGLE_API_KEY"))
        self.assertEqual(p.returncode, 0, p.stderr)
        d = json.loads(p.stdout)
        by = {c["name"]: c for c in d["checks"]}
        self.assertEqual(by["lighthouse"]["status"], "missing")
        self.assertEqual(by["google_api_key"]["status"], "optional")
        self.assertFalse(d["can_run"]["lab speed and accessibility scores"])
        self.assertFalse(d["can_run"]["real-visitor data (Google)"])
        self.assertTrue(d["can_run"]["facts, crawl, consistency, report (HTML only)"])

    def test_the_value_of_a_key_is_never_printed(self):
        secret = "AIzaSy-this-must-never-appear-0123456789"
        for args in (("--json",), ()):
            p = run({"PSI_API_KEY": secret}, *args)
            self.assertNotIn(secret, p.stdout + p.stderr)
            self.assertIn("$PSI_API_KEY", p.stdout)

    def test_an_empty_key_variable_does_not_count(self):
        p = run({"PSI_API_KEY": "", "PAGESPEED_API_KEY": "", "GOOGLE_API_KEY": ""}, "--json")
        by = {c["name"]: c for c in json.loads(p.stdout)["checks"]}
        self.assertEqual(by["google_api_key"]["status"], "optional")

    def test_human_output_marks_what_is_missing(self):
        p = run({"PATH": "/nonexistent"}, drop=("PSI_API_KEY", "PAGESPEED_API_KEY", "GOOGLE_API_KEY"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("MISSING  lighthouse", p.stdout)
        self.assertIn("to fix: npm install -g lighthouse", p.stdout)
        self.assertRegex(p.stdout, r"cannot\s+lab speed and accessibility scores")
        self.assertNotIn("\u2014", p.stdout)

    def test_ready_for_needs_each_piece(self):
        items = [{"name": n, "status": "ok"} for n in ("python", "chrome", "lighthouse", "unlighthouse", "google_api_key")]
        self.assertTrue(all(doctor.ready_for(items).values()))
        items[1]["status"] = "missing"                                                     # no Chrome
        parts = doctor.ready_for(items)
        self.assertFalse(parts["rendered screens and text, browser network view"])
        self.assertFalse(parts["lab speed and accessibility scores"])
        self.assertTrue(parts["real-visitor data (Google)"])
        items[0]["status"] = "missing"                                                     # no Python: nothing
        self.assertFalse(any(doctor.ready_for(items).values()))


if __name__ == "__main__":
    unittest.main()
