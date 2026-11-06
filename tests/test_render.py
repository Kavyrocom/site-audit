"""render.py against a local fixture: JS-built button, fixed banner, tall page. Skipped if Chrome is missing."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import render  # noqa: E402

HTML = """<!doctype html><html lang="en"><head><title>Fixture</title><meta name="viewport" content="width=device-width"></head>
<body style="margin:0"><h1>Fixture page</h1><div id="app"></div>
<section style="height:2500px"><h2>Tall section</h2><p>Some text in a tall section.</p></section>
<div id="banner" style="position:fixed;bottom:0;left:0;right:0;height:120px;background:#eee">We use cookies <button>Accept</button></div>
<script>document.getElementById('app').innerHTML = '<a href="/go" id="cta" style="display:block;height:20px">Start free trial</a>';</script>
</body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@unittest.skipUnless(render.find_chrome(), "Chrome/Chromium not available")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}/"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_render_sees_js_content_fixed_banner_and_scrolls(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "shots")
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "render.py"), self.url, "--out", out, "--settle", "0.5"],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(out, "rendered.json"), encoding="utf-8") as fh:
                r = json.load(fh)
            m = r["mobile"]
            self.assertIn("Start free trial", [b["text"] for b in m["buttons_and_links"]])   # built by JS
            self.assertGreaterEqual(len(m["screens"]), 2)                                      # tall page: several screens
            self.assertTrue(all(os.path.getsize(os.path.join(out, f)) > 1000 for f in m["screens"]))
            self.assertTrue(any(f["id"] == "banner" and f["screen_covered_pct"] >= 10 for f in m["fixed_or_sticky"]))
            self.assertGreaterEqual(m["small_tap_targets"], 1)                                 # 20 px high link
            self.assertTrue(m["screens_cover_page"])
            self.assertEqual(m["screens_range"][0], 1)
            self.assertTrue(any(h["text"] == "Tall section" and h["screen"] == 1 for h in m["headings"]))
            with open(os.path.join(out, "rendered-mobile.txt"), encoding="utf-8") as fh:
                self.assertIn("Tall section", fh.read())


    def test_start_captures_later_screens_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "part2")
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "render.py"), self.url, "--out", out, "--settle", "0.5",
                                "--start", "2", "--max-slices", "1"], capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(out, "rendered.json"), encoding="utf-8") as fh:
                m = json.load(fh)["mobile"]
            self.assertEqual(m["screens"], ["mobile-02.png"])
            self.assertEqual(m["screens_range"], [2, 2])
            self.assertFalse(m["screens_cover_page"])
            self.assertGreaterEqual(m["total_screens"], 3)
            self.assertFalse(os.path.exists(os.path.join(out, "mobile-01.png")))


if __name__ == "__main__":
    unittest.main()
