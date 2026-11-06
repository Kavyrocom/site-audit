"""consistency.py: finds planted contradictions, and stays quiet on things that only look like contradictions."""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "site-audit", "scripts", "consistency.py")
YEAR = datetime.now().year

PAGES = {
    "/": """<html><head><title>Studio Zorbul | Photographe</title></head><body>
<h1>Studio Zorbul</h1>
<p>Portrait à partir de 180 euros, séance en studio.</p>
<p>Réponse sous 24 heures, sans engagement. Appelez le <a href="tel:+33199000001">01 99 00 00 01</a>.</p>
<p>Studio Zorbul existe depuis 2016. Nous avons 12 ans d'expérience.</p>
<a href="/contact">Demander un devis</a> <a href="/services">Nos prestations</a>
<footer>© 2019 StudioZorbul. Studio-Zorbul, 69000 Lyon</footer></body></html>""",
    "/services": """<html><head><title>Prestations | Studio Zorbul</title></head><body>
<h1>Nos prestations</h1>
<h2>Portrait</h2><p>Séance de 1 heure en studio ou en extérieur, 12 photos retouchées, 150 euros.</p>
<h2>Mariage</h2><p>Reportage complet, galerie privée de 400 photos, à partir de 1 200 euros HT.</p>
<h2>Abonnement</h2><p>Suivi mensuel : 99 €/mois HT. Équivalent TTC : 118,80 €/mois TTC.</p>
<h2>Pack famille</h2><p><del>250 euros</del> 200 euros, offre de lancement.</p>
<p>Réponse sous 48 heures. Studio Zorbul depuis 2018. Contact : <a href="mailto:contact@zorbul.test">contact@zorbul.test</a></p>
<a href="/contact">Prendre rendez-vous</a> <a href="/about">À propos</a></body></html>""",
    "/contact": """<html><head><title>Contact | Studio Zorbul</title></head><body>
<h1>Contact</h1><p>Réponse sous 48 heures. Tél : <a href="tel:+33199000002">01 99 00 00 01</a></p>
<p>1 rue de l'Exemple, 69000 Lyon. Autre atelier : 38000 Grenoble. Email : hello@zorbul.test</p>
<a href="/contact">Écrivez-nous</a></body></html>""",
    "/about": """<html><head><title>À propos | Studio Zorbul</title></head><body>
<h1>À propos</h1><p>Portrait de famille : 150 euros. Studio Zorbul, photographe. <a href="/contact">Réserver une séance</a></p></body></html>""",
}

CLEAN = {
    "/": """<html><head><title>Atelier Clair</title></head><body><h1>Atelier Clair</h1>
<p>Coaching individuel : 90 euros la séance. Réponse sous 24 heures.</p>
<h2>Programme</h2><p>Total dû : 790 € HT. 948 € TTC. Paiement en 4 fois : 197,50 € HT par mois.</p>
<p>Gain : 8h/semaine pour les équipes commerce. Gain : 4h/semaine pour la compta.</p>
<footer>© %d Atelier Clair, 75011 Paris. Tél 01 99 00 00 03</footer></body></html>""" % YEAR,
    "/exemple": """<html><head><title>Exemple | Atelier Clair</title></head><body><h1>Exemple</h1>
<h2>Un exemple de réassort</h2><p>Pour 120 unités, le montant estimé de 840 € est affiché au fournisseur.</p></body></html>""",
    "/comparatif": """<html><head><title>Comparatif | Atelier Clair</title></head><body><h1>Comparatif</h1><h2>Louer ou acheter un local</h2>
<table><tr><th></th><th>Louer</th><th>Acheter</th></tr>
<tr><td>Coût mensuel</td><td>20 à 200 €/mois</td><td>30 à 150 €/mois</td></tr></table></body></html>""",
    "/offre": """<html><head><title>Offre | Atelier Clair</title></head><body><h1>Offre</h1>
<p>Coaching individuel : 90 euros la séance. Réponse sous 24 heures. Tél : <a href="tel:+33199000003">01 99 00 00 03</a></p></body></html>""",
}


