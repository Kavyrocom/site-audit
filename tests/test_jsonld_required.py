"""jsonld_problems: required properties missing from JSON-LD, for the types Google documents.

The rules tested here, each named by its test:
  - only REQUIRED properties are reported, never recommended ones
  - a type or a nesting we do not check is left alone (a wrong "missing" sends someone to fix good markup)
  - facts.py and crawl.py carry the result, on a real served page
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_fix_tracker import SCRIPTS  # noqa: E402

sys.path.insert(0, SCRIPTS)
import facts  # noqa: E402


def problems(*blocks):
    return facts.jsonld_problems([json.dumps(b) for b in blocks])


def kinds(ps):
    return sorted((p["type"], tuple(p["missing"])) for p in ps)


CTX = "https://schema.org"
GOOD_PRODUCT = {"@context": CTX, "@type": "Product", "name": "Monstera",
                "offers": {"@type": "Offer", "price": "24.90", "priceCurrency": "EUR"}}


class RequiredOnly(unittest.TestCase):
    def test_a_complete_product_is_clean_and_recommended_properties_are_never_asked(self):
        self.assertEqual(problems(GOOD_PRODUCT), [])                      # no image, brand, sku, availability: not required

    def test_a_product_needs_a_name_and_one_of_review_rating_or_offers(self):
        self.assertEqual(kinds(problems({"@context": CTX, "@type": "Product", "name": "X"})),
                         [("Product", ("review or aggregateRating or offers",))])
        self.assertEqual(kinds(problems({"@context": CTX, "@type": "Product", "offers": GOOD_PRODUCT["offers"]})),
                         [("Product", ("name",))])
        for one in ("review", "aggregateRating", "offers"):
            self.assertEqual(problems({"@context": CTX, "@type": "Product", "name": "X", one: {"@type": "Thing", "x": 1}}), [], one)

    def test_an_empty_value_counts_as_missing(self):
        for empty in ("", None, [], {}):
            self.assertEqual(kinds(problems({"@context": CTX, "@type": "Product", "name": empty, "offers": GOOD_PRODUCT["offers"]})),
                             [("Product", ("name",))], repr(empty))

    def test_an_offer_inside_a_product_needs_a_price_directly_or_in_its_specification(self):
        no_price = {"@context": CTX, "@type": "Product", "name": "X", "offers": {"@type": "Offer", "priceCurrency": "EUR"}}
        self.assertEqual(kinds(problems(no_price)), [("Offer", ("price or priceSpecification.price",))])
        in_spec = json.loads(json.dumps(no_price))
        in_spec["offers"]["priceSpecification"] = {"@type": "UnitPriceSpecification", "price": 12}
        self.assertEqual(problems(in_spec), [])
        listed = json.loads(json.dumps(no_price))
        listed["offers"] = [GOOD_PRODUCT["offers"], {"@type": "Offer"}]    # the second offer has nothing
        self.assertEqual(len(problems(listed)), 1)
        zero = json.loads(json.dumps(no_price))
        zero["offers"]["price"] = 0                                        # a free product is a price, not a missing one
        self.assertEqual(problems(zero), [])

    def test_an_offer_outside_a_product_is_not_checked(self):
        event = {"@context": CTX, "@type": "Event", "name": "Open day", "startDate": "2026-12-01",
                 "location": {"@type": "Place", "name": "Hall"}, "offers": {"@type": "Offer", "url": "https://x.example/t"}}
        self.assertEqual(problems(event), [])                              # Google does not ask a price here
        loose = {"@context": CTX, "@graph": [{"@type": "Offer", "url": "https://x.example/t"}]}
        self.assertEqual(problems(loose), [])                              # an offer is judged through its product only

    def test_a_video_needs_name_thumbnail_and_upload_date(self):
        self.assertEqual(kinds(problems({"@context": CTX, "@type": "VideoObject", "name": "Demo"})),
                         [("VideoObject", ("thumbnailUrl", "uploadDate"))])

    def test_an_event_needs_name_start_date_and_location(self):
        self.assertEqual(kinds(problems({"@context": CTX, "@type": "Event", "name": "Open day"})),
                         [("Event", ("startDate", "location"))])

    def test_a_local_business_needs_name_and_address_and_a_known_subtype_is_checked_too(self):
        self.assertEqual(kinds(problems({"@context": CTX, "@type": "LocalBusiness", "name": "Chez Lou"})),
                         [("LocalBusiness", ("address",))])
        self.assertEqual(kinds(problems({"@context": CTX, "@type": "Restaurant", "address": {"@type": "PostalAddress"}})),
                         [("Restaurant", ("name",))])
        self.assertEqual(problems({"@context": CTX, "@type": "Organization"}), [])      # nothing is required there
        self.assertEqual(problems({"@context": CTX, "@type": "Article"}), [])           # nor there
        self.assertEqual(problems({"@context": CTX, "@type": "SomeUnknownType"}), [])


class Breadcrumbs(unittest.TestCase):
    def crumbs(self, items):
        return {"@context": CTX, "@type": "BreadcrumbList", "itemListElement": items}

    def test_a_complete_trail_whose_last_item_has_no_url_is_clean(self):
        self.assertEqual(problems(self.crumbs([
            {"@type": "ListItem", "position": 1, "name": "Books", "item": "https://x.example/books"},
            {"@type": "ListItem", "position": 2, "name": "Award winners"}])), [])      # the page itself needs no item

    def test_a_trail_needs_two_items_and_each_item_a_position_a_name_and_a_url_except_the_last(self):
        self.assertEqual(kinds(problems(self.crumbs([{"@type": "ListItem", "position": 1, "name": "Home", "item": "https://x.example/"}]))),
                         [("BreadcrumbList", ("itemListElement with at least 2 items",))])
        ps = problems(self.crumbs([{"@type": "ListItem", "name": "Books"},
                                   {"@type": "ListItem", "position": 2}]))
        self.assertEqual(kinds(ps), [("BreadcrumbList item 1", ("position", "item")), ("BreadcrumbList item 2", ("name",))])

    def test_a_name_is_not_needed_when_the_item_is_an_object_that_has_one(self):
        self.assertEqual(problems(self.crumbs([
            {"@type": "ListItem", "position": 1, "item": {"@id": "https://x.example/a", "name": "A"}},
            {"@type": "ListItem", "position": 2, "item": {"@id": "https://x.example/b", "name": "B"}}])), [])


class Shapes(unittest.TestCase):
    def test_graph_lists_and_full_schema_urls_are_read(self):
        graph = {"@context": CTX, "@graph": [{"@type": "WebSite", "name": "S"},
                                              {"@type": "https://schema.org/Product", "name": "X"}]}
        self.assertEqual(kinds(problems(graph)), [("Product", ("review or aggregateRating or offers",))])
        self.assertEqual(len(problems([{"@context": CTX, "@type": "Product", "name": "X"}, GOOD_PRODUCT])), 1)
        self.assertEqual(len(problems({"@context": CTX, "@type": ["Product", "Thing"], "name": "X"})), 1)

    def test_a_reference_deeper_in_the_block_is_not_asked_for_what_its_entity_has(self):
        # Seen on a real shop: the variants are only urls and the rating names the product it is about.
        shop = {"@context": CTX, "@type": "ProductGroup", "name": "Runner",
                "offers": {"@type": "Offer", "price": "98", "priceCurrency": "EUR"},
                "hasVariant": [{"@type": "Product", "url": "https://x.example/v1"}, {"@type": "Product", "url": "https://x.example/v2"}],
                "aggregateRating": {"@type": "AggregateRating", "ratingValue": 4.5, "reviewCount": 12,
                                    "itemReviewed": {"@type": "Product", "name": "Runner"}}}
        self.assertEqual(problems(shop), [])
        self.assertEqual(problems({"aggregateRating": {"@type": "AggregateRating", "itemReviewed": {"@type": "Product", "name": "R"}}}), [])

    def test_a_product_in_the_graph_is_checked_and_so_is_a_breadcrumb_written_inside_its_page(self):
        page = {"@context": CTX, "@graph": [
            {"@type": "WebPage", "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://x.example/"}]}},
            {"@type": "Product", "name": "X"}]}
        self.assertEqual(kinds(problems(page)), [("BreadcrumbList", ("itemListElement with at least 2 items",)),
                                                 ("Product", ("review or aggregateRating or offers",))])

    def test_a_block_without_context_is_named_but_a_graph_with_its_context_above_is_not(self):
        self.assertEqual(kinds(problems({"@type": "Product", "name": "X", "offers": GOOD_PRODUCT["offers"]})),
                         [("Product", ("@context",))])
        self.assertEqual(problems({"@context": CTX, "@graph": [{"@type": "WebSite", "name": "S"}]}), [])

    def test_a_block_that_does_not_parse_is_left_to_the_invalid_counter(self):
        self.assertEqual(facts.jsonld_problems(['{"@type": "Product", "name": ']), [])
        self.assertEqual(facts.jsonld_types(['{"@type": "Product", "name": ']), ([], 1))


class OnAServedPage(unittest.TestCase):
    PAGE = """<!doctype html><html lang="en"><head><title>Monstera deliciosa for the living room</title>
