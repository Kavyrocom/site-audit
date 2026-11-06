#!/usr/bin/env python3
"""Find contradictions INSIDE a site: the same thing said two different ways (stdlib only).

Usage:
    python3 -I consistency.py --pages crawl/pages.jsonl [--max-pages 40] [--out DIR]
    python3 -I consistency.py --urls URL [URL ...] [--out DIR]

Reads the initial HTML of each page (text built by JavaScript is not seen: say so in the report if the site is
JavaScript-rendered). Writes DIR/consistency.json and prints a summary. It produces CANDIDATES with verbatim
snippets and their pages: you read the snippets and decide whether it is a real contradiction. It never
decides for you, and a finding built on it must quote both snippets.

What it looks for:
  price_conflicts     same service or product, different amount (VAT-only gaps and "from" prices are set aside)
  quantity_conflicts  same promise, different number: "reply within 24 hours" here, "48 hours" there
  contact_issues      several different phones, emails or postal addresses; tel:/mailto: link that does not
                      match the text shown
  name_variants       the same name spelled several ways (Studio Zorbul, StudioZorbul, studio-zorbul)
  cta_variants        the same destination offered with many different button texts
  year_claims         "since 2016" versus "since 2018", years of experience that do not add up, stale footer year
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402
from facts import DEFAULT_UA, fetch  # noqa: E402

S0, S1 = "\ue000", "\ue001"  # markers around struck-through text (old prices)
SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
BLOCK = {"p", "li", "tr", "td", "th", "dd", "dt", "div", "section", "article", "header", "footer", "main", "aside", "nav", "form",
         "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "br", "ul", "ol", "table", "figure", "figcaption", "button", "label",
         "option", "summary", "details", "hr"}
STOP = set("""le la les l un une des du de d et ou a au aux en dans pour par sur avec sans ce cet cette ces se sa son ses notre nos votre vos
leur leurs nous vous je tu il elle on ils elles que qui quoi dont est sont etre avoir plus moins tres tout tous toute toutes pas ne ni mais donc
car si y the a an of to in on for and or with from your our you we it is are be at by as this that its prix tarif tarifs tarification offre
partir des des seulement seul soit euro euros eur ht ttc hors taxes taxe toutes comprises compris mois an ans annee annuel mensuel par per month
year only starting from des des dès pack formule forfait sur devis gratuit gratuite gratuits cliquez ici voir lire suite savoir""".split())


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def stem(t):
    return t[:-1] if len(t) > 4 and t[-1] in "sx" else t


def tokens(s):
    return {stem(t) for t in re.findall(r"[a-z0-9]+", fold(s)) if t not in STOP and not t.isdigit() and len(t) > 1}


class Blocks(HTMLParser):
    """Visible text cut into blocks, each with the heading it sits under; plus links, title, struck text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.links, self.title = [], [], None
        self.skip = self.struck = 0
        self.buf, self.heads = [], [""] * 6
        self.in_title = False
        self.in_h = 0
        self.hbuf = []
        self.row = []
        self.in_cell = False
        self.a = None

    def _flush(self):
        t = " ".join("".join(self.buf).split())
        self.buf = []
        if t.replace(S0, "").replace(S1, "").strip():
            head = next((h for h in reversed(self.heads) if h), "")
            self.blocks.append({"text": t, "heading": head, "row_label": self.row[0] if self.row and self.in_cell else ""})
            if self.in_cell:
                self.row.append(t.replace(S0, "").replace(S1, ""))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP:
            self.skip += 1
            return
        if tag == "title":
            self.in_title = True
            return
        if tag in BLOCK:
            self._flush()
        if tag == "tr":
            self.row = []
        if tag in ("td", "th"):
            self.in_cell = True
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.in_h = int(tag[1])
            self.hbuf = []
        if tag in ("del", "s", "strike"):
            self.struck += 1
        if tag == "a" and a.get("href"):
            self.a = {"href": a["href"].strip(), "text": []}
        if tag == "img" and a.get("alt") and not self.skip:
            self.buf.append(" ")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "title":
            self.in_title = False
            return
        if tag in ("del", "s", "strike"):
            self.struck = max(0, self.struck - 1)
        if tag == "a" and self.a:
            self.a["text"] = " ".join("".join(self.a["text"]).split())
            self.links.append(self.a)
            self.a = None
        if tag in BLOCK:
            self._flush()
        if tag in ("td", "th"):
            self.in_cell = False
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self.in_h:
            t = " ".join("".join(self.hbuf).split())
            lv = int(tag[1])
            self.heads[lv - 1] = t
            for k in range(lv, 6):
                self.heads[k] = ""
            self.in_h = 0

    def handle_data(self, d):
        if self.in_title:
            self.title = (self.title or "") + d
            return
        if self.skip:
            return
        chunk = (S0 + d + S1) if self.struck else d
        self.buf.append(chunk)
        if self.in_h:
            self.hbuf.append(d)
        if self.a is not None:
            self.a["text"].append(d)

    def close(self):
        super().close()
        self._flush()


