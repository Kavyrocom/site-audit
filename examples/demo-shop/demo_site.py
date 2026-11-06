#!/usr/bin/env python3
"""A fictional online shop ("Maison Quokka", houseplants) with planted, ordinary defects: the site audited in report.md.

    FICTIVE_WP_USER=audit FICTIVE_WP_APP_PASSWORD="<any text, for example six groups of four letters>" python3 -I demo_site.py [port]

Then ask your agent to audit http://127.0.0.1:18940/ with the site-audit skill (it is a local test site served over
plain HTTP, so HTTPS, HSTS, PageSpeed Insights and CrUX cannot be measured).

Everything here is invented: the brand, the people, the prices, the address, the phone numbers (02 61 91 xx xx is a
range reserved for fiction) and the e-mail addresses (.example). The server listens on 127.0.0.1 only. It also serves a
tiny fake WordPress REST API that accepts the credentials given in the environment, so the inside view of the skill can be
exercised for real, read-only.
"""
import base64
import http.server
import json
import os
import socketserver
import struct
import sys
import zlib

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18940
USER = os.environ.get("FICTIVE_WP_USER", "audit")
PASSWORD = os.environ.get("FICTIVE_WP_APP_PASSWORD", "")
BRAND = "Maison Quokka"

NAV = """<header><a href="/" class="logo">Maison Quokka</a><nav><a href="/produits/">Plantes</a> <a href="/nos-conseils/">Conseils</a> <a href="/livraison/">Livraison</a> <a href="/a-propos/">À propos</a> <a href="/contact/">Contact</a></nav>
<a class="icon" href="/panier/"><img src="/assets/cart.png" width="20" height="20"></a></header>"""
FOOT = """<footer><p>© 2024 Maison Quokka, 8 impasse du Kiwi, 44000 Nantes. Tél. 02 61 91 31 41. <a href="/mentions-legales/">Mentions légales</a></p></footer>"""
BANNER = """<div id="cookie-banner" role="dialog" aria-label="Cookies" class="cookie-banner"><p>Nous mesurons l'audience de ce site uniquement si tu l'acceptes.</p>
<div><button type="button" class="accept">Tout accepter</button> <button type="button" class="refuse">Tout refuser</button></div></div>"""


def page(path, title, body, desc=None, noindex=False):
    d = f'<meta name="description" content="{desc}">' if desc else ""
    r = '<meta name="robots" content="noindex,follow">' if noindex else ""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>{d}{r}<link rel="canonical" href="http://127.0.0.1:{PORT}{path}">
<link rel="stylesheet" href="/assets/theme.css"><script src="/assets/theme.js"></script></head><body>{NAV}<main>{body}</main>{FOOT}{BANNER}</body></html>"""


def product(path, name, price, shown, alt, h1=True, jsonld_price=None):
    ld = json.dumps({"@context": "https://schema.org", "@type": "Product", "name": name,
                     "offers": {"@type": "Offer", "priceCurrency": "EUR", "price": jsonld_price or price}})
    head = f"<h1>{name}</h1>" if h1 else f"<h2>{name}</h2>"
    big = "/assets/big.png" if path.endswith("monstera/") else "/assets/p1.png"
    return page(path, "Plante d'intérieur livrée chez toi | Maison Quokka" if path.rsplit("/", 2)[-2] in ("monstera", "pothos", "ficus") else f"{name} | Maison Quokka",
                f'<img src="{big}" width="600" height="600"{alt}>{head}<p class="price">{shown} €</p><p class="muted">Prix TTC, hors frais de livraison.</p>'
                f'<p>Une plante facile, livrée en pot de 14 cm avec sa fiche d\'entretien.</p><a class="btn" href="/panier/?add={path.split("/")[-2]}">Ajouter au panier</a>'
                f'<script type="application/ld+json">{ld}</script>', desc=f"{name}, plante d'intérieur livrée chez toi.")


PAGES = {}
PAGES["/"] = page("/", "Maison Quokka | Plantes d'intérieur livrées chez toi",
    """<img src="/assets/hero.png" width="1200" height="700" alt="Salon avec plusieurs plantes vertes">
