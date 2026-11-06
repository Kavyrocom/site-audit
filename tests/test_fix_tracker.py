"""fix_tracker.py: the rules that make an agent apply a plan safely (priority order, GO, nothing missing)."""
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


def example():
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


# `provide --ref NAME` wants NAME to be a variable that exists in the environment (a pasted value is not a name)
REF_ENV = {**os.environ, "GTM_TOKEN": "x", "GTM_ENV": "x", "WP_ENV": "x"}


class Env:
    def __init__(self, tmp, findings=None):
        self.tmp = tmp
        self.findings = os.path.join(tmp, "findings.json")
        self.state = os.path.join(tmp, "fix-state.json")
        with open(self.findings, "w", encoding="utf-8") as fh:
            json.dump(findings or example(), fh)
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "build_report.py"), self.findings, "--out", os.path.join(tmp, "report.md")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def run(self, *args):
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), args[0], "--state", self.state, *args[1:]],
                           capture_output=True, text=True, env=REF_ENV)
        return r

    def init(self, owner="Alex"):
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", self.findings, "--state", self.state, "--owner", owner],
                           capture_output=True, text=True, env=REF_ENV)
        assert r.returncode == 0, r.stderr
        return r

    def read(self, name):
        with open(os.path.join(self.tmp, name), encoding="utf-8") as fh:
            return fh.read()


def two_agent_actions():
    d = example()
    d["findings"][1]["execution"]["mode"] = "agent"
    return d