# ---------- prices ----------
NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
CUR = r"(?:€|eur(?:os?)?|euros?|\$|usd|£|gbp)"
PRICE = re.compile(rf"(?<![\w.,])(?:(?P<c1>[€$£])\s?(?P<n1>{NUM})|(?P<n2>{NUM})\s?(?P<c2>{CUR})(?![a-z]))", re.I)
VAT_RATIOS = (1.2, 1.1, 1.055, 1.07, 1.21, 1.196, 1.20)


def parse_amount(s):
    s = s.replace("\u00a0", " ").replace("\u202f", " ").strip()
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace(" ", "").replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = (head + "." + tail) if len(tail) <= 2 else s.replace(",", "")
        s = s.replace(" ", "")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        s = (head.replace(".", "").replace(" ", "") + "." + tail) if (len(tail) <= 2 and " " not in s) else s.replace(".", "").replace(" ", "")
    else:
        s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def qualifiers(text, a, b):
    """Qualifiers that belong to THIS amount: what follows it up to the end of the phrase, and a few words before it."""
    tail = re.split(r"[.;!?]\s|\d|\n", text[b:b + 26])[0]
    after, before = fold(tail), fold(text[max(0, a - 22):a])
    q = []
    if re.search(r"\b(a partir de|des|from|starting at|a partir)\b", before):
        q.append("from")
    if re.search(r"\bht\b|hors taxes?", after):
        q.append("HT")
    if re.search(r"\bttc\b|toutes taxes", after):
        q.append("TTC")
    if re.search(r"/\s?mois|par mois|mensuel|per month|/\s?month|monthly", after) or re.search(r"\b(mensuel|monthly)\b", before):
        q.append("month")
    elif re.search(r"/\s?an\b|par an|annuel|per year|/\s?year|yearly|/\s?ans?\b", after) or re.search(r"\b(annuel|yearly|annual)\b", before):
        q.append("year")
    return q


# a colon before a number or a currency sign ("Diagnostic : 49 EUR") is a label, not the end of a sentence
SENTENCE_BREAK = re.compile(r"(?:[.!?;](?=\s)|:(?=\s)(?!\s*(?:\d|[€$£]))|[\n|\u2022\u00b7]|\s[-\u2013]\s)")


def sentence_before(text, a):
    """The words of the sentence that holds position `a`, up to `a` (a long paragraph has many sentences: the label of a
    price is the sentence it is in, not the last seven words before it, which shift with every word added upstream)."""
    head = re.sub(f"[{S0}{S1}]", "", text[:a])
    full = re.sub(f"[{S0}{S1}]", "", text)          # the break rule looks at what FOLLOWS the colon, so it reads the whole text
    cut = 0
    for m in SENTENCE_BREAK.finditer(full):
        if m.end() > len(head):
            break
        cut = m.end()
    return head[cut:]


def local_label(text, a):
    words = re.sub(r"\s+", " ", sentence_before(text, a)).split()
    return " ".join(words[-12:])


