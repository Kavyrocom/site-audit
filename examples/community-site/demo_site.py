#!/usr/bin/env python3
"""A fictional community site ("Cercle Pixel") with planted, realistic defects: the site audited in report.md.

    FICTIVE_WP_USER=audit FICTIVE_WP_APP_PASSWORD="<any text, for example six groups of four letters>" python3 -I demo_site.py [port]

Then ask your agent to audit http://127.0.0.1:18940/ with the site-audit skill (it is a local test site served over
plain HTTP, so HTTPS, HSTS, PageSpeed Insights and CrUX cannot be measured).

Everything here is invented: the brand, the people, the prices, the phone numbers (01 99 00 xx xx is the reserved
fiction range) and the e-mail addresses (.example). It also serves a tiny fake WordPress REST API that accepts the
credentials given in the environment, so the inside view of the skill can be exercised for real, read-only.
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

NAV = """<header><a href="/" class="logo">Cercle Pixel</a><nav><a href="/communaute-gratuite/">Communaut&eacute;</a> <a href="/formules/">Formules</a> <a href="/blog/">Blog</a> <a href="/a-propos/">&Agrave; propos</a> <a href="/contact/">Contact</a></nav>
<a class="cta" href="/communaute-gratuite/?ref={source}">Rejoindre</a></header>"""
FOOT = """<footer><p>&copy; 2022 Cercle Pixel, 1 rue de l'Exemple, 69000 Lyon. T&eacute;l. 01 99 00 00 21. <a href="/mentions-legales/">Mentions l&eacute;gales</a> <a href="/espace-membres/">Espace membres</a></p></footer>"""
BANNER = """<div id="cookie-banner" role="dialog" aria-label="Cookies" class="cookie-banner"><p>Nous utilisons des cookies pour mesurer l'audience et vous proposer des contenus adapt&eacute;s. En continuant, vous acceptez leur utilisation. Vous pouvez en savoir plus dans notre politique de confidentialit&eacute;.</p>
<div><button type="button" class="accept">Tout accepter</button> <button type="button" class="refuse">Refuser</button> <button type="button">Personnaliser</button></div></div>"""
SCRIPTS = """<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}gtag('consent','default',{analytics_storage:'granted',ad_storage:'denied'});</script>
<script async src="/assets/gtm-loader.js"></script><script src="/assets/vendor-bundle.js"></script><script src="/assets/theme.js"></script>"""


def page(title, body, h1=True, desc=None, extra_head="", noindex=False):
    d = f'<meta name="description" content="{desc}">' if desc else ""
    r = '<meta name="robots" content="noindex,follow">' if noindex else ""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>{d}{r}<link rel="canonical" href="http://127.0.0.1:{PORT}/">
<link rel="stylesheet" href="/assets/theme.css">{extra_head}{SCRIPTS}</head><body class="home">{NAV}<main>{body}</main>{FOOT}{BANNER}</body></html>"""


PAGES = {}
PAGES["/"] = page("Cercle Pixel | La communaut&eacute; pour apprendre la retouche photo avec des ateliers, des corrections de portfolio et des d&eacute;fis chaque semaine",
    """<img src="/assets/hero.png" width="1200" height="600" alt="">
<h1>Apprends la retouche photo avec une communaut&eacute; qui r&eacute;pond</h1>
<h1>Cercle Pixel</h1>
<p>Ateliers en direct, corrections de portfolio et d&eacute;fis hebdomadaires. Acc&egrave;s gratuit pour d&eacute;marrer, formule compl&egrave;te &agrave; 29 &euro; par mois.</p>
<a class="btn" href="/communaute-gratuite/?ref={source}">Commencer gratuitement</a>
<section><h2>Ce que tu y trouves</h2><p>Plus de 1 200 membres, un atelier en direct chaque semaine, des corrections de portfolio par des professionnels.</p></section>
<section><h2>Ils en parlent</h2><p>Des membres de toute la francophonie progressent chaque mois.</p></section>""", desc="Rejoins Cercle Pixel, la communaut&eacute; francophone de retouche photo.")
PAGES["/communaute-gratuite/"] = page("Rejoindre la communaut&eacute; gratuite | Cercle Pixel",
    """<h1>Commence gratuitement</h1><p>Cr&eacute;e ton compte en 30 secondes et acc&egrave;de &agrave; un premier atelier.</p>
