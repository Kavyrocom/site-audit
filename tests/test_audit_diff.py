"""audit_diff.py: compare two audits of the same site without ever inventing a fix.

The rules tested here, each named by its test:
  - a finding the second audit does not report is a CANDIDATE fix, never a confirmed one, and its
    'how to verify' line is recalled
  - a finding whose domain the second audit dropped is 'not audited', not 'fixed'
  - matching ignores the finding ids (the model numbers them fresh in every audit)
  - scores are recomputed from the findings, with the report's arithmetic
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_fix_tracker import SCRIPTS, example  # noqa: E402

sys.path.insert(0, SCRIPTS)
import build_report as br  # noqa: E402


def write(tmp, name, data):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def run(first, second, tmp):
    return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "audit_diff.py"), first, second,
                           "--out", os.path.join(tmp, "d.md"), "--json", os.path.join(tmp, "d.json")],
                          capture_output=True, text=True, timeout=60)


def second_audit(**changes):
    """The example audit, one month later, with the changes the test chooses."""
    d = json.loads(json.dumps(example()))
    d["meta"]["date"] = "2026-02-15"
    for k, v in changes.items():
        d[k] = v
    return d


def security_finding(fid="S1"):
    return {"id": fid, "domain": "security", "title": "No HSTS header", "severity": "medium", "effort": "low",
            "impact": "medium", "confidence": "measured",
            "observation": "The Strict-Transport-Security header is absent.",
            "evidence": "facts.json: Strict-Transport-Security: absent on /",
            "action": "Send the header from the server.", "pages": ["/"], "owner": "developer",
            "fix_steps": ["Add the header in the server configuration."],
            "verify": "curl -I https://example.com/ answers with Strict-Transport-Security.",
            "execution": {"mode": "assisted", "risk": "low", "rollback": "", "needs": []}}


class CandidateFixesAreNotConfirmedFixes(unittest.TestCase):
    def test_an_absent_finding_is_a_candidate_and_keeps_its_verify_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            second = second_audit(findings=[example()["findings"][0]])          # F2 is not reported any more
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", second), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
            self.assertIn("No longer reported by the second audit (1)", md)
            self.assertIn("candidate fix, not a confirmed one", md)
            self.assertIn("to confirm : Open the page on a phone: the proof line is visible", md)
            self.assertNotIn("fixed:", md)                                       # the word 'fixed' is never claimed
            d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
            self.assertEqual([f["title"] for f in d["no_longer_reported"]], ["No proof near the main button"])
            self.assertEqual(d["no_longer_reported"][0]["verify"], example()["findings"][1]["verify"])

    def test_a_finding_whose_domain_was_dropped_is_not_a_fixed_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = example()
            old["findings"].append(security_finding())
            old["strengths"].append({"domain": "security", "text": "HTTPS everywhere.",
                                     "evidence": "facts.json: scheme=https on every page"})
            old["meta"]["domains_audited"] = old["meta"]["domains_audited"] + ["security"]
            new = second_audit()                                                # no security domain any more
            r = run(write(tmp, "a.json", old), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
            self.assertIn("Domain not audited this time (1)", md)
            self.assertIn("No HSTS header", md.split("Domain not audited")[1])   # it is in that section, not in 'no longer reported'
            d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
            self.assertEqual([f["id"] for f in d["not_audited"]], ["S1"])
            self.assertEqual(d["no_longer_reported"], [])

    def test_matching_ignores_the_ids_the_model_numbers_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["findings"][0]["id"] = "F10"                                     # same problems, fresh numbering
            new["findings"][1]["id"] = "F11"
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
            self.assertEqual(len(d["still_reported"]), 2, d)
            self.assertEqual((d["no_longer_reported"], d["new"]), ([], []))
            self.assertEqual(d["still_reported"][0]["id_first"], "F1")
            self.assertEqual(d["still_reported"][0]["id_second"], "F10")

    def test_a_duplicate_pairs_one_by_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = example()
            twin = json.loads(json.dumps(old["findings"][0]))
            twin["id"] = "F9"
            twin["observation"] = "The second run of the same blocking scripts."
            old["findings"].append(twin)                                         # the same problem, written twice
            new = second_audit()                                                # reported once this time
            r = run(write(tmp, "a.json", old), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
            self.assertEqual(len(d["still_reported"]), 2, d)                    # F1 and F2 are still reported
            self.assertEqual([f["id"] for f in d["no_longer_reported"]], ["F9"], d)   # the twin is the candidate

    def test_a_severity_move_is_named_up_or_down(self):
        for sev, change, word in (("critical", "up", "severity up"), ("medium", "down", "severity down")):
            with tempfile.TemporaryDirectory() as tmp:
                new = second_audit()
                new["findings"][0]["severity"] = sev
                r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
                self.assertEqual(r.returncode, 0, r.stderr)
                d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
                self.assertEqual(d["still_reported"][0]["change"], change, d)
                md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
                self.assertIn(f"({word})", md)


class ScoresAndRefusals(unittest.TestCase):
    def test_scores_are_recomputed_from_the_findings_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["findings"][0]["severity"] = "medium"                            # high -> medium: the speed score moves
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
            old_scores, old_overall = br.compute(example())[:2]
            new_scores, new_overall = br.compute(new)[:2]
            self.assertEqual(d["first"]["overall"], old_overall)
            self.assertEqual(d["second"]["overall"], new_overall)
            self.assertEqual(d["second"]["scores"]["performance"], new_scores["performance"])
            md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
            self.assertIn("| Speed | 80/100 | 92/100 | +12 |", md)
            self.assertIn(f"| **Overall score** | {old_overall}/100 | {new_overall}/100 |", md)

    def test_two_audits_of_two_different_sites_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["meta"]["url"] = "https://other-shop.example/"
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("two different sites", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "d.md")))

    def test_the_older_audit_must_come_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["meta"]["date"] = "2025-12-01"                                   # earlier than the first audit
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("before the first", r.stderr)
            self.assertNotIn("Traceback", r.stderr)

    def test_a_findings_file_that_was_never_validated_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            del new["findings"][0]["evidence"]                                   # a file build_report would refuse
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("quality gate", r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "d.md")))

    def test_missing_files_exit_2_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(os.path.join(tmp, "a.json"), os.path.join(tmp, "b.json"), tmp)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("cannot read", r.stderr)
            self.assertNotIn("Traceback", r.stderr)


class HonestyOfTheSmallPrint(unittest.TestCase):
    def test_a_smaller_second_audit_warns_before_any_absence_is_read(self):
        for scope_a, pa, scope_b, pb, expect in (("site", 12, "site", 5, "covered fewer pages"),
                                                 ("page", None, "site", 5, "do not have the same scope")):
            with tempfile.TemporaryDirectory() as tmp:
                old = example()
                old["meta"].update(scope=scope_a, pages_audited=pa)
                new = second_audit()
                new["meta"].update(scope=scope_b, pages_audited=pb)
                r = run(write(tmp, "a.json", old), write(tmp, "b.json", new), tmp)
                self.assertEqual(r.returncode, 0, r.stderr)
                d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
                self.assertTrue(any(expect in w for w in d["warnings"]), d["warnings"])
                md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
                self.assertIn("> " + d["warnings"][0], md)

    def test_a_second_audit_that_covers_other_domains_warns_about_the_overall_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["meta"]["domains_audited"] = example()["meta"]["domains_audited"] + ["accessibility"]
            new["strengths"].append({"domain": "accessibility", "text": "Buttons have readable names.",
                                      "evidence": "shots/rendered.json: buttons_and_links name every control"})
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.load(open(os.path.join(tmp, "d.json"), encoding="utf-8"))
            self.assertTrue(any("does not cover the same domains" in w and "accessibility" in w for w in d["warnings"]), d["warnings"])

    def test_a_quoted_em_dash_of_the_site_survives_and_the_prose_stays_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["findings"].append({                                            # a finding only the second audit reports
                "id": "F7", "domain": "seo", "title": "Meta title cut", "severity": "low", "effort": "low",
                "impact": "low", "confidence": "measured",
                "observation": 'The meta title reads "Shop — plants" and stops there.',
                "evidence": 'facts.json: title_len=16, title "Shop — plants" measured',
                "action": "Write a title that names the shop and what it sells.", "pages": ["/"], "owner": "content",
                "fix_steps": ["Rewrite the title and keep it under 60 characters."],
                "verify": "facts.py shows a title of 40 to 60 characters.",
                "execution": {"mode": "assisted", "risk": "low", "rollback": "", "needs": []}})
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
            self.assertIn('"Shop — plants"', md)                                # the quotation keeps its own characters
            self.assertFalse(br.forbidden_outside_quotes(md))

    def test_the_french_diff_reads_in_french(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = second_audit()
            new["meta"]["language"] = "fr"
            r = run(write(tmp, "a.json", example()), write(tmp, "b.json", new), tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = open(os.path.join(tmp, "d.md"), encoding="utf-8").read()
            self.assertIn("Comparaison des deux audits", md)
            self.assertIn("Toujours signalé (2)", md)


if __name__ == "__main__":
    unittest.main()