def extract_prices(page, blocks):
    out = []
    for b in blocks:
        text = b["text"]
        for m in PRICE.finditer(text):
            raw = m.group("n1") or m.group("n2")
            amount = parse_amount(raw)
            if amount is None or amount <= 0 or amount > 10_000_000:
                continue
            cur = (m.group("c1") or m.group("c2")).lower()
            cur = "EUR" if cur in ("€", "eur", "euro", "euros") else ("USD" if cur in ("$", "usd") else "GBP")
            pre = text[:m.start()]
            struck = pre.count(S0) > pre.count(S1)
            q = qualifiers(re.sub(f"[{S0}{S1}]", "", text), m.start() - (pre.count(S0) + pre.count(S1)), m.end() - (pre.count(S0) + pre.count(S1)))
            clean = re.sub(f"[{S0}{S1}]", "", text)
            lbl = local_label(text, m.start())
            from_row = False
            if not tokens(lbl) and b["row_label"]:
                lbl, from_row = b["row_label"], True
            s = max(0, len(re.sub(f"[{S0}{S1}]", "", pre)) - 70)
            out.append({"page": page, "amount": amount, "currency": cur, "qualifiers": q, "struck": struck, "heading": b["heading"],
                        "label": lbl, "_row": from_row, "snippet": clean[s:s + 170].strip(), "_h": tokens(b["heading"]), "_l": tokens(lbl), "_near": last_term(lbl)})
    return out


def last_term(label):
    """The last meaningful word before the amount ("... nous proposons un diagnostic à 49 €" -> "diagnostic")."""
    for t in reversed(re.findall(r"[a-z0-9]+", fold(label))):
        if t not in STOP and not t.isdigit() and len(t) > 1:
            return stem(t)
    return None


GENERIC = frozenset({"montant", "total", "prix", "tarif", "price", "amount", "cout", "somme", "budget", "estime", "environ", "soit", "cost", "fee", "frais"})


def same_thing(a, b):
    """Are two price mentions about the same thing? Several different prices in ONE section are not a conflict
    (HT, TTC, instalments, options), so a shared heading alone is only enough across two pages."""
    la, lb, ha, hb = a["_l"], b["_l"], a["_h"], b["_h"]
    if a["page"] == b["page"] and a.get("_row") and b.get("_row"):
        return None  # two cells of one table row on one page are alternatives (columns), not a contradiction
    la, lb = la - GENERIC, lb - GENERIC
    long_ = lambda ts: any(len(t) >= 4 for t in ts)
    if la and la == lb and long_(la):
        return "same label"
    for x, y in ((la, hb), (lb, ha)):
        if x and x <= y and long_(x):
            return "label equals a heading elsewhere"
    sh = {t for t in la & lb if len(t) >= 4}
    if len(sh) >= 2:
        return "similar label"
    na, nb = a.get("_near"), b.get("_near")
    if a["page"] != b["page"] and na and na == nb and len(na) >= 5 and na not in GENERIC:
        return "same item named just before the amount"   # one price in a long paragraph, the other in a short line
    if ha and ha == hb and a["page"] != b["page"] and (not la or not lb or sh):
        return "same heading on two pages"
    return None


def period(p):
    return "month" if "month" in p["qualifiers"] else ("year" if "year" in p["qualifiers"] else "once")


def vat_gap(x, y):
    lo, hi = sorted((x, y))
    return lo > 0 and any(abs(hi / lo - r) < 0.012 for r in VAT_RATIOS)


def price_conflicts(prices):
    live = [p for p in prices if not p["struck"]]
    seen, uniq = set(), []
    for p in live:
        k = (p["page"], p["amount"], p["snippet"][-60:])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    groups = []
    for p in uniq:
        for g in groups:
            if g["cur"] == p["currency"] and g["per"] == period(p) and same_thing(g["members"][0], p):
                g["members"].append(p)
                break
        else:
            groups.append({"cur": p["currency"], "per": period(p), "members": [p]})
    out = []
    for g in groups:
        ms = g["members"]
        amounts = sorted({m["amount"] for m in ms})
        if len(amounts) < 2:
            continue
        by_page = {}
        for m in ms:
            by_page.setdefault(m["page"], set()).add(m["amount"])
        if len(by_page) >= 2 and len({frozenset(v) for v in by_page.values()}) == 1:
            continue                      # the same table of prices on several pages, not two prices for one thing
        # drop gaps explained by VAT or by "from" prices
        real = False
        notes = []
        for i, x in enumerate(amounts):
            for y in amounts[i + 1:]:
                lowers = [m for m in ms if m["amount"] == x]
                highers = [m for m in ms if m["amount"] == y]
                if vat_gap(x, y) and any(("HT" in m["qualifiers"]) != ("HT" in n["qualifiers"]) or ("TTC" in m["qualifiers"]) != ("TTC" in n["qualifiers"]) for m in lowers for n in highers):
                    notes.append(f"{x:g} and {y:g} may be the same price without and with VAT")
                    continue
                if any("from" in m["qualifiers"] for m in lowers) and not all("from" in n["qualifiers"] for n in highers):
                    notes.append(f"{x:g} is a 'from' price, {y:g} may be a specific option")
                    continue
                real = True
        if not real:
            continue
        why = same_thing(ms[0], next(m for m in ms if m["amount"] != ms[0]["amount"]))
        out.append({"currency": g["cur"], "period": g["per"], "amounts": amounts, "match_reason": why or "similar wording",
                    "confidence": "high" if why in ("same label", "label equals a heading elsewhere") else "medium", "notes": notes,
                    "mentions": [{k: m[k] for k in ("page", "amount", "qualifiers", "heading", "snippet")} for m in ms][:8]})
    out.sort(key=lambda c: (c["confidence"] != "high", -len(c["mentions"])))
    return out[:15]