<meta name="description" content="A large indoor plant for a bright room, delivered in three days, with a care guide on the page.">
<link rel="canonical" href="http://{host}/p/">
<script type="application/ld+json">{block}</script></head><body><h1>Monstera</h1>
<p>{words}</p><a href="/">Home</a></body></html>"""

    def serve(self, block):
        page = self.PAGE.format(host="{host}", block=json.dumps(block), words="plant " * 200)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(h):
                body = page.replace("{host}", "%s:%d" % h.server.server_address[:2]).encode()
                h.send_response(200 if h.path == "/p/" else 404)
                h.send_header("Content-Type", "text/html; charset=utf-8")
                h.send_header("Content-Length", str(len(body)))
                h.end_headers()
                h.wfile.write(body)

            def log_message(h, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d/p/" % srv.server_address[1]

    def run_tool(self, script, url, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), url, "--out", out, *extra],
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            if script == "facts.py":
                with open(out, encoding="utf-8") as fh:
                    return json.load(fh)
            with open(os.path.join(out, "summary.json"), encoding="utf-8") as fh:
                return json.load(fh)

    def test_facts_json_lists_what_is_missing(self):
        url = self.serve({"@context": CTX, "@type": "Product", "name": "Monstera"})
        f = self.run_tool("facts.py", url)
        self.assertEqual(kinds(f["structured_data"]["jsonld_missing_required"]),
                         [("Product", ("review or aggregateRating or offers",))])

    def test_facts_json_is_empty_for_good_markup(self):
        f = self.run_tool("facts.py", self.serve(GOOD_PRODUCT))
        self.assertEqual(f["structured_data"]["jsonld_missing_required"], [])

    def test_the_crawl_summary_names_the_page(self):
        url = self.serve({"@context": CTX, "@type": "Product", "name": "Monstera"})
        s = self.run_tool("crawl.py", url, "--max-pages", "3")
        found = s["issues"]["jsonld_missing_required_properties"]
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0]["url"].endswith("/p/"))
        self.assertEqual(found[0]["problems"][0]["type"], "Product")


if __name__ == "__main__":
    unittest.main()