class TrackerTests(unittest.TestCase):
    def test_full_flow_enforces_priority_go_and_needs(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, two_agent_actions())
            e.init()
            self.assertEqual(e.run("init", "--findings", e.findings).returncode, 2)          # no silent reset
            st = e.run("status").stdout
            self.assertIn("P1  F1", st)
            self.assertIn("blocked: needs tag_manager_access, consent_rules", st)
            needs = e.run("needs").stdout
            for n in ("tag_manager_access", "consent_rules", "real_proof"):
                self.assertIn(n, needs)
            nxt = e.run("next").stdout
            self.assertIn("readiness=blocked", nxt)
            self.assertIn("do NOT guess, do NOT start", nxt)
            # blocked: cannot be approved
            r = e.run("approve", "--id", "F1", "--by", "Alex")
            self.assertEqual(r.returncode, 2)
            self.assertIn("missing", r.stderr)
            # secrets are never stored
            self.assertEqual(e.run("provide", "--need", "tag_manager_access", "--note", "verified: list 200").returncode, 2)       # needs --ref
            r = e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_TOKEN", "--note", "verified: token abcdefghijklmnopqrstuvwxyz0123456789")
            self.assertEqual(r.returncode, 2)                                                                                 # token-like note
            self.assertEqual(e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_TOKEN", "--note", "no check done").returncode, 2)  # no probe
            self.assertEqual(e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_TOKEN", "--note", "verified: list containers 200").returncode, 0)
            self.assertEqual(e.run("provide", "--need", "consent_rules", "--note", "analytics only after consent").returncode, 0)
            with open(e.state, encoding="utf-8") as fh:
                raw = fh.read()
            self.assertIn("GTM_TOKEN", raw)
            self.assertNotIn("abcdefghijklmnopqrstuvwxyz", raw)
            self.assertIn("readiness=ready", e.run("next").stdout)
            # priority order: F2 (P2) cannot jump ahead of F1 (P1) without the person's word
            self.assertEqual(e.run("provide", "--need", "real_proof", "--note", "1,200 teams, quote from Anna, ok to publish").returncode, 0)
            self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex").returncode, 2)
            self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex", "--out-of-order").returncode, 2)                  # reason missing
            # the agent cannot approve its own work
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "agent").returncode, 2)
            # done before GO is refused
            self.assertEqual(e.run("done", "--id", "F1", "--proof", "applied and checked it").returncode, 2)
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "Alex").returncode, 0)
            self.assertEqual(e.run("done", "--id", "F1", "--proof", "ok").returncode, 2)                                      # proof too thin
            r = e.run("done", "--id", "F1", "--proof", "lh_median.py: median TBT 180 ms, spread 4")
            self.assertEqual(r.returncode, 0, r.stderr)
            plan = e.read("action-plan.md")
            self.assertIn("### - [x] 1. Third-party scripts block the main thread (F1)", plan)
            self.assertIn("### - [ ] 2.", plan)
            r = e.run("approve", "--id", "F2", "--by", "Alex")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(e.run("done", "--id", "F2", "--proof", "phone check: proof line visible on screen 1").returncode, 0)
            self.assertIn("All actions are done", e.run("next").stdout)
            log = e.read("fix-log.md")
            self.assertIn("GO by Alex", log)
            self.assertIn("F1: DONE", log)

    def test_human_and_assisted_actions_are_handed_off(self):
        d = example()
        d["findings"][0]["execution"] = {"mode": "human", "risk": "high", "needs": [], "rollback": ""}
        self.assertEqual(d["findings"][1]["execution"]["mode"], "assisted")
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp, d)
            e.init()
            self.assertIn("readiness=human", e.run("next").stdout)
            self.assertEqual(e.run("approve", "--id", "F1", "--by", "Alex").returncode, 2)          # the agent cannot apply a human action
            self.assertEqual(e.run("handoff", "--id", "F1", "--note", "instructions sent to the developer").returncode, 0)
            self.assertIn("handed_off", e.run("status").stdout)
            self.assertEqual(e.run("handoff", "--id", "F2", "--note", "draft sent").returncode, 2)   # F2 still needs real_proof
            e.run("provide", "--need", "real_proof", "--note", "1,200 teams, quote from Anna, ok to publish")
            self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex").returncode, 2)          # assisted: handoff, not an agent GO
            self.assertEqual(e.run("handoff", "--id", "F2", "--note", "proof line text sent to the editor").returncode, 0)
            nxt = e.run("next").stdout
            self.assertIn("Waiting on the person: F1, F2", nxt)                                      # handed-off actions never block the agent
            self.assertEqual(e.run("done", "--id", "F1", "--proof", "developer confirmed; curl returns 404").returncode, 0)
            self.assertEqual(e.run("done", "--id", "F2", "--proof", "phone check: proof line visible on screen 1").returncode, 0)
            self.assertIn("All actions are done", e.run("next").stdout)

    def test_failed_deferred_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp)
            e.init()
            for n, kw in (("tag_manager_access", ["--ref", "GTM_TOKEN", "--note", "verified: 200"]), ("consent_rules", ["--note", "after consent"])):
                self.assertEqual(e.run("provide", "--need", n, *kw).returncode, 0)
            e.run("approve", "--id", "F1", "--by", "Alex")
            self.assertEqual(e.run("fail", "--id", "F1", "--reason", "tag broke the checkout").returncode, 0)
            nxt = e.run("next").stdout
            self.assertIn("FAILED earlier", nxt)
            self.assertEqual(e.run("approve", "--id", "F2", "--by", "Alex").returncode, 2)          # a failed action still blocks the next ones
            self.assertEqual(e.run("defer", "--id", "F1", "--by", "Alex", "--reason", "person: skip it").returncode, 0)
            self.assertEqual(e.run("reopen", "--id", "F1").returncode, 0)
            self.assertIn("pending", e.run("status").stdout.replace("ready", "pending"))

    def test_access_revoked_blocks_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            e = Env(tmp)
            e.init()
            e.run("provide", "--need", "tag_manager_access", "--ref", "GTM_TOKEN", "--note", "verified: 200")
            e.run("provide", "--need", "consent_rules", "--note", "after consent")
            self.assertIn("readiness=ready", e.run("next").stdout)
            e.run("provide", "--need", "tag_manager_access", "--revoke")
            self.assertIn("readiness=blocked", e.run("next").stdout)

    def test_invalid_findings_refuse_init(self):
        d = example()
        del d["findings"][0]["execution"]
        with tempfile.TemporaryDirectory() as tmp:
            findings = os.path.join(tmp, "findings.json")
            with open(findings, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "fix_tracker.py"), "init", "--findings", findings, "--state", os.path.join(tmp, "s.json"), "--owner", "Alex"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertFalse(os.path.exists(os.path.join(tmp, "s.json")))


if __name__ == "__main__":
    unittest.main()