def tax_mix(prices):
    c = Counter()
    for p in prices:
        if p["struck"]:
            continue
        c["HT" if "HT" in p["qualifiers"] else ("TTC" if "TTC" in p["qualifiers"] else "unlabeled")] += 1
    return dict(c)


# ---------- quantities ----------
UNITS = {"heure": "hour", "heures": "hour", "h": "hour", "jour": "day", "jours": "day", "j": "day", "semaine": "week", "semaines": "week",
         "mois": "month", "minute": "minute", "minutes": "minute", "min": "minute", "photo": "photo", "photos": "photo", "seance": "session",
         "seances": "session", "séance": "session", "séances": "session", "client": "client", "clients": "client", "membre": "member", "membres": "member",
         "projet": "project", "projets": "project", "an": "year", "ans": "year", "%": "percent", "hours": "hour", "days": "day", "weeks": "week",
         "months": "month", "years": "year", "customers": "client", "members": "member", "projects": "project"}
DURATION_HOURS = {"minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 730, "year": 8760}
PROMISE = ("delai", "reponse", "livraison", "diagnostic", "essai", "garantie", "rembours", "engagement", "duree", "retour", "support",
           "assistance", "disponib", "operationnel", "resultat", "rappel", "mise", "installation", "formation", "rendez")
QTY = re.compile(r"(?<![\w.,/:])(?P<n>\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)\s?(?P<u>%|[A-Za-zéèÉ]+)(?![\w])")


def extract_quantities(page, blocks):
    out = []
    for b in blocks:
        text = re.sub(f"[{S0}{S1}]", "", b["text"])
        prices = [(m.start(), m.end()) for m in PRICE.finditer(text)]
        for m in QTY.finditer(text):
            if any(a <= m.start() < e for a, e in prices):
                continue
            u = UNITS.get(m.group("u").lower())
            if not u:
                continue
            if m.group("u").lower() == "h" and re.match(r"\d", text[m.end():m.end() + 1] or ""):
                continue  # 10h30
            raw = re.sub(r"[ \u00a0\u202f]", "", m.group("n"))
            try:
                n = float(raw.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw) else raw.replace(",", "."))     # 1,200 is 1200
            except ValueError:
                continue
            tail = text[m.end():m.end() + 60]
            tail_cut = SENTENCE_BREAK.search(tail)
            ctx = sentence_before(text, m.start())[-100:] + " " + (tail[:tail_cut.start()] if tail_cut else tail)
            hours = n * DURATION_HOURS[u] if u in DURATION_HOURS else None      # 48 h and 2 days are the same promise
            out.append({"page": page, "value": n, "unit": u, "hours": hours, "snippet": text[max(0, m.start() - 50):m.end() + 40].strip(),
                        "heading": b["heading"], "_c": tokens(ctx), "_h": tokens(b["heading"])})
    return out