<form action="/inscription/" method="post"><label>E-mail <input type="text" name="e"></label><label>Pr&eacute;nom <input type="text" name="p"></label><button>Je m'inscris</button></form>""",
    desc="Cr&eacute;e ton compte gratuit et suis un premier atelier de retouche photo.")
PAGES["/formules/"] = page("Formules et tarifs | Cercle Pixel",
    """<h1>Formules</h1><div class="plans"><div><h2>Gratuit</h2><p>0 &euro;</p></div><div><h2>Complet</h2><p>39 &euro; par mois, ateliers illimit&eacute;s</p><a class="btn" href="/paiement/">Choisir</a></div></div>
<p>Satisfait ou rembours&eacute; sous 14 jours. Sans engagement.</p>""", desc="Les formules de Cercle Pixel.")
PAGES["/a-propos/"] = page("&Agrave; propos | Cercle Pixel",
    """<h1>&Agrave; propos</h1><p>Cercle Pixel existe depuis 2019. Notre fondatrice, Camille, retouche des photos depuis plus de 9 ans.</p>
<p>Nous accompagnons plus de 1 500 membres.</p><img src="/assets/team.png" width="800" height="400">""", desc="Qui est derri&egrave;re Cercle Pixel.")
PAGES["/blog/"] = page("Blog | Cercle Pixel", "<h1>Blog</h1><ul>" + "".join(f'<li><a href="/blog/article-{i}/">Article {i}</a></li>' for i in range(1, 7)) + "</ul>", desc="Les articles du blog.")
TITLES = [
    "Comment corriger les ombres d'un portrait en lumi&egrave;re naturelle sans perdre la texture de la peau | Cercle Pixel",
    "Les trois r&eacute;glages de courbes que je refais sur chaque photo de paysage | Cercle Pixel",
    "Retouche photo : 7 erreurs qui trahissent un travail d'amateur | Cercle Pixel",
    "Pr&eacute;parer un portfolio de retouche photo qui d&eacute;croche des clients en 2025 sans le moindre budget publicitaire | Cercle Pixel",
    "Pourquoi tes couleurs paraissent ternes une fois export&eacute;es | Cercle Pixel",
    "Calibrer son &eacute;cran pour la retouche photo : le guide complet des sondes, des logiciels et des r&eacute;glages | Cercle Pixel",
]
for i, t in enumerate(TITLES, 1):
    body = f"<h1>Article {i}</h1>" + "<p>" + ("Un paragraphe pour montrer comment un texte plus long est structur&eacute;. " * 12) + "</p>"
    if i == 3:
        body += '<img src="/assets/team.png" width="800" height="400"><p><a href="http://127.0.0.1:%d/blog/">Lien en http</a></p><img src="http://example.invalid/pixel.png" width="10" height="10">' % PORT
    PAGES[f"/blog/article-{i}/"] = page(t, body, desc=None if i in (2, 5) else "Un article du blog Cercle Pixel.")
PAGES["/contact/"] = page("Contact | Cercle Pixel", "<h1>Contact</h1><p>&Eacute;cris-nous : <a href=\"mailto:contact@cercle-pixel.example\">contact@cercle-pixel.example</a> ou appelle le 01 99 00 00 22.</p>", desc="Contacter Cercle Pixel.")
PAGES["/mentions-legales/"] = page("Mentions l&eacute;gales | Cercle Pixel", "<h1>Mentions l&eacute;gales</h1><p>Cercle Pixel, 1 rue de l'Exemple, 69000 Lyon.</p>", desc="Mentions l&eacute;gales.")
PAGES["/espace-membres/"] = page("Espace membres | Cercle Pixel", "<p>Connecte-toi pour retrouver tes ateliers.</p>", h1=False, noindex=True)
PAGES["/paiement/"] = page("Paiement | Cercle Pixel", "<h1>Paiement</h1><p>Formule compl&egrave;te, 39 &euro; par mois.</p>", desc="Paiement s&eacute;curis&eacute;.")
SOFT404 = page("Cercle Pixel", "<h1>Cette page n'existe pas</h1><p>Retourne &agrave; l'accueil.</p>")

