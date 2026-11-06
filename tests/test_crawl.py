"""Offline tests: crawl.py and facts.py against a tiny local fixture site (no network)."""
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

PAGE = "<!doctype html><html lang='en'><head><title>{title}</title>{meta}<meta name='viewport' content='width=device-width'></head><body>{body}</body></html>"
LONG = " ".join(["word"] * 200)
SITE = {
    "/": PAGE.format(title="Home", meta="<meta name='description' content='Home page'><link rel='canonical' href='/'>",
                     body=f"<h1>Home</h1><p>{LONG}</p><a href='/a'>A</a> <a href='/b'>B</a> <a href='/old'>old</a> <a href='/missing'>gone</a> <a href='/private/x'>private</a>"),
    "/a": PAGE.format(title="Same title", meta="<meta name='description' content='A'>", body=f"<h1>A</h1><h1>A again</h1><p>{LONG}</p><img src='x.png'>"),
    "/b": PAGE.format(title="Same title", meta="<meta name='robots' content='noindex'>", body="<p>short</p>"),
    "/new": PAGE.format(title="New", meta="<meta name='description' content='N'>", body=f"<h1>New</h1><p>{LONG}</p>"),
    "/sitemap-only": PAGE.format(title="Only in sitemap", meta="<meta name='description' content='S'>", body=f"<h1>S</h1><p>{LONG}</p>"),
}
ROBOTS = "User-agent: *\nDisallow: /private/\nSitemap: {base}/sitemap.xml\n"
SITEMAP = "<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>{base}/</loc></url><url><loc>{base}/a</loc></url><url><loc>{base}/sitemap-only</loc></url></urlset>"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        base = f"http://127.0.0.1:{self.server.server_port}"
        path = self.path.split("?")[0]
        if path == "/robots.txt":
            return self.send(200, ROBOTS.format(base=base), "text/plain", head)
        if path == "/sitemap.xml":
            return self.send(200, SITEMAP.format(base=base), "application/xml", head)
        if path == "/old":
            self.send_response(301)
            self.send_header("Location", "/older")
            self.end_headers()
            return
        if path == "/older":
            self.send_response(301)
            self.send_header("Location", "/new")
            self.end_headers()
            return
        if path in SITE:
            return self.send(200, SITE[path], "text/html; charset=utf-8", head)
        return self.send(404, "not found", "text/plain", head)

    def send(self, code, body, ctype, head):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head:
            self.wfile.write(data)


class CrawlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def run_crawl(self, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "crawl")
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "crawl.py"), self.base + "/", "--out", out, "--delay", "0", "--workers", "2", *extra],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(os.path.join(out, "summary.json"), encoding="utf-8") as fh:
                summary = json.load(fh)
            with open(os.path.join(out, "pages.jsonl"), encoding="utf-8") as fh:
                pages = [json.loads(line) for line in fh]
            return summary, pages

    def test_crawl_finds_expected_issues(self):
        s, pages = self.run_crawl("--max-pages", "20")
        i = s["issues"]
        urls = {p["url"] for p in pages}
        self.assertIn(self.base + "/a", urls)
        self.assertIn(self.base + "/sitemap-only", urls)           # reached through the sitemap sample
        self.assertNotIn(self.base + "/private/x", urls)           # robots.txt respected
        self.assertEqual(s["robots_skipped"], 1)
        self.assertTrue(any(x["count"] == 2 for x in i["duplicate_titles"]))
        self.assertTrue(any(x["url"].endswith("/a") for x in i["multiple_h1"]))
        self.assertTrue(any(u.endswith("/b") for u in i["noindex_pages"]))
        self.assertTrue(any(x["url"].endswith("/b") for x in i["thin_content_under_150_words"]))
        self.assertTrue(any(x["url"].endswith("/missing") and x["status"] == 404 for x in i["broken_internal_links_not_crawled"]) or
                        any(x["url"].endswith("/missing") for x in i["error_pages"]))
        self.assertTrue(any(x["hops"] == 2 for x in i["redirect_chains_2plus_hops"]))
        self.assertEqual(i["images_missing_alt"]["total"], 1)

    def test_page_cap_is_reported(self):
        s, pages = self.run_crawl("--max-pages", "2")
        self.assertEqual(len(pages), 2)
        self.assertTrue(s["cap_reached"])
        self.assertTrue(any("cap reached" in w for w in s["warnings"]))

    def test_facts_on_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "facts.json")
            p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "facts.py"), self.base + "/a", "--out", out], capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(out, encoding="utf-8") as fh:
                f = json.load(fh)
        self.assertEqual(f["status"], 200)
        self.assertEqual(f["title"], "Same title")
        self.assertEqual(f["h1_count_raw"], 2)
        self.assertEqual(f["images"]["missing_alt_attr"], 1)
        self.assertEqual(f["site_level"]["robots.txt"]["status"], 200)
        self.assertEqual(f["site_level"]["soft_404_test"]["status"], 404)


if __name__ == "__main__":
    unittest.main()