def quantity_conflicts(qs):
    out, seen = [], set()
    uniq = []
    for q in qs:
        k = (q["page"], q["value"], q["unit"], q["snippet"][-40:])
        if k not in seen:
            seen.add(k)
            uniq.append(q)
    groups = []
    for q in uniq:
        for g in groups:
            r = g[0]
            sh = {t for t in (r["_c"] & q["_c"]) if len(t) >= 4}
            promise = any(t.startswith(PROMISE) for t in sh)
            if (r["unit"] == q["unit"] or (r["hours"] is not None and q["hours"] is not None)) and sh and (len(sh) >= 2 or promise) and len(sh) / max(1, min(len(r["_c"]), len(q["_c"]))) >= 0.34:
                g.append(q)
                break
        else:
            groups.append([q])
    for g in groups:
        timed = all(q["hours"] is not None for q in g)
        vals = sorted({round(q["hours"], 3) if timed else q["value"] for q in g})
        if len(vals) >= 2:
            shared = sorted(set.intersection(*[q["_c"] for q in g]))[:5]
            # sibling claims on one page ("Gain: 8h" for team A, "Gain: 4h" for team B) are not contradictions:
            # across two pages, or a promise word (delay, reply, diagnostic...), is required
            if len({q["page"] for q in g}) < 2 and not any(t.startswith(PROMISE) for t in shared):
                continue
            # a page that itself lists several values ("reminder 48h before, another 24h before"; "Gain: 8h" next to
            # "Gain: 4h") is enumerating cases, not contradicting itself: if half the pages do that, it is a list
            per_page = {}
            for q in g:
                per_page.setdefault(q["page"], set()).add(round(q["hours"], 3) if timed else q["value"])
            if sum(1 for v in per_page.values() if len(v) >= 2) * 2 >= len(per_page):
                continue
            out.append({"unit": "hour (durations converted)" if timed and len({q["unit"] for q in g}) > 1 else g[0]["unit"], "values": vals, "shared_words": shared,
                        "mentions": [{k: q[k] for k in ("page", "value", "unit", "snippet", "heading")} for q in g][:8]})
    out.sort(key=lambda c: -len(c["mentions"]))
    return out[:15]


# ---------- contacts, names, ctas, years ----------
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "avif"}
PHONE = re.compile(r"(?<![\d])(?:\+|00)?\d[\d .\-()]{7,17}\d(?![\d])")
POSTAL = re.compile(r"\b(\d{5})\s+([A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]+(?:[ \-][A-ZÀ-Ý][A-Za-zÀ-ÿ'’\-]+){0,2})")


def norm_phone(s):
    d = re.sub(r"\D", "", s)
    if s.strip().startswith("+") or d.startswith("00"):
        d = d[2:] if d.startswith("00") else d
        return "+" + d
    if len(d) == 10 and d.startswith("0"):
        return "+33" + d[1:]
    return None


def collect_contacts(page, text, links, store):
    for m in EMAIL.finditer(text):
        e = m.group(0).strip(".,;").lower()
        if e.rsplit(".", 1)[-1] in IMG_EXT or "example" in e.split("@")[1]:
            continue
        store["emails"][e].add(page)
    for m in PHONE.finditer(text):
        raw = m.group(0)
        if re.search(r"(?:19|20)\d{2}\s*[-–]\s*(?:19|20)\d{2}", raw) or len(re.sub(r"\D", "", raw)) < 9:
            continue
        n = norm_phone(raw)
        if n and 10 <= len(n) <= 15:
            store["phones"][n].add(page)
    for m in POSTAL.finditer(text):
        store["postal"][f"{m.group(1)} {m.group(2).strip()}"].add(page)
    for ln in links:
        h = ln["href"]
        if h.lower().startswith("tel:"):
            n = norm_phone(urllib.parse.unquote(h[4:]))
            if n:
                store["phones"][n].add(page)
                shown = norm_phone(ln["text"]) if re.search(r"\d{2}", ln["text"]) else None
                if shown and shown != n:
                    store["mismatch"].append({"page": page, "kind": "phone", "link": n, "text": ln["text"]})
        elif h.lower().startswith("mailto:"):
            e = urllib.parse.unquote(h[7:].split("?")[0]).strip().lower()
            if e:
                store["emails"][e].add(page)
                if "@" in ln["text"] and ln["text"].strip().lower() != e:
                    store["mismatch"].append({"page": page, "kind": "email", "link": e, "text": ln["text"]})


CAP = re.compile(r"\b(?:[A-ZÀ-Ý][a-zà-ÿ]+(?:[ \-][A-ZÀ-Ý][A-Za-zà-ÿ]+)+|[A-Z][a-z]+[A-Z][A-Za-z]+)\b")


