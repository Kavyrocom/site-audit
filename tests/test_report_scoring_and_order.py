"""Rules that an independent review showed to be untested: breaking them left the whole suite green.

Each test names the rule it protects. They were checked by breaking the rule on purpose: the test must fail.
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_consistency import run as consistency_run  # noqa: E402
from test_fix_tracker import Env, SCRIPTS, example, two_agent_actions  # noqa: E402

sys.path.insert(0, SCRIPTS)
import build_report as br  # noqa: E402


def build(findings, name="findings.json"):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(findings, fh)
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), path, "--out", os.path.join(tmp, "report.md"),
                            "--json", os.path.join(tmp, "report.json")], capture_output=True, text=True, timeout=60)
        js = None
        if os.path.exists(os.path.join(tmp, "report.json")):
            with open(os.path.join(tmp, "report.json"), encoding="utf-8") as fh:
                js = json.load(fh)
        return r, js


class EvidenceIsRequired(unittest.TestCase):
    def with_evidence(self, evidence, confidence):
        d = example()
        d["findings"][0]["evidence"] = evidence
        d["findings"][0]["confidence"] = confidence
        return build(d)[0]

    def test_a_finding_without_evidence_is_refused_whatever_its_confidence(self):
        for conf in ("measured", "deduced", "hypothesis"):
            r = self.with_evidence("", conf)
            self.assertEqual(r.returncode, 2, conf)
            self.assertIn("evidence", r.stderr)

    def test_a_token_evidence_is_refused(self):
        self.assertEqual(self.with_evidence("x", "deduced").returncode, 2)
        self.assertEqual(self.with_evidence("x", "hypothesis").returncode, 2)
        self.assertEqual(self.with_evidence("x1", "measured").returncode, 2)

    def test_a_measured_finding_must_cite_a_value_or_a_file(self):
        r = self.with_evidence("trust me, it is slow", "measured")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a proof", r.stderr)
        self.assertEqual(self.with_evidence("LCP 4.1 s in lh/lh-median.json", "measured").returncode, 0)

    def test_a_bare_file_name_or_two_words_is_not_a_proof(self):
        for weak in ("facts.json", "header absent", "see render.json", "Header missing"):
            self.assertEqual(self.with_evidence(weak, "measured").returncode, 2, weak)
        self.assertEqual(self.with_evidence("Strict-Transport-Security: absent in facts.json", "measured").returncode, 0)

    def test_one_item_reads_in_the_singular(self):
        self.assertIn("1 action:", br._singular("Current score: 50/100. 1 actions: 1 this week, 0 this month, 0 later."))
        self.assertIn("1 action :", br._singular("Score actuel : 50/100. 1 actions : 1 cette semaine."))
        self.assertNotIn("the 1 deduced", br._singular("If the 1 deduced or hypothetical findings all turn out true: 60/100"))
        self.assertEqual(br._singular("3 actions: 2 this week"), "3 actions: 2 this week")

    def test_a_plan_with_a_ticked_box_in_capitals_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "findings.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(example(), fh)
            args = [sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), path, "--out", os.path.join(tmp, "report.md")]
            self.assertEqual(subprocess.run(args, capture_output=True, text=True, timeout=60).returncode, 0)
            plan = os.path.join(tmp, "action-plan.md")
            with open(plan, encoding="utf-8") as fh:
                text = fh.read()
            ticked = text.replace("### - [ ]", "### - [X]", 1)
            self.assertNotEqual(ticked, text)
            with open(plan, "w", encoding="utf-8") as fh:
                fh.write(ticked)
            r = subprocess.run(args, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 2, r.stderr)
            with open(plan, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), ticked)


class TheScoreArithmeticIsTheDocumentedOne(unittest.TestCase):
    def one_domain(self, severity, confidence="measured"):
        d = example()
        keep = d["findings"][0]
        keep.update(severity=severity, confidence=confidence, domain="seo")
        d["findings"] = [keep]
        d["meta"]["domains_audited"] = ["seo"]
        d["strengths"] = [s for s in d["strengths"] if s["domain"] == "seo"] or [{"domain": "seo", "text": "ok", "evidence": "facts.json: ok"}]
        scores, overall, *_ = br.compute(d)
        return scores["seo"]

    def test_severity_weights_are_40_20_8_3(self):
        self.assertEqual(self.one_domain("critical"), 60)
        self.assertEqual(self.one_domain("high"), 80)
        self.assertEqual(self.one_domain("medium"), 92)
        self.assertEqual(self.one_domain("low"), 97)

    def test_confidence_discounts_the_penalty(self):
        self.assertEqual(self.one_domain("high", "deduced"), 86)        # 20 x 0.7
        self.assertEqual(self.one_domain("high", "hypothesis"), 92)     # 20 x 0.4

    def test_the_report_states_the_score_if_uncertain_findings_are_confirmed(self):
        d = example()
        for f in d["findings"]:
            f["confidence"] = "hypothesis"
        r, js = build(d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(js["overall_if_uncertain_findings_confirmed"], js["overall"])
        d2 = example()
        for f in d2["findings"]:
            f["confidence"] = "measured"
        _, js2 = build(d2)
        self.assertEqual(js2["overall_if_uncertain_findings_confirmed"], js2["overall"])


class AMalformedFileIsRefusedNotCrashed(unittest.TestCase):
    def test_every_malformed_shape_exits_2_with_a_message(self):
        cases = []
        d = example(); del d["findings"][0]["domain"]; cases.append(("missing domain", d))
        d = example(); d["findings"] = "nope"; cases.append(("findings is a string", d))
        d = example(); d["findings"] = [1, 2]; cases.append(("findings are numbers", d))
        d = example(); d["strengths"] = "nope"; cases.append(("strengths is a string", d))
        d = example(); d["meta"]["domains_audited"] = "seo"; cases.append(("domains_audited is a string", d))
        cases.append(("top level is a list", [1, 2, 3]))
        for name, payload in cases:
            r, _ = build(payload)
            self.assertEqual(r.returncode, 2, f"{name}: rc {r.returncode}\n{r.stderr[-300:]}")
            self.assertNotIn("Traceback", r.stderr, name)


class PriorityOrderBindsTheGo(unittest.TestCase):
    def test_a_lower_priority_action_cannot_be_approved_first_without_the_persons_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = two_agent_actions()
            d["findings"][0]["execution"]["mode"] = "agent"          # F1 (P1) and F2 (P2) are both agent actions
            e = Env(tmp, d)
            e.init()
            e.run("provide", "--need", "real_proof", "--note", "Customer quote with permission to publish it")
            r = e.run("approve", "--id", "F2", "--by", "Alex")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("more urgent", r.stderr)
            self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex", "--out-of-order").returncode, 2)       # no reason given
            ok = e.run("approve", "--id", "F2", "--by", "Alex", "--out-of-order", "--reason", "Alex: do the proof first")
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("OUT OF ORDER", e.read("fix-log.md"))


class PricesThatLookDifferentButAreNot(unittest.TestCase):
    PAGES = {
        "/": "<html><head><title>Atelier</title></head><body><h1>Atelier</h1><h2>Abonnement mensuel</h2><p>Abonnement mensuel : 99 € par mois HT.</p>"
             "<h2>Mariage</h2><p>Mariage reportage complet : à partir de 1 200 euros.</p><a href='/tarifs'>Tarifs</a></body></html>",
        "/tarifs": "<html><head><title>Tarifs | Atelier</title></head><body><h1>Tarifs</h1><h2>Abonnement mensuel</h2><p>Abonnement mensuel : 118,80 € par mois TTC.</p>"
                   "<h2>Mariage</h2><p>Mariage reportage complet : 1 500 euros avec album.</p>"
                   "<h2>Portrait</h2><p>Portrait en studio : 150 euros.</p></body></html>",
        "/about": "<html><head><title>A propos | Atelier</title></head><body><h1>A propos</h1><h2>Portrait</h2><p>Portrait en studio : 180 euros.</p></body></html>",
    }

    @classmethod
    def setUpClass(cls):
        cls.d = consistency_run(cls.PAGES, list(cls.PAGES))

    def amounts(self):
        return {a for c in self.d["price_conflicts"] for a in c["amounts"]}

    def test_the_same_price_with_and_without_vat_on_two_pages_is_not_a_conflict(self):
        self.assertNotIn(118.8, self.amounts(), self.d["price_conflicts"])

    def test_a_from_price_next_to_a_specific_option_is_not_a_conflict(self):
        self.assertNotIn(1200.0, self.amounts(), self.d["price_conflicts"])

    def test_a_real_contradiction_between_pages_is_still_reported(self):
        self.assertTrue(any(150.0 in c["amounts"] and 180.0 in c["amounts"] for c in self.d["price_conflicts"]), self.d["price_conflicts"])


class WrongInputExitsWithTwoAndAMessage(unittest.TestCase):
    """Exit 2 is the documented code for a refusal or a usage error. A traceback with code 1 hides it."""

    def run_script(self, *args, stdin=""):
        with tempfile.TemporaryDirectory() as tmp:
            return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, args[0]), *args[1:]], capture_output=True, text=True,
                                  timeout=60, cwd=tmp, input=stdin, env={"PATH": os.environ.get("PATH", "")})

    def assert_usage_error(self, r, label):
        self.assertEqual(r.returncode, 2, f"{label}: rc {r.returncode}\n{r.stderr[-300:]}")
        self.assertNotIn("Traceback", r.stderr, label)
        self.assertTrue(r.stderr.strip(), label)

    def test_urls_that_are_not_http_are_a_usage_error_in_every_script(self):
        for script in ("facts.py", "crawl.py", "render.py", "devtools.py", "psi.py", "lh_median.py"):
            for bad in ("ftp://example.com", "file:///etc/passwd", "javascript:alert(1)//x"):
                r = self.run_script(script, bad, "--out", "o") if script != "lh_median.py" else self.run_script(script, bad)
                if script == "lh_median.py" and r.returncode != 2 and "lighthouse" in r.stderr and "not found" in r.stderr:
                    continue                                                  # Lighthouse missing on this machine: nothing to check
                self.assert_usage_error(r, f"{script} {bad}")

    def test_missing_input_files(self):
        self.assert_usage_error(self.run_script("fix_tracker.py", "init", "--findings", "missing.json", "--state", "s.json", "--owner", "Alex"), "fix_tracker init")
        self.assert_usage_error(self.run_script("consistency.py", "--pages", "missing.jsonl", "--out", "o"), "consistency")
        self.assert_usage_error(self.run_script("redact.py", "--out", "/dev/null/x", stdin="text"), "redact")

    def test_a_scheme_less_address_still_means_https(self):
        import safenet
        self.assertEqual(safenet.start_url("example.com/page"), "https://example.com/page")
        self.assertEqual(safenet.start_url("http://example.com"), "http://example.com")


if __name__ == "__main__":
    unittest.main()
