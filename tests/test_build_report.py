import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
EXAMPLE = os.path.join(ROOT, "skills", "site-audit", "templates", "findings.example.json")
sys.path.insert(0, SCRIPTS)
import build_report as br  # noqa: E402


def load():
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


class ValidateTests(unittest.TestCase):
    def test_example_is_valid(self):
        errs, _ = br.validate(load())
        self.assertEqual(errs, [])

    def test_measured_without_evidence_is_refused(self):
        d = load()
        d["findings"][0]["evidence"] = ""
        errs, _ = br.validate(d)
        self.assertTrue(any("evidence" in e for e in errs))

    def test_domain_without_strength_is_refused(self):
        d = load()
        d["strengths"] = [s for s in d["strengths"] if s["domain"] != "seo"]
        errs, _ = br.validate(d)
        self.assertTrue(any("lists no strength" in e for e in errs))

    def test_unknown_values_are_refused(self):
        d = load()
        d["findings"][0]["severity"] = "huge"
        d["findings"][1]["domain"] = "magic"
        errs, _ = br.validate(d)
        self.assertTrue(any("severity" in e for e in errs))
        self.assertTrue(any("unknown domain" in e for e in errs))

    def test_finding_in_unlisted_domain_is_refused(self):
        d = load()
        d["findings"][0]["domain"] = "security"
        errs, _ = br.validate(d)
        self.assertTrue(any("not listed in meta.domains_audited" in e for e in errs))

    def test_em_dash_is_refused(self):
        d = load()
        d["meta"]["verdict"] = "Good \u2014 mostly"
        errs, _ = br.validate(d)
        self.assertTrue(any("em dash" in e for e in errs))

    def test_em_dash_inside_a_verbatim_quote_of_the_site_is_kept(self):
        for quote in ('The title says "Shop \u2014 plants"', 'Title: \u201cShop \u2014 plants\u201d', 'Titre : \u00abShop \u2014 plants\u00bb', 'Title is `Shop \u2014 plants`'):
            d = load()
            d["findings"][0]["evidence"] += " " + quote
            errs, _ = br.validate(d)
            self.assertEqual([e for e in errs if "em dash" in e], [], quote)

    def test_em_dash_outside_the_quote_is_still_refused_and_the_message_says_where(self):
        d = load()
        d["findings"][0]["evidence"] += ' The title says "Shop \u2014 plants" \u2014 which is too long.'
        errs, _ = br.validate(d)
        hits = [e for e in errs if "em dash" in e]
        self.assertEqual(len(hits), 1)
        self.assertIn("findings[0].evidence", hits[0])
        self.assertIn("outside a quotation", hits[0])

    def test_em_dash_in_a_quote_does_not_hide_one_in_the_next_sentence_of_another_field(self):
        d = load()
        d["findings"][0]["evidence"] += ' "a \u2014 b"'
        d["findings"][1]["action"] += " now \u2014 later"
        errs, _ = br.validate(d)
        self.assertTrue(any("em dash" in e and "findings[1].action" in e for e in errs), errs)

    def test_fix_steps_verify_owner_are_required(self):
        for key in ("fix_steps", "verify", "owner"):
            d = load()
            del d["findings"][0][key]
            errs, _ = br.validate(d)
            self.assertTrue(any(key in e for e in errs), key)
        d = load()
        d["findings"][0]["fix_steps"] = ["ok", " "]
        errs, _ = br.validate(d)
        self.assertTrue(any("fix_steps" in e for e in errs))
        d = load()
        d["findings"][0]["owner"] = "intern"
        errs, _ = br.validate(d)
        self.assertTrue(any("owner" in e for e in errs))

    def test_execution_block_is_required_and_checked(self):
        d = load()
        del d["findings"][0]["execution"]
        errs, _ = br.validate(d)
        self.assertTrue(any("execution" in e for e in errs))
        d = load()
        d["findings"][0]["execution"]["mode"] = "robot"
        d["findings"][0]["execution"]["risk"] = "huge"
        errs, _ = br.validate(d)
        self.assertTrue(any("execution.mode" in e for e in errs))
        self.assertTrue(any("execution.risk" in e for e in errs))
        d = load()
        d["findings"][0]["execution"]["rollback"] = ""
        errs, _ = br.validate(d)
        self.assertTrue(any("rollback" in e for e in errs))     # medium risk without a way back
        d = load()
        d["findings"][0]["execution"]["needs"][0]["kind"] = "wish"
        d["findings"][0]["execution"]["needs"][1]["id"] = "Bad Id"
        errs, _ = br.validate(d)
        self.assertTrue(any("kind must be" in e for e in errs))
        self.assertTrue(any("snake_case" in e for e in errs))

    def test_same_need_must_keep_one_definition(self):
        d = load()
        d["findings"][1]["execution"]["needs"].append({"id": "consent_rules", "kind": "info", "what": "x"})
        errs, _ = br.validate(d)
        self.assertTrue(any("different kind" in e for e in errs))

    def test_finding_id_is_required_and_unique(self):
        d = load()
        del d["findings"][0]["id"]
        errs, _ = br.validate(d)
        self.assertTrue(any("'id' is required" in e for e in errs))
        d = load()
        d["findings"][1]["id"] = d["findings"][0]["id"]
        errs, _ = br.validate(d)
        self.assertTrue(any("duplicate id" in e for e in errs))

    def test_priority_numbers_follow_the_ranking(self):
        d = load()
        self.assertEqual(br.priority_map(d), {"F1": 1, "F2": 2})
        quick = dict(d["findings"][1], id="Q", severity="high", effort="low", impact="high", confidence="measured")
        d["findings"].append(quick)
        self.assertEqual(br.priority_map(d)["Q"], 1)

    def test_internal_audit_needs_a_verified_access(self):
        d = load()
        d["meta"]["audit_depth"] = "external_internal"
        errs, _ = br.validate(d)
        self.assertTrue(any("internal_access" in e for e in errs))
        d["meta"]["internal_access"] = ["ssh"]
        d["findings"][0]["layer"] = "internal"
        errs, _ = br.validate(d)
        self.assertEqual(errs, [])
        d["meta"]["audit_depth"] = "external"
        errs, _ = br.validate(d)
        self.assertTrue(any("needs a verified access" in e for e in errs))
        d["meta"]["audit_depth"] = "deep"
        errs, _ = br.validate(d)
        self.assertTrue(any("audit_depth" in e for e in errs))

    def test_report_states_the_depth_and_tags_internal_findings(self):
        d = load()
        d["meta"]["audit_depth"] = "external_internal"
        d["meta"]["internal_access"] = ["ssh", "wp"]
        d["findings"][0]["layer"] = "internal"
        d["meta"]["language"] = "en"
        scores, overall, ranked, top, plan = br.compute(d)
        md = br.render(d, scores, overall, top, plan)
        self.assertIn("external + internal (read-only access: ssh, wp)", md)
        self.assertIn("· internal", md)

    def test_site_scope_needs_pages_audited(self):
        d = load()
        d["meta"]["scope"] = "site"
        d["meta"]["pages_audited"] = 0
        errs, _ = br.validate(d)
        self.assertTrue(any("pages_audited" in e for e in errs))