def name_variants(texts, titles, host):
    forms = defaultdict(Counter)
    for t in texts:
        for m in CAP.finditer(t):
            f = m.group(0)
            forms[re.sub(r"[\s\-_.]", "", fold(f))][f] += 1
    brand = re.sub(r"[^a-z0-9]", "", fold(host.split(".")[0] if host.count(".") else host))
    out = []
    for key, c in forms.items():
        if len(key) < 6 or len(c) < 2:
            continue
        spaced = {f for f in c if " " in f or "-" in f}
        if not (len(c) >= 2):
            continue
        out.append({"name": key, "forms": dict(c.most_common(6)), "is_brand": bool(brand) and (key == brand or brand in key)})
    # brand spelled without capitals (host-like) in text
    out.sort(key=lambda x: (not x["is_brand"], -sum(x["forms"].values())))
    return out[:12]


def cta_variants(page_links, host):
    dest = defaultdict(Counter)
    pages = defaultdict(set)
    for page, links in page_links:
        for ln in links:
            t = ln["text"].strip()
            if not t or len(t) > 40 or len(t) < 3:
                continue
            u = urllib.parse.urlparse(urllib.parse.urljoin(page, ln["href"]))
            if u.scheme not in ("http", "https") or u.netloc.lower().removeprefix("www.") != host:
                continue
            key = (u.path.rstrip("/") or "/")
            dest[key][t.lower()] += 1
            pages[key].add(page)
    out = []
    for key, c in dest.items():
        if len(c) >= 3 and key != "/" and len(pages[key]) >= 2:
            out.append({"destination": key, "distinct_texts": len(c), "texts": dict(c.most_common(8)), "pages": len(pages[key])})
    out.sort(key=lambda x: -x["distinct_texts"])
    return out[:8]


YEAR_SINCE = re.compile(r"(?:depuis|since|fond[ée]e?\s+en|cr[ée]{2}e?\s+en|founded(?:\s+in)?|n[ée]e?\s+en|ouvert(?:e)?\s+en|[ée]tabli\s+en)\s+((?:19|20)\d{2})", re.I)
YEAR_EXP = re.compile(r"(\d{1,2})\s*(?:\+\s*)?ans?\s+d['’]\s?(?:exp[ée]rience|expertise)|(\d{1,2})\s*\+?\s*years?\s+of\s+experience", re.I)
COPY = re.compile(r"(?:©|&copy;|copyright)\s*(?:copyright\s*)?((?:19|20)\d{2})(?:\s*[-–]\s*((?:19|20)\d{2}))?", re.I)