def serve(pages):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = pages.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def run(pages, paths):
    srv = serve(pages)
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-I", SCRIPT, "--urls", *[base + p for p in paths], "--out", tmp, "--delay", "0"],
                               capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stderr
            with open(os.path.join(tmp, "consistency.json"), encoding="utf-8") as fh:
                return json.load(fh)
    finally:
        srv.shutdown()
        srv.server_close()


class ConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = run(PAGES, list(PAGES))
        cls.clean = run(CLEAN, list(CLEAN))

    def test_price_conflict_between_home_services_and_about(self):
        hits = [c for c in self.d["price_conflicts"] if 150.0 in c["amounts"] and 180.0 in c["amounts"]]
        self.assertTrue(hits, self.d["price_conflicts"])
        c = hits[0]
        self.assertIn(150.0, c["amounts"])
        snippets = " ".join(m["snippet"] for m in c["mentions"])
        self.assertIn("180 euros", snippets)
        self.assertIn("150 euros", snippets)

    def test_things_that_are_not_conflicts_are_set_aside(self):
        flagged = {a for c in self.d["price_conflicts"] for a in c["amounts"]}
        self.assertNotIn(1200.0, flagged)                       # Mariage alone
        self.assertNotIn(118.8, flagged)                        # 99 HT vs 118,80 TTC is the VAT, not a contradiction
        self.assertNotIn(250.0, flagged)                        # struck-through old price
        self.assertTrue(any(s["amount"] == 250.0 for s in self.d["struck_prices"]))
        self.assertEqual(self.d["tax_labels"].get("HT"), 2)
        self.assertEqual(self.d["tax_labels"].get("TTC"), 1)

    def test_quantity_conflict_on_the_reply_delay(self):
        hits = [c for c in self.d["quantity_conflicts"] if c["unit"] == "hour" and 24.0 in c["values"] and 48.0 in c["values"]]
        self.assertTrue(hits, self.d["quantity_conflicts"])
        self.assertTrue(any("reponse" in w for w in hits[0]["shared_words"]))

    def test_contacts(self):
        issues = " | ".join(self.d["contact_issues"])
        self.assertIn("different postal code", issues)
        self.assertIn("phone link +33199000002", issues)        # link says ...02, text says ...01
        self.assertEqual(len(self.d["contacts"]["phones"]), 2)
        self.assertIn("hello@zorbul.test", self.d["contacts"]["emails"])

    def test_name_variants(self):
        names = [n for n in self.d["name_variants"] if n["name"] == "studiozorbul"]
        self.assertTrue(names, self.d["name_variants"])
        forms = set(names[0]["forms"])
        self.assertIn("Studio Zorbul", forms)
        self.assertIn("StudioZorbul", forms)
        self.assertIn("Studio-Zorbul", forms)

    def test_cta_variants_on_one_destination(self):
        c = [x for x in self.d["cta_variants"] if x["destination"] == "/contact"]
        self.assertTrue(c)
        self.assertGreaterEqual(c[0]["distinct_texts"], 3)

    def test_year_claims(self):
        issues = " | ".join(self.d["year_claims"]["issues"])
        self.assertIn("different years", issues)
        self.assertIn("12 years of experience", issues)
        self.assertIn("footer copyright year is 2019", issues)

    def test_consistent_site_raises_nothing(self):
        c = self.clean
        self.assertEqual(c["price_conflicts"], [])
        self.assertEqual(c["quantity_conflicts"], [])
        self.assertEqual(c["contact_issues"], [])
        self.assertEqual(c["year_claims"]["issues"], [])
        self.assertEqual(c["prices_found"], 8)                  # the same price said twice, HT/TTC/instalments in one section, an unrelated "montant estimé" elsewhere and the two cells of a table row are not conflicts


if __name__ == "__main__":
    unittest.main()
