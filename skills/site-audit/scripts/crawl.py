#!/usr/bin/env python3
"""Polite same-host crawler for site-wide audits (stdlib only, read-only GET/HEAD).

Usage:
    python3 -I crawl.py <url> [--max-pages 25] [--workers 3] [--delay 0.2] [--out crawl]
                              [--check-links 60] [--check-external 0] [--ignore-robots]

Strategy: breadth-first from the start URL (links), then, if budget remains, sample the sitemap so that
every URL "template" (first path segment) gets covered. robots.txt is respected unless --ignore-robots
(use that only on a site you own).

Writes <out>/pages.jsonl (one line per page) and <out>/summary.json (coverage + site-wide issues, with the
URLs concerned). Everything in summary.json is a measurement, not an opinion: interpreting it is the
model's job (see references/technical.md and references/seo.md).
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import botwall  # noqa: E402
import robotsrules  # noqa: E402
import safenet  # noqa: E402
from facts import DEFAULT_UA, PageParser, fetch, jsonld_problems, jsonld_types  # noqa: E402

SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|avif|svg|ico|css|js|mjs|json|xml|zip|gz|mp4|mp3|mov|webm|woff2?|ttf|eot|docx?|xlsx?|pptx?|rss|atom)(\?|$)", re.I)
TRACKING = re.compile(r"^(utm_|fbclid|gclid|msclkid|mc_|_ga|ref$|ref_)", re.I)
UNVERIFIED = {401, 403, 405, 429, 999, 503}


def norm(url, base=None):
    if base:
        url = urllib.parse.urljoin(base, url)
    u = urllib.parse.urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    q = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)])
    netloc = u.netloc.lower()
    for scheme, port in (("http", ":80"), ("https", ":443")):
        if u.scheme == scheme and netloc.endswith(port):
            netloc = netloc[: -len(port)]
    return urllib.parse.urlunparse((u.scheme, netloc, u.path or "/", "", q, ""))


SITEMAP_MAX_BYTES = 52_428_800
MAX_WORKERS = 4        # parallel requests, at most
MIN_DELAY = 0.1        # seconds between two requests to the site (all workers together), at least
ROBOTS_TOKEN = "SiteAuditSkill"  # robots.txt rules for this name win over those for `*` (RFC 9309)


class Pacer:
    """One clock shared by every worker: two requests to the site are never closer than `gap` seconds, whatever the
    number of workers (a per-worker sleep would let 4 workers fire 4 requests together)."""

    def __init__(self, gap):
        self.gap = gap
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + self.gap
        if at > now:
            time.sleep(at - now)


def host_key(url):
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def parse_sitemap(url, ua, budget=5000, depth=0, seen=None):
    """Return (urls, child_sitemaps_read, errors)."""
    seen = seen if seen is not None else set()
    if url in seen or depth > 2:
        return [], 0, []
    seen.add(url)
    # A sitemap may hold 50 000 URLs (up to 50 MB once unpacked, as the sitemap standard allows) and may be a .gz file.
    r = fetch(url, ua, timeout=40, max_bytes=SITEMAP_MAX_BYTES, gunzip_file=url.lower().split("?")[0].endswith(".gz"))
    if r["status"] != 200 or not r["body"]:
        return [], 0, [f"{url} -> status {r['status']}"]
    # Remote XML is untrusted: refuse any DTD/entity declaration (XXE, billion-laughs) before parsing.
    if re.search(r"<!(DOCTYPE|ENTITY)", r["body"], re.I) or r.get("truncated"):
        return [], 0, [f"{url} -> refused (DTD/entity declaration or oversized sitemap)"]
    try:
        root = ET.fromstring(re.sub(r"<\?xml-stylesheet[^>]*\?>", "", r["body"]).encode("utf-8"))
    except ET.ParseError as e:
        return [], 0, [f"{url} -> XML parse error: {e}"]
    tag = lambda el: el.tag.split("}")[-1]
    urls, errs, kids = [], [], 0
    if tag(root) == "sitemapindex":
        for sm in root:
            loc = next((c.text.strip() for c in sm if tag(c) == "loc" and c.text), None)
            if loc and kids < 8:
                kids += 1
                u, k, e = parse_sitemap(loc, ua, budget, depth + 1, seen)
                urls += u
                errs += e
                kids += k
    else:
        for el in root:
            loc = next((c.text.strip() for c in el if tag(c) == "loc" and c.text), None)
            if loc:
                urls.append(loc)
            if len(urls) >= budget:
                break
    return urls, kids, errs


def analyse(url, ua, depth, hop_check=None):
    r = fetch(url, ua, timeout=25, hop_check=hop_check, error_body=True)
    rec = {"url": url, "final_url": r["final_url"], "status": r["status"], "redirect_hops": len(r["chain"]),
           "ttfb_ms": r["ttfb_ms"], "bytes": r["bytes"], "depth": depth, "error": r["error"],
           "content_type": r["headers"].get("content-type", ""), "x_robots_tag": r["headers"].get("x-robots-tag")}
    links = []
    wall = botwall.detect(r["status"], r["headers"], r["body"]) if not r["error"] else None
    if wall and (wall["confidence"] == "high" or r["status"] >= 400):
        rec["bot_wall"] = wall            # the answer is a protection page, not the page: it is set aside, never parsed
        return rec, links
    if wall:
        rec["bot_wall_suspect"] = wall    # wording of a verification page on a thin page: kept, and reported
    if r["status"] == 200 and "html" in rec["content_type"].lower() and r["body"]:
        p = PageParser(r["final_url"])
        p.feed(r["body"])
        title = " ".join((p.title or "").split()) or None
        desc = p.meta.get("description")
        canon = next((l.get("href") for l in p.links_head if "canonical" in l.get("rel", "").lower()), None)
        h1s = [t for lv, t in p.headings if lv == 1]
        robots = (p.meta.get("robots") or "") + " " + (rec["x_robots_tag"] or "")
        types, _ = jsonld_types(p.jsonld_raw)
        rec.update({
            "title": title, "title_len": len(title) if title else 0,
            "meta_description": desc, "meta_description_len": len(desc) if desc else 0,
            "h1_count": len(h1s), "h1_first": h1s[0][:100] if h1s else None,
            "h2_count": sum(1 for lv, _ in p.headings if lv == 2),
            "canonical": canon, "canonical_is_self": (norm(canon, r["final_url"]) == norm(r["final_url"])) if canon else None,
            "noindex": "noindex" in robots.lower(), "lang": p.html_lang,
            "words": len(re.findall(r"\w+", " ".join(p.text))),
            "images": len(p.images), "images_missing_alt": sum(1 for i in p.images if "alt" not in i),
            "has_viewport": bool(p.meta.get("viewport")), "has_og_title": "og:title" in p.meta, "has_og_image": "og:image" in p.meta,
            "jsonld_types": types, "jsonld_missing_required": jsonld_problems(p.jsonld_raw), "forms": len(p.forms),
            "scripts": len(p.scripts), "generic_anchor_links": sum(1 for a in p.links if (a["text"] or "").strip().lower() in ("click here", "here", "read more", "learn more", "en savoir plus", "cliquez ici", "lire la suite")),
        })
        for a in p.links:
            href = (a["href"] or "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                n = norm(href, r["final_url"])
                if n:
                    links.append((n, "nofollow" in a["rel"].lower()))
    return rec, links


BEHIND_ROBOTS = -1                          # status given to a link whose redirect leads where robots.txt forbids


def head_status(url, ua, hop_check=None, pacer=None):
    r = fetch(url, ua, method="HEAD", timeout=15, want_body=False, hop_check=hop_check)
    if r["status"] == 0 and "robots.txt forbids" in str(r.get("error") or ""):
        return BEHIND_ROBOTS, len(r["chain"])           # the target is behind a rule the site set: not a broken link, and not requested again
    if r["status"] in (405, 501) or r["status"] == 0:
        if pacer:
            pacer.wait()
        r = fetch(url, ua, timeout=15, want_body=False, hop_check=hop_check)
    return r["status"], len(r["chain"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--max-pages", type=int, default=25)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.2)
    ap.add_argument("--out", default="crawl")
    ap.add_argument("--check-links", type=int, default=60, help="HEAD-check up to N internal link targets not crawled")
    ap.add_argument("--check-external", type=int, default=0, help="HEAD-check up to N external links (off by default)")
    ap.add_argument("--ignore-robots", action="store_true")
    ap.add_argument("--ua", default=DEFAULT_UA)
    a = ap.parse_args()
    # A politeness floor: this is an audit of one site, not a scanner. Raise neither beyond what a small site can bear.
    a.workers = min(max(1, a.workers), MAX_WORKERS)
    a.delay = max(a.delay, MIN_DELAY)

    start = norm(safenet.start_url(a.url))
    if not start:
        sys.exit("invalid URL")
    hk = host_key(start)
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(start))
    os.makedirs(a.out, exist_ok=True)
    safenet.private_output(a.out)

    # robots + sitemap
    rb = fetch(base + "/robots.txt", a.ua, timeout=15)
    rp = robotsrules.Robots(rb["status"], rb["body"], ROBOTS_TOKEN)
    if rp.disallow_all and not a.ignore_robots:
        print(f"robots.txt answered HTTP {rb['status'] or 'no answer'}: the standard says to stay away, so nothing is crawled. "
              "If this is your own site, fix robots.txt, or use --ignore-robots on a site you own.", file=sys.stderr)
    asked_delay = rp.crawl_delay() if not a.ignore_robots else None
    if asked_delay:
        a.delay = min(max(a.delay, float(asked_delay)), 10.0)  # honour Crawl-delay, but never stall for minutes
    declared = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rb["body"]) if rb["status"] == 200 else []
    sm_urls, sm_errs, sm_read = [], [], []
    for cand in (declared or [base + "/sitemap.xml", base + "/sitemaps.xml", base + "/sitemap_index.xml"]):
        if "/feed" in cand:
            continue
        if rp.disallow_all and not a.ignore_robots:
            break                      # robots.txt is unreachable or broken: stay away, sitemaps included
        u, k, e = parse_sitemap(cand, a.ua)
        if u:
            sm_urls += u
            sm_read.append(cand)
            if declared and len(sm_read) >= 3:
                break
            if not declared:
                break
        else:
            sm_errs += e
    sm_norm = {n for n in (norm(u) for u in sm_urls) if n and host_key(n) == hk}
    sm_dupes = len(sm_urls) - len(set(sm_urls))

    pages, order = {}, []  # url -> record
    inlinks = defaultdict(set)
    nofollow_in = defaultdict(int)
    discovered_internal = {}
    skipped_robots = []
    seen = {start}
    frontier = [start]
    depth = 0
    t0 = time.time()

    pacer = Pacer(a.delay)

    def allowed(u):
        return a.ignore_robots or rp.allowed(u)

    def hop_check(u):
        # a redirect must not lead somewhere robots.txt forbids, nor to another site
        if host_key(u) != hk:
            return None
        return None if allowed(u) else "redirect to a URL that robots.txt forbids"

    def run_batch(urls, d):
        def work(u):
            pacer.wait()
            return analyse(u, a.ua, d, hop_check)
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            return list(ex.map(work, urls))

    # With a sitemap, keep ~40% of the budget to sample templates the navigation does not reach.
    bfs_cap = a.max_pages if len(sm_norm) <= a.max_pages else max(1, int(a.max_pages * 0.6))
    while frontier and len(pages) < bfs_cap:
        batch = []
        for u in frontier:
            if len(pages) + len(batch) >= bfs_cap:
                break
            if not allowed(u):
                skipped_robots.append(u)
                continue
            batch.append(u)
        nxt = []
        for rec, links in run_batch(batch, depth):
            pages[rec["url"]] = rec
            order.append(rec["url"])
            for (n, nf) in links:
                if host_key(n) != hk:
                    continue
                if SKIP_EXT.search(urllib.parse.urlparse(n).path):
                    continue
                inlinks[n].add(rec["url"])
                if nf:
                    nofollow_in[n] += 1
                discovered_internal.setdefault(n, rec["url"])
                if n not in seen:
                    seen.add(n)
                    nxt.append(n)
        frontier = nxt
        depth += 1
        if depth > 6:
            break

    # sitemap sampling: cover every template (first path segment) with the remaining budget
    sampled = []
    if len(pages) < a.max_pages and sm_norm:
        groups = defaultdict(list)
        for u in sorted(sm_norm):
            if u in pages or SKIP_EXT.search(urllib.parse.urlparse(u).path):
                continue
            seg = urllib.parse.urlparse(u).path.strip("/").split("/")[0]
            groups[seg].append(u)
        picks = []
        while len(picks) < a.max_pages - len(pages) and any(groups.values()):
            for seg in list(groups):
                if groups[seg]:
                    picks.append(groups[seg].pop(0))
                    if len(picks) >= a.max_pages - len(pages):
                        break
        picks = [u for u in picks if allowed(u)]
        for rec, links in run_batch(picks, -1):
            pages[rec["url"]] = rec
            order.append(rec["url"])
            sampled.append(rec["url"])
            for (n, nf) in links:
                if host_key(n) == hk and not SKIP_EXT.search(urllib.parse.urlparse(n).path):
                    inlinks[n].add(rec["url"])
                    discovered_internal.setdefault(n, rec["url"])

    # link check on discovered-but-not-crawled internal targets
    unchecked = [u for u in discovered_internal if u not in pages and allowed(u)][: a.check_links]
    link_status = {}
    if unchecked:
        with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
            for u, (st, hops) in zip(unchecked, ex.map(lambda x: (pacer.wait(), head_status(x, a.ua, hop_check, pacer))[1], unchecked)):
                link_status[u] = (st, hops)

    # ---- issues
    recs = [pages[u] for u in order]
    ok = [r for r in recs if r["status"] == 200 and "title" in r]
    cap = lambda lst, n=20: lst[:n]
    issues = {}
    issues["error_pages"] = cap([{"url": r["url"], "status": r["status"], "error": r["error"], "found_on": cap(sorted(inlinks.get(r["url"], [])), 3)} for r in recs if (r["status"] >= 400 or r["status"] == 0) and "robots.txt forbids" not in str(r["error"]) and not r.get("bot_wall")])
    walls = [r for r in recs if r.get("bot_wall")]
    issues["blocked_by_bot_protection"] = cap([{"url": r["url"], "status": r["status"], "vendor": r["bot_wall"]["vendor"], "kind": r["bot_wall"]["kind"]} for r in walls])
    broken = [{"url": u, "status": s, "found_on": cap(sorted(inlinks.get(u, [])), 3)} for u, (s, _) in link_status.items() if s in (404, 410) or 500 <= s < 600 and s != 503 or s == 0]
    issues["broken_internal_links_not_crawled"] = cap(broken)
    issues["links_redirecting_to_forbidden_areas"] = cap([u for u, (s, _) in link_status.items() if s == BEHIND_ROBOTS] + [r["url"] for r in recs if r["status"] == 0 and "robots.txt forbids" in str(r["error"])])
    issues["unverified_links"] = [u for u, (s, _) in link_status.items() if s in UNVERIFIED][:10]
    issues["redirect_chains_2plus_hops"] = cap([{"url": r["url"], "hops": r["redirect_hops"], "final": r["final_url"]} for r in recs if r["redirect_hops"] >= 2])
    issues["pages_reached_via_redirect"] = cap([{"url": r["url"], "final": r["final_url"]} for r in recs if r["redirect_hops"] == 1], 10)
    issues["missing_title"] = cap([r["url"] for r in ok if not r.get("title")])
    issues["title_too_long_over_65"] = cap([{"url": r["url"], "len": r["title_len"]} for r in ok if r.get("title_len", 0) > 65])
    issues["missing_meta_description"] = cap([r["url"] for r in ok if not r.get("meta_description")])
    issues["missing_h1"] = cap([r["url"] for r in ok if r.get("h1_count") == 0])
    issues["multiple_h1"] = cap([{"url": r["url"], "count": r["h1_count"]} for r in ok if r.get("h1_count", 0) > 1])
    issues["thin_content_under_150_words"] = cap([{"url": r["url"], "words": r["words"]} for r in ok if r.get("words", 0) < 150])
    issues["noindex_pages"] = cap([r["url"] for r in ok if r.get("noindex")])
    issues["canonical_missing"] = cap([r["url"] for r in ok if r.get("canonical") is None])
    issues["canonical_points_elsewhere"] = cap([{"url": r["url"], "canonical": r["canonical"]} for r in ok if r.get("canonical_is_self") is False])
    issues["images_missing_alt"] = {"total": sum(r.get("images_missing_alt", 0) for r in ok), "pages": cap([{"url": r["url"], "n": r["images_missing_alt"]} for r in ok if r.get("images_missing_alt")], 10)}
    issues["missing_lang"] = cap([r["url"] for r in ok if not r.get("lang")])
    issues["missing_viewport"] = cap([r["url"] for r in ok if not r.get("has_viewport")])
    issues["jsonld_missing_required_properties"] = cap([{"url": r["url"], "problems": r["jsonld_missing_required"][:5]} for r in ok if r.get("jsonld_missing_required")])
    issues["missing_og_image"] = cap([r["url"] for r in ok if not r.get("has_og_image")])
    issues["slow_ttfb_over_800ms"] = cap([{"url": r["url"], "ttfb_ms": r["ttfb_ms"]} for r in recs if (r["ttfb_ms"] or 0) > 800])
    t = defaultdict(list)
    m = defaultdict(list)
    for r in ok:
        if r.get("title"):
            t[r["title"]].append(r["url"])
        if r.get("meta_description"):
            m[r["meta_description"]].append(r["url"])
    issues["duplicate_titles"] = cap([{"title": k[:90], "urls": v[:5], "count": len(v)} for k, v in t.items() if len(v) > 1])
    issues["duplicate_meta_descriptions"] = cap([{"meta": k[:90], "urls": v[:5], "count": len(v)} for k, v in m.items() if len(v) > 1])
    issues["deep_pages_depth_over_3"] = cap([{"url": r["url"], "depth": r["depth"]} for r in recs if r["depth"] > 3])
    issues["single_inlink_pages"] = cap([r["url"] for r in recs if r["depth"] >= 1 and len(inlinks.get(r["url"], [])) == 1], 10)
    # trailing slash inconsistency among linked URLs
    stripped = defaultdict(set)
    for u in list(discovered_internal) + list(pages):
        stripped[u.rstrip("/")].add(u)
    issues["trailing_slash_inconsistency"] = cap([sorted(v) for v in stripped.values() if len(v) > 1], 10)
    crawled_set = set(pages)
    complete = len(pages) < a.max_pages and not frontier
    issues["sitemap"] = {
        "files_read": sm_read, "urls_total": len(sm_urls), "urls_same_host": len(sm_norm), "duplicate_urls": sm_dupes, "errors": cap(sm_errs, 5),
        "in_sitemap_but_not_linked_from_crawl": cap(sorted(u for u in sm_norm if u in crawled_set and not inlinks.get(u) and u != start), 10),
        "crawled_pages_not_in_sitemap": cap(sorted(u for u in crawled_set if sm_norm and u not in sm_norm and pages[u]["status"] == 200), 10),
        "orphan_check_reliable": bool(complete),
    }
    warnings = []
    if recs and recs[0]["status"] == 200 and recs[0].get("words", 0) < 80 and recs[0].get("scripts", 0) > 5:
        warnings.append("Start page has almost no text but many scripts: the site is probably rendered by JavaScript. This crawl only sees the initial HTML.")
    if walls:
        w0 = walls[0]["bot_wall"]
        if recs[0].get("bot_wall"):
            warnings.append(f"The start page was not audited: {botwall.one_line(w0)}. {botwall.GUIDANCE}")
        else:
            warnings.append(f"{len(walls)} page(s) answered with a bot-protection page and were set aside, not counted as pages of the site "
                            f"({botwall.one_line(w0)}). The crawl is a sample, and the protection may have started after too many requests: "
                            "say so, do not conclude about the pages that were not read.")
    suspects = [r["url"] for r in recs if r.get("bot_wall_suspect")]
    if suspects:
        warnings.append(f"{len(suspects)} page(s) carry the wording of a verification page ({suspects[0]}): look at them before you trust their figures.")
    if len(pages) >= a.max_pages:
        warnings.append(f"Page cap reached ({a.max_pages}): results describe a sample, not the whole site.")
    if skipped_robots:
        warnings.append(f"{len(skipped_robots)} URL(s) skipped because robots.txt disallows them.")
    summary = {
        "start": start, "pages_crawled": len(pages), "max_pages": a.max_pages, "cap_reached": len(pages) >= a.max_pages,
        "crawl_complete": bool(complete) and not walls, "bfs_pages": len(pages) - len(sampled), "sitemap_sampled_pages": len(sampled),
        "max_depth_reached": max([r["depth"] for r in recs] + [0]), "duration_s": round(time.time() - t0, 1),
        "status_counts": dict(Counter(r["status"] for r in recs)), "robots_skipped": len(skipped_robots), "pages_blocked_by_bot_protection": len(walls),
        "internal_links_discovered": len(discovered_internal), "links_checked_by_head": len(link_status),
        "avg_words_html_pages": round(sum(r.get("words", 0) for r in ok) / max(1, len(ok))),
        "warnings": warnings, "issues": issues,
    }
    with open(os.path.join(a.out, "pages.jsonl"), "w", encoding="utf-8") as fh:
        for u in order:
            rec = dict(pages[u])
            rec["inlinks"] = len(inlinks.get(u, []))
            rec["in_sitemap"] = (u in sm_norm) if sm_norm else None
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: summary[k] for k in ("start", "pages_crawled", "cap_reached", "crawl_complete", "bfs_pages", "sitemap_sampled_pages", "status_counts", "duration_s", "warnings")}, ensure_ascii=False, indent=2))
    print("issue counts:", {k: (len(v) if isinstance(v, list) else v.get("total", "")) for k, v in issues.items() if k != "sitemap" and v})
    if recs and recs[0].get("bot_wall"):
        print(f"the start page is not the site: {botwall.one_line(recs[0]['bot_wall'])}. {botwall.GUIDANCE}", file=sys.stderr)
        return 1
    if not pages:
        print("nothing was crawled (robots.txt, an unreachable site or a refused address): do not audit the site-wide parts from memory", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
