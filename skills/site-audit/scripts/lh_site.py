#!/usr/bin/env python3
"""Lighthouse on SEVERAL pages in one go, through Unlighthouse (stdlib wrapper; needs `unlighthouse-ci` and Chrome).

Usage:
    python3 -I lh_site.py --site https://example.com --pages crawl/pages.jsonl [--max 10] [--out lh-site]
    python3 -I lh_site.py --site https://example.com --paths /,/pricing/,/contact/ [--desktop] [--out lh-site]

Install the tool once: npm install -g unlighthouse
Why a wrapper: out of the box Unlighthouse runs Lighthouse WITHOUT the 4x CPU slowdown that Lighthouse and PageSpeed
Insights apply on mobile, which flatters the mobile scores (the gap was large on the page we tried, but that run is not
kept in this repository, so no figure is quoted). This script writes a config that restores the slowdown (mobile), runs the pages one at a time, then READS the
settings Lighthouse actually used and refuses to call the result comparable when they are not the expected ones.

Use it to SCREEN the pages of a site (which ones are slow), one run each. Then confirm the worst two or three with
lh_median.py (3 runs in series, median): one run per page moves by a few points and a busy machine lies.

Writes <out>/lh-site.json (pages sorted worst first, `comparable`, the settings used) and prints a table.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import facts  # noqa: E402
import safenet  # noqa: E402
import netguard  # noqa: E402
from render import find_chrome  # noqa: E402

EXPECT = {"mobile": {"cpu": 4, "method": "simulate"}, "desktop": {"cpu": 1, "method": "simulate"}}


def paths_from_pages(jsonl, site, limit):
    host = urllib.parse.urlparse(site).netloc.lower().removeprefix("www.")
    rows = []
    with open(jsonl, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("status") != 200 or "html" not in (r.get("content_type") or "").lower() or r.get("noindex"):
                continue
            u = urllib.parse.urlparse(r.get("final_url") or r["url"])
            if u.netloc.lower().removeprefix("www.") != host or u.query:
                continue
            rows.append((r.get("depth", 9), u.path or "/"))
    seen, out = set(), []
    for _, p in sorted(rows):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True)
    ap.add_argument("--pages", help="crawl/pages.jsonl from crawl.py")
    ap.add_argument("--paths", help="comma separated paths, e.g. /,/pricing/")
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--desktop", action="store_true")
    ap.add_argument("--out", default="lh-site")
    a = ap.parse_args()
    site = safenet.start_url(a.site)
    binary = shutil.which("unlighthouse-ci")
    if not binary:
        print("unlighthouse-ci not found. Install it once with: npm install -g unlighthouse. Fall back on lh_median.py for the main page.", file=sys.stderr)
        return 3
    paths = [p.strip() for p in a.paths.split(",") if p.strip()] if a.paths else (paths_from_pages(a.pages, site, a.max) if a.pages else ["/"])
    paths = [p if p.startswith("/") else "/" + p for p in paths][:a.max]
    if not paths:
        sys.exit("no page to test")
    dev = "desktop" if a.desktop else "mobile"
    os.makedirs(a.out, exist_ok=True)
    safenet.private_output(a.out)
    cfg = os.path.join(a.out, "unlighthouse.config.mjs")
    lh = "" if a.desktop else ", lighthouseOptions: { throttling: { cpuSlowdownMultiplier: 4 } }"
    proxy = netguard.GuardProxy()   # the browser Unlighthouse starts goes through the same filter as the other scripts
    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(f"export default {{ site: {json.dumps(site)}, urls: {json.dumps(paths)}, scanner: {{ samples: 1, throttle: true }}{lh}, "
                 f"puppeteerOptions: {{ args: {json.dumps(proxy.flags())} }}, "
                 "puppeteerClusterOptions: { maxConcurrency: 1 } }\n")
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("note: running as root, so the browser Unlighthouse starts may run without its sandbox. Audit sites you do not trust as a normal user.", file=sys.stderr)
    chrome = find_chrome()
    if chrome and not os.environ.get("CHROME_PATH"):
        os.putenv("CHROME_PATH", chrome)   # inherited by the child process; Unlighthouse reads it
    res = os.path.join(a.out, "ul")
    shutil.rmtree(res, ignore_errors=True)
    # Unlighthouse fetches each page itself (its Node process, outside its browser) before it tests it, and that fetch
    # cannot go through the proxy (Node would also send puppeteer's own local DevTools calls there). So each page is
    # checked here just before: one that redirects off the site or to a refused address is left out. A site that answers
    # differently the second time is not covered (said in the README).
    kept = []
    for p in paths:
        r0 = facts.fetch(site.rstrip("/") + p, facts.DEFAULT_UA, timeout=20, want_body=False, hop_check=lambda u: None if safenet.host_of(u) == safenet.host_of(site) else "redirect to another site")
        if r0["error"] and ("refused" in r0["error"] or "another site" in r0["error"]):
            print(f"{p}: left out ({r0['error'][:120]})", file=sys.stderr)
            continue
        kept.append(p)
    if not kept:
        print("no page left to test", file=sys.stderr)
        proxy.stop()
        return 2
    if kept != paths:
        paths = kept
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(f"export default {{ site: {json.dumps(site)}, urls: {json.dumps(paths)}, scanner: {{ samples: 1, throttle: true }}{lh}, "
                     f"puppeteerOptions: {{ args: {json.dumps(proxy.flags())} }}, "
                     "puppeteerClusterOptions: { maxConcurrency: 1 } }\n")
    work = netguard.short_tempdir("sa-ul-")
    env = {**os.environ, "TMPDIR": work}
    try:
        r = subprocess.run([binary, "--config-file", os.path.abspath(cfg), "--desktop" if a.desktop else "--mobile", "--no-cache", "--reporter", "jsonExpanded",
                            "--output-path", os.path.abspath(res)], cwd=a.out, capture_output=True, text=True, timeout=1200, env=env)
    except subprocess.TimeoutExpired:
        netguard.cleanup_tempdir(work)
        proxy.stop()
        print("unlighthouse did not finish within 20 minutes (its Chrome was stopped): lower the number of pages (--paths) and run again", file=sys.stderr)
        return 2
    netguard.cleanup_tempdir(work)
    ci = os.path.join(res, "ci-result.json")
    if r.returncode != 0 or not os.path.exists(ci):
        print("unlighthouse failed:", (r.stderr or r.stdout)[-300:], file=sys.stderr)
        return 2
    with open(ci, encoding="utf-8") as fh:
        data = json.load(fh)
    used = []
    for f in glob.glob(os.path.join(res, "reports", "**", "lighthouse.json"), recursive=True) + glob.glob(os.path.join(res, "reports", "lighthouse.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                lhr = json.load(fh)
            c = lhr.get("configSettings", {})
            final = lhr.get("finalDisplayedUrl") or lhr.get("finalUrl")
            why = safenet.check(final, safenet.default_allow_private(site)) if final else None
            if why:
                print(f"refused: a page led to {final[:160]} ({why}). Unlighthouse had already loaded it, nothing from it is kept", file=sys.stderr)
                shutil.rmtree(res, ignore_errors=True)
                return 2
            used.append({"cpu": (c.get("throttling") or {}).get("cpuSlowdownMultiplier"), "method": c.get("throttlingMethod"), "form_factor": c.get("formFactor")})
        except (OSError, ValueError):
            pass
    want = EXPECT[dev]
    bad = [u for u in used if u["cpu"] != want["cpu"] or u["method"] != want["method"] or (u["form_factor"] and u["form_factor"] != dev)]
    comparable = bool(used) and not bad
    pages = []
    for rt in data.get("routes", []):
        cat = {k: (None if v.get("score") is None else round(v["score"] * 100)) for k, v in (rt.get("categories") or {}).items()}
        m = {k: (v or {}).get("numericValue") for k, v in (rt.get("metrics") or {}).items()}
        pages.append({"path": rt.get("path"), "performance": cat.get("performance"), "accessibility": cat.get("accessibility"), "best_practices": cat.get("best-practices"), "seo": cat.get("seo"),
                      "lcp_ms": round(m["largest-contentful-paint"]) if m.get("largest-contentful-paint") is not None else None,
                      "tbt_ms": round(m["total-blocking-time"]) if m.get("total-blocking-time") is not None else None,
                      "cls": round(m["cumulative-layout-shift"], 3) if m.get("cumulative-layout-shift") is not None else None})
    pages.sort(key=lambda p: (p["performance"] is None, p["performance"] or 0))
    result = {"site": site, "device": dev, "runs_per_page": 1, "comparable": comparable,
              "settings_used": used[0] if used else None, "settings_expected": want,
              "note": ("Settings match Lighthouse and PageSpeed Insights defaults for " + dev + ". " if comparable else
                       "WARNING: the settings Lighthouse used are NOT the " + dev + " defaults (expected CPU slowdown " + str(want["cpu"]) + "x). Do not compare these numbers with Lighthouse or PageSpeed Insights and do not quote them. ")
              + "One run per page: confirm the worst pages with lh_median.py.",
              "pages": pages, "guard_connections": proxy.served, "blocked_by_proxy": proxy.refused[:20]}
    proxy.stop()
    with open(os.path.join(a.out, "lh-site.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"{len(pages)} pages, {dev}, CPU slowdown {result['settings_used'] and result['settings_used']['cpu']}x, comparable with Lighthouse: {comparable}")
    for p in pages:
        perf = "n/a" if p["performance"] is None else p["performance"]
        print(f"  perf {perf:>3}  LCP {p['lcp_ms']} ms  TBT {p['tbt_ms']} ms  CLS {p['cls']}  {p['path']}")
    if not comparable:
        print(result["note"], file=sys.stderr)
    print("written:", os.path.join(a.out, "lh-site.json"))
    return 0 if comparable else 4


if __name__ == "__main__":
    sys.exit(main())
