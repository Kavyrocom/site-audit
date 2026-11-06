"""Hostile-site tests: what an untrusted site (or an unlucky page) must not be able to make the scripts do.

Every case here comes from an independent review of the repository: redirects to file: or to private hosts,
robots.txt rules aimed at this crawler, XML entity bombs, wrong charsets, relative canonicals, look-alike
tracker names.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "site-audit", "scripts")
sys.path.insert(0, SCRIPTS)
import crawl  # noqa: E402
import facts  # noqa: E402
import safenet  # noqa: E402

PAGE = "<!doctype html><html lang='fr'><head><meta charset='{cs}'><title>Titre de test assez long pour passer</title>{head}</head><body>{body}</body></html>"


class Site(BaseHTTPRequestHandler):
    routes = {}
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        type(self).hits.append(path)
        r = type(self).routes.get(path)
        if r is None:
            r = (404, {}, b"not found")
        code, headers, body = r(self) if callable(r) else r
        self.send_response(code)
        headers = {"Content-Type": "text/html; charset=utf-8", **headers}
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def html(body="<h1>x</h1>", head="", cs="utf-8"):
    return PAGE.format(cs=cs, head=head, body=body).encode(cs)


class Base(unittest.TestCase):
    def serve(self, routes, host="127.0.0.1"):
        handler = type("H", (Site,), {"routes": routes, "hits": []})
        srv = ThreadingHTTPServer((host, 0), handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return srv, handler, f"http://{host}:{srv.server_port}"

    def run_script(self, name, *args, timeout=60):
        return subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, name), *args],
                              capture_output=True, text=True, timeout=timeout)


class NetworkGuard(Base):
    def test_only_http_and_https_are_ever_fetched(self):
        self.assertIsNotNone(safenet.check("file:///etc/passwd", allow_private=True))
        self.assertIsNotNone(safenet.check("ftp://example.com/x", allow_private=True))
        self.assertIsNotNone(safenet.check("gopher://example.com/", allow_private=True))
        self.assertIsNone(safenet.check("https://example.com/", allow_private=True))

    def test_public_start_cannot_lead_to_private_hosts(self):
        fake = {"example.com": ["93.184.216.34"], "metadata.example": ["169.254.169.254"],
                "intranet.example": ["10.0.0.5"], "loop.example": ["127.0.0.1"], "v6.example": ["::1"],
                "mapped.example": ["::ffff:10.0.0.1"], "mixed.example": ["93.184.216.34", "192.168.1.9"]}
        with mock.patch.object(safenet, "_resolve", lambda h: fake.get(h, [])):
            self.assertIsNone(safenet.check("https://example.com/", False))
            for h in ("metadata.example", "intranet.example", "loop.example", "v6.example", "mapped.example", "mixed.example"):
                self.assertIsNotNone(safenet.check(f"http://{h}/", False), h)
            with mock.patch.dict(safenet._AUDIT, {"allow_private": True, "start_addrs": {"10.0.0.5"}}):
                self.assertIsNone(safenet.check("http://intranet.example/", True), "a local audit may stay on the host it started on")
                self.assertIsNotNone(safenet.check("http://mapped.example/", True), "and not reach another private host")
            with mock.patch.dict(safenet._AUDIT, {"allow_private": True, "start_addrs": set()}):
                self.assertIsNotNone(safenet.check("http://intranet.example/", True), "no start recorded: only loopback is allowed")
                self.assertIsNone(safenet.check("http://loop.example/", True))
            self.assertFalse(safenet.starts_private("http://intranet.example/"), "a name that resolves to a private address does not switch the guard off")
            with mock.patch.dict(os.environ, {safenet.ALLOW_PRIVATE_ENV: "intranet.example"}):
                self.assertTrue(safenet.starts_private("http://intranet.example/"), "unless the person running the audit names that host")
                self.assertFalse(safenet.starts_private("http://metadata.example/"))
            self.assertTrue(safenet.starts_private("http://10.1.2.3/"))
            self.assertTrue(safenet.starts_private("http://localhost:8080/") or not safenet._resolve("localhost"))
            self.assertFalse(safenet.starts_private("https://example.com/"))

    def test_redirect_to_file_is_refused_not_followed_and_does_not_crash(self):
        _, hits, base = self.serve({"/": (302, {"Location": "file:///etc/hostname"}, b"")})
        r = facts.fetch(base + "/", facts.DEFAULT_UA)
        self.assertEqual(r["status"], 0)
        self.assertIn("scheme", r["error"])
        self.assertEqual(r["body"], "")

    def test_redirect_from_a_public_site_to_a_private_host_is_never_requested(self):
        internal, internal_hits, internal_base = self.serve({"/secret": (200, {}, b"AccessKeyId=NOT-A-REAL-KEY")}, host="127.0.0.2")
        _, _, base = self.serve({"/": (302, {"Location": internal_base + "/secret"}, b"")})
        real = safenet._resolve
        # pretend the start host is public; the redirect target resolves for real, to a loopback address
        with mock.patch.object(safenet, "_resolve", lambda h: ["93.184.216.34"] if h == "127.0.0.1" else real(h)):
            r = facts.fetch(base + "/", facts.DEFAULT_UA, allow_private=False)
        self.assertEqual(r["status"], 0)
        self.assertIn("private", r["error"])
        self.assertNotIn("NOT-A-REAL-KEY", r["body"])
        self.assertEqual(internal_hits.hits, [], "the private host must not even be contacted")

    def test_facts_script_survives_a_redirect_to_file_and_writes_no_file_content(self):
        _, _, base = self.serve({"/": (200, {}, html("<h1>Accueil</h1>")), "/llms.txt": (302, {"Location": "file:///etc/hostname"}, b"")})
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "facts.json")
            r = self.run_script("facts.py", base + "/", "--out", out)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            with open(out, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["site_level"]["/llms.txt"]["status"], 0)

    def test_crawl_survives_a_link_that_redirects_to_file(self):
        _, _, base = self.serve({"/": (200, {}, html("<a href='/f'>f</a><a href='/ok'>ok</a>")),
                                 "/f": (302, {"Location": "file:///etc/hostname"}, b""),
                                 "/ok": (200, {}, html("<h1>ok</h1>"))})
        with tempfile.TemporaryDirectory() as d:
            r = self.run_script("crawl.py", base + "/", "--max-pages", "6", "--delay", "0", "--out", d)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])
            self.assertTrue(os.path.exists(os.path.join(d, "summary.json")))


class BodyHandling(Base):
    def test_charset_from_header_and_from_meta_are_honoured(self):
        text = "Café crème à Genève"
        _, _, base = self.serve({
            "/h": (200, {"Content-Type": "text/html; charset=iso-8859-1"}, text.encode("latin-1")),
            "/m": (200, {"Content-Type": "text/html"}, html(f"<p>{text}</p>", cs="iso-8859-1")),
        })
        self.assertIn(text, facts.fetch(base + "/h", facts.DEFAULT_UA)["body"])
        self.assertIn(text, facts.fetch(base + "/m", facts.DEFAULT_UA)["body"])

    def test_body_is_capped_and_flagged_truncated(self):
        _, _, base = self.serve({"/big": (200, {}, b"a" * 50_000)})
        r = facts.fetch(base + "/big", facts.DEFAULT_UA, max_bytes=10_000)
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["body"]), 10_000)

    def test_gzip_bomb_is_capped(self):
        import gzip
        bomb = gzip.compress(b"0" * 30_000_000)
        _, _, base = self.serve({"/z": (200, {"Content-Encoding": "gzip"}, bomb)})
        r = facts.fetch(base + "/z", facts.DEFAULT_UA, max_bytes=1_000_000)
        self.assertTrue(r["truncated"])
        self.assertLessEqual(len(r["body"]), 1_000_000)


class PageFacts(Base):
    def facts_for(self, path_html):
        _, _, base = self.serve({"/": (200, {}, path_html.encode())})
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "f.json")
            r = self.run_script("facts.py", base + "/", "--out", out)
            self.assertEqual(r.returncode, 0, r.stderr[-400:])
            with open(out, encoding="utf-8") as fh:
                return json.load(fh)

    def test_relative_canonical_to_itself_is_self(self):
        d = self.facts_for(PAGE.format(cs="utf-8", head="<link rel='canonical' href='/'>", body="<h1>x</h1>"))
        self.assertTrue(d["canonical_is_self"], d["canonical"])

    def test_canonical_to_another_page_is_not_self(self):
        d = self.facts_for(PAGE.format(cs="utf-8", head="<link rel='canonical' href='/autre'>", body="<h1>x</h1>"))
        self.assertFalse(d["canonical_is_self"])

    def test_a_class_named_sticky_is_not_a_consent_tool(self):
        d = self.facts_for(PAGE.format(cs="utf-8", head="", body="<div class='sticky-nav'>menu</div><h1>x</h1>"))
        self.assertNotIn("cookieyes", d["consent_tool_detected"])

    def test_real_cookieyes_markup_is_still_detected(self):
        d = self.facts_for(PAGE.format(cs="utf-8", head="", body="<div class='cky-consent-container'></div><h1>x</h1>"))
        self.assertIn("cookieyes", d["consent_tool_detected"])

    def test_text_that_talks_about_matomo_is_not_a_tracker(self):
        d = self.facts_for(PAGE.format(cs="utf-8", head="<script type='application/ld+json'>{\"articleBody\":\"matomo vs plausible\"}</script>",
                                       body="<h1>Matomo ou Plausible ?</h1><p>On compare matomo et plausible.</p>"))
        self.assertNotIn("matomo", d["trackers_detected"])

    def test_real_matomo_script_is_detected(self):
        d = self.facts_for(PAGE.format(cs="utf-8", head="<script src='/js/matomo.js'></script>", body="<h1>x</h1>"))
        self.assertIn("matomo", d["trackers_detected"])

    def test_robots_disallow_all_reads_the_group_for_the_wildcard_only(self):
        f = facts.robots_disallows_all
        self.assertFalse(f("User-agent: *\nDisallow: /wp-admin/\n\nUser-agent: GPTBot\nDisallow: /\n"))
        self.assertTrue(f("User-agent: *\nDisallow: /\n"))
        self.assertTrue(f("User-agent: GPTBot\nUser-agent: *\nDisallow: /\n"))
        self.assertFalse(f("User-agent: *\nDisallow: /\nAllow: /public\n"))
        self.assertFalse(f("User-agent: *\nDisallow:\n"))
        self.assertFalse(f(""))


class CrawlerManners(Base):
    def test_rules_aimed_at_this_crawler_are_obeyed_even_without_a_wildcard_group(self):
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: SiteAuditSkill\nDisallow: /\n"),
                  "/": (200, {}, html("<a href='/a'>a</a>")), "/a": (200, {}, html("<h1>a</h1>"))}
        _, h, base = self.serve(routes)
        with tempfile.TemporaryDirectory() as d:
            self.run_script("crawl.py", base + "/", "--max-pages", "5", "--delay", "0", "--out", d)
        self.assertNotIn("/a", h.hits)

    def test_rules_for_other_bots_do_not_stop_us(self):
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: GPTBot\nDisallow: /\n"),
                  "/": (200, {}, html("<a href='/a'>a</a>")), "/a": (200, {}, html("<h1>a</h1>"))}
        _, h, base = self.serve(routes)
        with tempfile.TemporaryDirectory() as d:
            self.run_script("crawl.py", base + "/", "--max-pages", "5", "--delay", "0", "--out", d)
        self.assertIn("/a", h.hits)

    def test_crawl_delay_is_honoured_up_to_a_cap(self):
        routes = {"/robots.txt": (200, {"Content-Type": "text/plain"}, b"User-agent: *\nCrawl-delay: 1\n"),
                  "/": (200, {}, html("<a href='/a'>a</a>")), "/a": (200, {}, html("<h1>a</h1>"))}
        _, h, base = self.serve(routes)
        import time
        t0 = time.time()
        with tempfile.TemporaryDirectory() as d:
            self.run_script("crawl.py", base + "/", "--max-pages", "5", "--delay", "0", "--workers", "1", "--out", d)
        self.assertGreaterEqual(time.time() - t0, 1.0)

    def test_sitemap_with_an_entity_declaration_is_refused(self):
        bomb = b"<?xml version='1.0'?><!DOCTYPE lolz [<!ENTITY a 'aaaa'>]><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>http://x/&a;</loc></url></urlset>"
        _, _, base = self.serve({"/sitemap.xml": (200, {"Content-Type": "application/xml"}, bomb)})
        urls, _, errs = crawl.parse_sitemap(base + "/sitemap.xml", facts.DEFAULT_UA)
        self.assertEqual(urls, [])
        self.assertTrue(any("refused" in e for e in errs), errs)

    def test_a_clean_sitemap_is_read(self):
        ok = b"<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>http://x/a</loc></url></urlset>"
        _, _, base = self.serve({"/sitemap.xml": (200, {"Content-Type": "application/xml"}, ok)})
        urls, _, errs = crawl.parse_sitemap(base + "/sitemap.xml", facts.DEFAULT_UA)
        self.assertEqual(urls, ["http://x/a"])


if __name__ == "__main__":
    unittest.main()