def year_claims(page_texts):
    now = datetime.now().year
    since, exp, copy = defaultdict(list), [], []
    for page, t in page_texts:
        for m in YEAR_SINCE.finditer(t):
            since[int(m.group(1))].append({"page": page, "snippet": t[max(0, m.start() - 40):m.end() + 40].strip()})
        for m in YEAR_EXP.finditer(t):
            exp.append({"page": page, "years": int(m.group(1) or m.group(2)), "snippet": t[max(0, m.start() - 40):m.end() + 30].strip()})
        for m in COPY.finditer(t):
            copy.append({"page": page, "year": int(m.group(2) or m.group(1)), "snippet": t[max(0, m.start() - 10):m.end() + 20].strip()})
    out = {"since_years": {str(k): v[:3] for k, v in sorted(since.items())}, "issues": []}
    if len(since) >= 2:
        out["issues"].append(f"'since/founded' gives different years: {sorted(since)}")
    for y, items in since.items():
        for e in exp:
            if abs((now - y) - e["years"]) > 1:
                out["issues"].append(f"'{e['years']} years of experience' ({e['page']}) does not match 'since {y}' ({items[0]['page']}): that is {now - y} years")
    if copy:
        latest = max(c["year"] for c in copy)
        if latest < now:
            out["issues"].append(f"footer copyright year is {latest}, current year is {now}")
        out["copyright_years"] = sorted({c["year"] for c in copy})
    out["experience_claims"] = exp[:6]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", help="crawl/pages.jsonl written by crawl.py")
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--delay", type=float, default=0.25, help="seconds between requests (be polite)")
    ap.add_argument("--out", default=".")
    ap.add_argument("--ua", default=DEFAULT_UA)
    a = ap.parse_args()
    urls = list(a.urls)
    if a.pages:
        if not os.path.isfile(a.pages):
            print(f"usage error: {a.pages} not found (run crawl.py first, or give --urls)", file=sys.stderr)
            return 2
        with open(a.pages, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("status") == 200 and "html" in (r.get("content_type") or "").lower():
                    urls.append(r.get("final_url") or r["url"])
    urls = list(dict.fromkeys(urls))[:a.max_pages]
    if not urls:
        print("usage error: no page to read, give --pages crawl/pages.jsonl or --urls", file=sys.stderr)
        return 2
    host = urllib.parse.urlparse(urls[0]).netloc.lower().removeprefix("www.")
    prices, qtys, page_links, page_texts, titles = [], [], [], [], []
    store = {"emails": defaultdict(set), "phones": defaultdict(set), "postal": defaultdict(set), "mismatch": []}
    read = []
    for u in urls:
        r = fetch(u, a.ua, timeout=25)
        time.sleep(a.delay)
        if r["status"] != 200 or not r["body"]:
            continue
        p = Blocks()
        p.feed(r["body"])
        p.close()
        read.append(u)
        full = "\n".join(re.sub(f"[{S0}{S1}]", "", b["text"]) for b in p.blocks)
        page_texts.append((u, full))
        if p.title:
            titles.append(" ".join(p.title.split()))
        prices += extract_prices(u, p.blocks)
        qtys += extract_quantities(u, p.blocks)
        page_links.append((u, p.links))
        collect_contacts(u, full, p.links, store)
    if not read:
        print("no page could be read", file=sys.stderr)
        return 1
    contacts = {k: {v: sorted(pg)[:6] for v, pg in sorted(store[k].items())} for k in ("emails", "phones", "postal")}
    issues = []
    if len(contacts["phones"]) > 1:
        issues.append(f"{len(contacts['phones'])} different phone numbers on the site")
    if len(contacts["emails"]) > 2:
        issues.append(f"{len(contacts['emails'])} different email addresses on the site")
    if len(contacts["postal"]) > 1:
        issues.append(f"{len(contacts['postal'])} different postal code + city pairs")
    for m in store["mismatch"][:6]:
        issues.append(f"{m['kind']} link {m['link']} but the text shows {m['text']!r} ({m['page']})")
    result = {
        "pages_read": len(read), "host": host,
        "note": "Candidates to read and judge, not verdicts. Initial HTML only (text built by JavaScript is not seen).",
        "prices_found": len([p for p in prices if not p["struck"]]), "struck_prices": [{k: p[k] for k in ("page", "amount", "snippet")} for p in prices if p["struck"]][:8],
        "tax_labels": tax_mix(prices),
        "price_conflicts": price_conflicts(prices), "quantity_conflicts": quantity_conflicts(qtys),
        "contacts": contacts, "contact_issues": issues,
        "name_variants": name_variants([t for _, t in page_texts], titles, host),
        "cta_variants": cta_variants(page_links, host), "year_claims": year_claims(page_texts),
    }
    os.makedirs(a.out, exist_ok=True)
    safenet.private_output(a.out)
    path = os.path.join(a.out, "consistency.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    r = result
    print(f"{r['pages_read']} pages read, {r['prices_found']} prices found, tax labels: {r['tax_labels'] or 'none'}")
    print(f"price conflicts: {len(r['price_conflicts'])} | quantity conflicts: {len(r['quantity_conflicts'])} | contact issues: {len(r['contact_issues'])} | "
          f"name variants: {len(r['name_variants'])} | cta variants: {len(r['cta_variants'])} | year issues: {len(r['year_claims']['issues'])}")
    for c in r["price_conflicts"][:5]:
        print(f"  price [{c['confidence']}] {c['amounts']} {c['currency']}: " + " || ".join(f"{m['page'].split('//')[-1]}: {m['snippet'][-60:]!r}" for m in c["mentions"][:3]))
    for c in r["quantity_conflicts"][:4]:
        print(f"  quantity {c['values']} {c['unit']}: " + " || ".join(f"{m['snippet'][:50]!r}" for m in c["mentions"][:3]))
    for i in r["contact_issues"][:4] + r["year_claims"]["issues"][:3]:
        print("  -", i)
    print("written:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