class ScoreTests(unittest.TestCase):
    def test_scores_are_deterministic_and_penalised(self):
        d = load()
        s1 = br.compute(d)[:2]
        s2 = br.compute(copy.deepcopy(d))[:2]
        self.assertEqual(s1, s2)
        scores, overall = s1
        self.assertEqual(scores["performance"], 100 - 20)       # one measured high finding
        self.assertEqual(scores["cro"], 100 - round(8 * 0.7))   # one deduced medium finding
        self.assertEqual(scores["seo"], 100)
        self.assertTrue(0 <= overall <= 100)

    def test_score_never_below_zero(self):
        d = load()
        d["findings"] = [dict(d["findings"][0], id=f"X{i}", severity="critical") for i in range(10)]
        scores, _ = br.compute(d)[:2]
        self.assertEqual(scores["performance"], 0)

    def test_ranking_puts_high_impact_low_effort_first(self):
        d = load()
        quick = dict(d["findings"][1], id="Q", severity="high", effort="low", impact="high", confidence="measured")
        d["findings"].append(quick)
        top = br.compute(d)[3]
        self.assertEqual(top[0]["id"], "Q")


class CliTests(unittest.TestCase):
    def run_cli(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "findings.json")
            with open(src, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            out = os.path.join(tmp, "report.md")
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), src, "--out", out, "--json", os.path.join(tmp, "r.json")],
                               capture_output=True, text=True)
            md = None
            if os.path.exists(out):
                with open(out, encoding="utf-8") as fh:
                    md = fh.read()
            return p, md

    def test_cli_writes_the_report_with_a_quoted_em_dash_and_nothing_else_in_it(self):
        d = load()
        d["findings"][0]["evidence"] += ' The page title is "Shop \u2014 plants".'
        p, md = self.run_cli(d)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Shop \u2014 plants", md)
        self.assertNotIn("\u2014", md.replace("Shop \u2014 plants", ""))     # the only em dashes in the report are the quoted ones

    def test_cli_refuses_a_report_whose_prose_has_an_em_dash(self):
        d = load()
        d["meta"]["verdict"] = "Good \u2014 mostly"
        p, md = self.run_cli(d)
        self.assertEqual(p.returncode, 2)
        self.assertIsNone(md)

    def test_cli_renders_report(self):
        p, md = self.run_cli(load())
        self.assertEqual(p.returncode, 0, p.stderr)
        for needle in ("# Audit of https://example.com/", "What works", "Top priorities", "Action plan", "Not measured", "Third-party scripts block"):
            self.assertIn(needle, md)
        self.assertNotIn("\u2014", md)

    def test_cli_french_labels(self):
        d = load()
        d["meta"]["language"] = "fr"
        p, md = self.run_cli(d)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("# Audit de https://example.com/", md)
        self.assertIn("Ce qui marche", md)

    def test_cli_writes_action_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "findings.json")
            with open(src, "w", encoding="utf-8") as fh:
                json.dump(load(), fh)
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), src, "--out", os.path.join(tmp, "report.md")],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(tmp, "action-plan.md"), encoding="utf-8") as fh:
                plan = fh.read()
            for needle in ("# Action plan: https://example.com/", "- [ ] 1. Third-party scripts block the main thread (F1)", "To do", "How to verify", "Owner",
                           "After the fixes", "Move analytics and chat", "median TBT at or under 200 ms", "What the agent needs from you",
                           "`tag_manager_access`", "Have the agent apply this plan", "Rollback", "Execution"):
                self.assertIn(needle, plan)
            self.assertNotIn("\u2014", plan)
            with open(os.path.join(tmp, "report.md"), encoding="utf-8") as fh:
                self.assertIn("action-plan.md", fh.read())

    def test_plan_phases_split_quick_wins_from_projects(self):
        d = load()
        _, _, _, _, plan = br.compute(d)
        self.assertEqual([f["id"] for f in plan["week"]], ["F2"])    # low effort, medium impact
        self.assertEqual([f["id"] for f in plan["month"]], ["F1"])   # high severity, medium effort
        self.assertEqual(plan["later"], [])

    def test_cli_exit_2_and_no_file_on_error(self):
        d = load()
        d["findings"][0]["evidence"] = ""
        p, md = self.run_cli(d)
        self.assertEqual(p.returncode, 2)
        self.assertIsNone(md)


if __name__ == "__main__":
    unittest.main()
