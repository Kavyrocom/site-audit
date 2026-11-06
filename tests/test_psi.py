"""psi.py against a fake Google server that follows the documented response format.

These tests prove the reading of the responses and the freshness rules. They do NOT prove the Google API
contract itself: that needs a real API key (see the README).
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "site-audit", "scripts", "psi.py")
KEY = "SECRETKEY1234567890"


def d(days_ago):
    x = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return {"year": x.year, "month": x.month, "day": x.day}


def psi_body(url, lcp_ms=1800):
    nodata = "nodata" in url
    le = {"id": url, "metrics": {
        "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3100, "distributions": [], "category": "AVERAGE"},
        "INTERACTION_TO_NEXT_PAINT": {"percentile": 180, "distributions": [], "category": "FAST"},
        "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5, "distributions": [], "category": "FAST"}}, "overall_category": "AVERAGE"}
    if nodata:
        le["origin_fallback"] = True
    return {"id": url, "loadingExperience": le,
            "originLoadingExperience": {"id": "https://example.test", "metrics": le["metrics"], "overall_category": "AVERAGE"},
            "lighthouseResult": {"requestedUrl": url, "lighthouseVersion": "13.0.0", "fetchTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                                 "configSettings": {"formFactor": "mobile"}, "runWarnings": [], "environment": {"hostUserAgent": "HeadlessChrome", "benchmarkIndex": 1500},
                                 "categories": {"performance": {"score": None if "nullscore" in url else 0.83}, "seo": {"score": 1.0}, "accessibility": {"score": 0.96}, "best-practices": {"score": 0.81}},
                                 "audits": {"largest-contentful-paint": {"numericValue": lcp_ms}, "first-contentful-paint": {"numericValue": 1200}, "total-blocking-time": {"numericValue": 640},
                                            "cumulative-layout-shift": {"numericValue": 0.02}, "speed-index": {"numericValue": 2100}, "interactive": {"numericValue": 5200},
                                            "server-response-time": {"numericValue": 120},
                                            "unused-javascript": {"title": "Reduce unused JavaScript", "details": {"type": "opportunity", "overallSavingsMs": 450, "overallSavingsBytes": 204800}}}}}


def crux_body(last_days_ago, form="PHONE"):
    hist = lambda g, n, p: [{"start": 0, "end": 2500, "density": g}, {"start": 2500, "end": 4000, "density": n}, {"start": 4000, "density": p}]
    return {"record": {"key": {"formFactor": form}, "collectionPeriod": {"firstDate": d(last_days_ago + 27), "lastDate": d(last_days_ago)},
                       "metrics": {"largest_contentful_paint": {"histogram": hist(0.6, 0.25, 0.15), "percentiles": {"p75": 3100}},
                                   "interaction_to_next_paint": {"histogram": hist(0.8, 0.15, 0.05), "percentiles": {"p75": 180}},
                                   "cumulative_layout_shift": {"histogram": hist(0.9, 0.07, 0.03), "percentiles": {"p75": "0.05"}}}}}


def hist_body():
    periods = [{"firstDate": d(7 * k + 6), "lastDate": d(7 * k)} for k in range(7, -1, -1)]
    lcp = [2200, 2300, 2400, 2600, 2800, 3000, 3100, 3200]
    return {"record": {"collectionPeriods": periods, "metrics": {"largest_contentful_paint": {"percentilesTimeseries": {"p75s": lcp}},
                                                                  "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": ["0.05"] * 7 + [None]}}}}}


def serve(mode="ok"):
    class H(http.server.BaseHTTPRequestHandler):
        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            if mode == "quota":
                return self._send(429, {"error": {"code": 429, "message": f"Quota exceeded for key {q.get('key', [''])[0]}"}})
            if q.get("key") != [KEY]:                                       # what Google does without a key
                return self._send(429, {"error": {"code": 429, "message": "Quota exceeded for quota metric 'Queries'"}})
            lcp = 3300 if "disagree" in q["url"][0] else 1800
            self._send(200, psi_body(q["url"][0], lcp))

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            target = body.get("url") or body.get("origin")
            if self.path.startswith("/hist"):
                return self._send(200, hist_body())
            if "nodata" in target and "url" in body:
                return self._send(404, {"error": {"code": 404, "message": "chrome ux report data not found", "status": "NOT_FOUND"}})
            self._send(200, crux_body(30 if "stale" in target else 1, body.get("formFactor", "PHONE")))

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def run(srv, url, *extra, key=KEY):
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    env = {"PATH": os.environ.get("PATH", ""), "SITEAUDIT_PSI_ENDPOINT": base + "/psi", "SITEAUDIT_CRUX_ENDPOINT": base + "/crux",
           "SITEAUDIT_CRUX_HISTORY_ENDPOINT": base + "/hist"}
    if key:
        env["PAGESPEED_API_KEY"] = key
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "-I", SCRIPT, url, "--out", tmp, *extra], capture_output=True, text=True, timeout=60, env=env)
        with open(os.path.join(tmp, "psi.json"), encoding="utf-8") as fh:
            return r, json.load(fh)


class PsiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_lab_is_fresh_and_field_is_page_level(self):
        r, j = run(self.srv, "https://example.test/page", "--history")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = j["strategies"]["mobile"]
        self.assertLess(s["lab"]["age_seconds"], 120)                       # a run made seconds ago
        self.assertEqual(s["lab"]["scores"]["performance"], 83)
        self.assertEqual(s["lab"]["metrics"]["tbt_ms"], 640)
        self.assertEqual(s["lab"]["opportunities"][0]["id"], "unused-javascript")
        self.assertEqual(s["psi_field_page"]["scope"], "page")
        self.assertAlmostEqual(s["psi_field_page"]["metrics"]["cls"]["p75"], 0.05)   # PSI gives CLS x100
        c = s["crux_page"]
        self.assertEqual(c["period"]["window_days"], 28)
        self.assertEqual(c["period"]["days_since_last"], 1)
        self.assertFalse(c["period"]["stale"])
        self.assertEqual(c["metrics"]["lcp_ms"]["rating"], "needs improvement")
        self.assertEqual(c["metrics"]["cls"]["p75"], 0.05)                  # CrUX gives CLS as a string
        self.assertIs(c["core_web_vitals_pass"], False)                     # LCP 3100 ms is not good

    def test_a_category_google_could_not_score_is_null_never_zero(self):
        r, j = run(self.srv, "https://example.test/nullscore")
        self.assertEqual(r.returncode, 0, r.stderr)
        scores = j["strategies"]["mobile"]["lab"]["scores"]
        self.assertIsNone(scores["performance"])
        self.assertEqual(scores["seo"], 100)

    def test_history_trend(self):
        _, j = run(self.srv, "https://example.test/page", "--history")
        t = j["strategies"]["mobile"]["history_page"]["trend"]
        self.assertEqual(t["lcp_ms"]["direction"], "worse")                 # 2600 four periods earlier, 3200 now
        self.assertGreater(t["lcp_ms"]["change_pct"], 5)
        self.assertEqual(j["strategies"]["mobile"]["history_page"]["periods"], 8)

    def test_page_without_data_falls_back_and_says_so(self):
        _, j = run(self.srv, "https://example.test/nodata")
        s = j["strategies"]["mobile"]
        self.assertEqual(s["psi_field_page"]["scope"], "origin")            # PSI fell back to the whole site
        self.assertEqual(s["crux_page"]["status"], "no_data")
        self.assertEqual(s["crux_origin"]["scope"], "origin")
        text = " ".join(j["interpretation"])
        self.assertIn("too little traffic", text)
        self.assertIn("not this page", text)

    def test_stale_field_data_is_flagged(self):
        _, j = run(self.srv, "https://example.test/stale")
        p = j["strategies"]["mobile"]["crux_page"]["period"]
        self.assertTrue(p["stale"])
        self.assertEqual(p["days_since_last"], 30)
        self.assertIn("stale", " ".join(j["interpretation"]))

    def test_lab_and_field_on_different_sides_of_the_limit(self):
        _, j = run(self.srv, "https://example.test/disagree")               # lab LCP 3300 ms, field p75 3100 ms: same side, no note
        self.assertNotIn("different sides", " ".join(j["interpretation"]))
        _, j = run(self.srv, "https://example.test/page")                   # lab 1800 ms, field 3100 ms: opposite sides
        self.assertIn("different sides", " ".join(j["interpretation"]))

    def test_desktop_uses_the_desktop_form_factor(self):
        _, j = run(self.srv, "https://example.test/page", "--strategy", "both")
        self.assertEqual(j["strategies"]["desktop"]["crux_page"]["form_factor"], "DESKTOP")
        self.assertEqual(j["strategies"]["mobile"]["crux_page"]["form_factor"], "PHONE")

    def test_no_key_exits_3_and_says_not_measured(self):
        r, j = run(self.srv, "https://example.test/page", key=None)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(j["status"], "no_key")
        self.assertIn("not measured", j["message"])

    def test_quota_error_is_reported_and_the_key_never_leaks(self):
        srv = serve("quota")
        try:
            r, j = run(srv, "https://example.test/page")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(j["status"], "quota_exceeded")
        self.assertEqual(r.returncode, 4)
        blob = r.stdout + r.stderr + json.dumps(j)
        self.assertNotIn(KEY, blob)
        self.assertIn("***", blob)

    def test_the_key_is_never_written_or_printed(self):
        r, j = run(self.srv, "https://example.test/page", "--history")
        self.assertNotIn(KEY, r.stdout + r.stderr + json.dumps(j))


if __name__ == "__main__":
    unittest.main()