<h1>Des plantes d'intérieur qui arrivent en pleine forme</h1>
<p>Livraison offerte dès 60 € d'achat, expédition sous 48 h. Chaque plante part avec sa fiche d'entretien.</p>
<a class="btn" href="/produits/">Voir les plantes</a>
<section><h2>Nos best-sellers</h2><ul class="cards">
<li><a href="/produits/monstera/"><img src="/assets/p1.png" width="300" height="300">Monstera</a></li>
<li><a href="/produits/pothos/"><img src="/assets/p2.png" width="300" height="300" alt="Pothos en suspension">Pothos</a></li>
<li><a href="/produits/ficus/"><img src="/assets/p3.png" width="300" height="300">Ficus</a></li></ul></section>
<section><h2>Ils nous font confiance</h2><p>2 340 avis clients, une note moyenne de 4,7 sur 5.</p></section>""",
    desc="Plantes d'intérieur livrées chez toi, avec leur fiche d'entretien. Maison Quokka.")
PAGES["/produits/"] = page("/produits/", "Plantes d'intérieur | Maison Quokka",
    '<h1>Toutes les plantes</h1><ul><li><a href="/produits/monstera/">Monstera</a></li><li><a href="/produits/pothos/">Pothos</a></li><li><a href="/produits/ficus/">Ficus</a></li><li><a href="/produits/calathea/">Calathea</a></li></ul>')
PAGES["/produits/monstera/"] = product("/produits/monstera/", "Monstera", "24.90", "26,90", "", jsonld_price="24.90")
PAGES["/produits/pothos/"] = product("/produits/pothos/", "Pothos", "14.90", "14,90", ' alt="Pothos en suspension"')
PAGES["/produits/ficus/"] = product("/produits/ficus/", "Ficus", "39.00", "39,00", "", h1=False)
PAGES["/produits/calathea/"] = product("/produits/calathea/", "Calathea", "19.90", "19,90", ' alt="Calathea à feuilles rayées"')
PAGES["/nos-conseils/"] = page("/nos-conseils/", "Conseils d'entretien | Maison Quokka",
    '<h1>Conseils d\'entretien</h1><ul><li><a href="/nos-conseils/arrosage/">Arroser sans noyer ses plantes</a></li></ul>', desc="Nos conseils d'entretien.", noindex=True)
PAGES["/nos-conseils/arrosage/"] = page("/nos-conseils/arrosage/",
    "Arroser ses plantes d'intérieur sans les noyer : la méthode simple en quatre gestes pour toute l'année | Maison Quokka",
    "<h1>Arroser sans noyer ses plantes</h1>" + "<p>" + ("Touche la terre sur deux centimètres : si elle est sèche, arrose. " * 14) + "</p>")
PAGES["/livraison/"] = page("/livraison/", "Livraison et retours | Maison Quokka",
    "<h1>Livraison</h1><p>Livraison offerte à partir de 75 € d'achat, sinon 5,90 €.</p><p>Délai de livraison : 5 jours ouvrés après la commande.</p>"
    "<p>Retour possible sous 14 jours si la plante arrive abîmée.</p>", desc="Frais, délais et retours.")
PAGES["/a-propos/"] = page("/a-propos/", "À propos | Maison Quokka",
    "<h1>À propos</h1><p>Maison Quokka existe depuis 2021. Plus de 1 800 clients nous font confiance. Notre fondatrice, Inès, choisit chaque plante elle-même.</p>",
    desc="Qui est derrière Maison Quokka.")
PAGES["/contact/"] = page("/contact/", "Contact | Maison Quokka",
    '<h1>Contact</h1><p>Écris-nous : <a href="mailto:contact@maison-quokka.example">contact@maison-quokka.example</a> ou appelle le 02 61 91 31 42.</p>'
    '<form action="/contact/envoi/" method="post"><input type="text" name="n" placeholder="Ton nom"><input type="text" name="e" placeholder="Ton e-mail"><textarea name="m" placeholder="Ton message"></textarea><button>Envoyer</button></form>',
    desc="Contacter Maison Quokka.")
PAGES["/mentions-legales/"] = page("/mentions-legales/", "Mentions légales | Maison Quokka",
    "<h1>Mentions légales</h1><p>Maison Quokka, 8 impasse du Kiwi, 44000 Nantes.</p>", desc="Mentions légales.")
PAGES["/panier/"] = page("/panier/", "Panier | Maison Quokka", "<h1>Panier</h1><p>Ton panier est vide.</p>", desc="Ton panier.")
SOFT404 = page("/", "Maison Quokka", "<h1>Cette page n'existe pas</h1><p>Retourne à l'accueil.</p>")

SITEMAP_URLS = list(PAGES) + ["/ancienne-collection/"]
SITEMAP = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
    f"<url><loc>http://127.0.0.1:{PORT}{u}</loc></url>" for u in SITEMAP_URLS) + "</urlset>"
ROBOTS = (f"User-agent: *\nAllow: /\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\nDisallow: /*?orderby=\n"
          f"Sitemap: http://127.0.0.1:{PORT}/sitemap.xml\n")

CSS = ("body{font-family:Arial,sans-serif;margin:0;color:#222}header,footer{padding:16px}main{padding:16px}.btn{display:inline-block;background:#2f6f4f;color:#fff;padding:12px 16px;border-radius:6px;text-decoration:none}"
       "nav a{margin:0 8px}img{max-width:100%;height:auto}.muted{color:#aaa;font-size:13px}.cards{display:flex;gap:8px;list-style:none;padding:0}.icon{padding:4px}"
       ".cookie-banner{position:fixed;left:0;right:0;bottom:0;background:#fff;border-top:1px solid #ccc;padding:10px 16px;z-index:9999}.cookie-banner button{min-height:40px;padding:6px 14px}\n" + "/* padding */\n" * 1500)
THEME_JS = ("document.addEventListener('DOMContentLoaded',function(){var b=document.getElementById('cookie-banner');if(!b)return;"
            "b.querySelectorAll('button').forEach(function(x){x.addEventListener('click',function(){b.style.display='none';"
            "if(x.className==='accept'){var s=document.createElement('script');s.src='/assets/analytics.js';document.head.appendChild(s)}})})});\n"
            + "".join(f"function t{i}(a,b){{var s=0;for(var k=0;k<a;k++){{s+=k*b+{i}}}return s}}\n" for i in range(3500)))
ANALYTICS_JS = "window.dataLayer=window.dataLayer||[];\n"


def png_noise(w, h):
    raw = bytearray()
    for _ in range(h):
        raw += b"\x00" + os.urandom(w * 3)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(raw), 1)) + chunk(b"IEND", b"")


ASSETS = {"/assets/theme.css": ("text/css", CSS.encode()), "/assets/theme.js": ("application/javascript", THEME_JS.encode()),
          "/assets/analytics.js": ("application/javascript", ANALYTICS_JS.encode()),
          "/assets/hero.png": ("image/png", png_noise(1200, 700)), "/assets/big.png": ("image/png", png_noise(900, 900)),
          "/assets/p1.png": ("image/png", png_noise(300, 300)), "/assets/p2.png": ("image/png", png_noise(300, 300)),
          "/assets/p3.png": ("image/png", png_noise(300, 300)), "/assets/cart.png": ("image/png", png_noise(20, 20))}

PLUGINS = [("quokka-shop", "active", "8.4.1"), ("quokka-cache", "active", "3.1.0"), ("quokka-seo", "active", "21.2.0"), ("quokka-forms", "active", "5.9.3"),
           ("quokka-mailer", "active", "2.0.7"), ("quokka-backup", "active", "4.6.2"), ("quokka-images", "active", "1.9.0"), ("quokka-security", "active", "7.3.5"),
           ("quokka-reviews", "active", "2.2.2"), ("quokka-shipping", "active", "3.5.0"), ("quokka-slider", "inactive", "6.1.4"), ("quokka-shop-legacy", "inactive", "1.0.3")]


def plugins():
    return [{"plugin": f"{s}/{s}", "status": st, "name": s, "version": v} for s, st, v in PLUGINS]


class H(http.server.BaseHTTPRequestHandler):
    server_version = "nginx"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def authed(self):
        h = self.headers.get("Authorization", "")
        if not PASSWORD or not h.startswith("Basic "):
            return False
        try:
            u, p = base64.b64decode(h[6:]).decode().split(":", 1)
        except Exception:
            return False
        return u == USER and p == PASSWORD

    def send(self, code, ctype, body, extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/wp-json"):
            if p in ("/wp-json", "/wp-json/"):
                return self.send(200, "application/json", json.dumps({"name": BRAND, "namespaces": ["wp/v2", "quokka/v1"]}))
            if not self.authed():
                return self.send(401, "application/json", json.dumps({"code": "rest_not_logged_in"}))
            if p == "/wp-json/wp/v2/users/me":
                return self.send(200, "application/json", json.dumps({"roles": ["administrator"], "capabilities": {"edit_pages": True, "edit_published_pages": True, "activate_plugins": True, "manage_options": True}}))
            if p == "/wp-json/wp/v2/plugins":
                return self.send(200, "application/json", json.dumps(plugins()))
            return self.send(404, "application/json", json.dumps({"code": "rest_no_route"}))
        hdr = {"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"}
        if p in PAGES:
            return self.send(200, "text/html; charset=utf-8", PAGES[p], hdr)
        if p in ASSETS:
            ct, body = ASSETS[p]
            return self.send(200, ct, body, {"Cache-Control": "max-age=300"})
        if p == "/sitemap.xml":
            return self.send(200, "application/xml", SITEMAP)
        if p == "/robots.txt":
            return self.send(200, "text/plain", ROBOTS)
        self.send(200, "text/html; charset=utf-8", SOFT404, hdr)  # soft 404: a missing page answers 200


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"fictional site on http://127.0.0.1:{PORT}/ (WordPress REST user {USER!r}, password {'set' if PASSWORD else 'NOT set'})", flush=True)
    S(("127.0.0.1", PORT), H).serve_forever()