SITEMAP_URLS = [p for p in PAGES if p != "/espace-membres/"] + ["/espace-membres/", "/ancienne-page/"]
SITEMAP = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(
    f"<url><loc>http://127.0.0.1:{PORT}{u}</loc></url>" for u in SITEMAP_URLS) + "</urlset>"
ROBOTS = f"User-agent: *\nAllow: /\nDisallow: /wp-admin/\nSitemap: http://127.0.0.1:{PORT}/sitemap.xml\n"

CSS = ("body{font-family:Arial,sans-serif;margin:0;color:#222}header,footer{padding:16px}main{padding:16px}.btn,.cta{display:inline-block;background:#7fd6c2;color:#fff;padding:10px 14px;border-radius:6px;text-decoration:none}"
       "nav a{margin:0 8px}img{max-width:100%;height:auto}.cookie-banner{position:fixed;left:0;right:0;bottom:0;background:#111;color:#fff;padding:20px;min-height:38vh;z-index:9999}"
       ".cookie-banner button{min-height:24px;padding:4px 8px;font-size:12px}\n" + "/* padding */\n" * 2500)
THEME_JS = "document.addEventListener('DOMContentLoaded',function(){var b=document.getElementById('cookie-banner');if(!b)return;b.querySelectorAll('button').forEach(function(x){x.addEventListener('click',function(){b.style.display='none'})})});"
VENDOR_JS = "/* vendor bundle */\n" + "".join(f"function f{i}(a,b){{var s=0;for(var k=0;k<a;k++){{s+=k*b+{i}}}return s}}\n" for i in range(9000))
GTM_JS = "window.dataLayer=window.dataLayer||[];/* loader */\n" + "".join(f"function g{i}(){{return {i}}}\n" for i in range(4000))


def png_noise(w, h):
    raw = bytearray()
    for _ in range(h):
        raw += b"\x00" + os.urandom(w * 3)
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(raw), 1)) + chunk(b"IEND", b"")


ASSETS = {"/assets/theme.css": ("text/css", CSS.encode()), "/assets/theme.js": ("application/javascript", THEME_JS.encode()),
          "/assets/vendor-bundle.js": ("application/javascript", VENDOR_JS.encode()), "/assets/gtm-loader.js": ("application/javascript", GTM_JS.encode()),
          "/assets/hero.png": ("image/png", png_noise(1200, 600)), "/assets/team.png": ("image/png", png_noise(800, 400))}

PLUGINS = ["pixel-cache", "pixel-seo", "pixel-security", "pixel-security-lite", "pixel-forms", "pixel-community", "pixel-shop", "pixel-mailer", "pixel-consent",
           "pixel-backup", "pixel-slider", "pixel-snippets", "pixel-redirects", "pixel-images", "pixel-analytics"]


def plugins():
    out = []
    for i in range(31):
        slug = PLUGINS[i % len(PLUGINS)] + ("" if i < len(PLUGINS) else f"-{i}")
        out.append({"plugin": f"{slug}/{slug}", "status": "inactive" if i in (6, 19) else "active", "name": slug, "version": f"{1 + i % 4}.{i % 9}.{i % 5}"})
    return out


class H(http.server.BaseHTTPRequestHandler):
    server_version = "nginx"
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
                return self.send(200, "application/json", json.dumps({"name": "Cercle Pixel", "namespaces": ["wp/v2", "pixel/v1"]}))
            if not self.authed():
                return self.send(401, "application/json", json.dumps({"code": "rest_not_logged_in"}))
            if p == "/wp-json/wp/v2/users/me":
                return self.send(200, "application/json", json.dumps({"roles": ["administrator"], "capabilities": {"edit_pages": True, "edit_published_pages": True, "activate_plugins": True, "manage_options": True}}))
            if p == "/wp-json/wp/v2/plugins":
                return self.send(200, "application/json", json.dumps(plugins()))
            return self.send(404, "application/json", json.dumps({"code": "rest_no_route"}))
        hdr = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
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
