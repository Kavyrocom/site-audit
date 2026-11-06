#!/usr/bin/env python3
"""Run Lighthouse N times IN SERIES and keep the median (stdlib only; needs the `lighthouse` CLI + Chrome).

Usage:
    python3 -I lh_median.py <url> [--runs 3] [--device mobile|desktop] [--out lh]

Why 3 runs, in series: a single run is noisy and a run made while the machine is busy can be badly
wrong (CPU contention slows the page being measured). Never launch two audits at once.

Writes <out>/run1.json ... runN.json (raw Lighthouse) and <out>/summary.json with:
  scores and metrics (median, min, max), `unstable` flag, and a `digest` of the median run:
  failed audits with their values, contrast offenders, LCP element, heaviest scripts, third parties.
"""
import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402
import netguard  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("--runs", type=int, default=3)
ap.add_argument("--device", choices=["mobile", "desktop"], default="mobile")
ap.add_argument("--out", default="lh")
ap.add_argument("--timeout", type=int, default=240)
a = ap.parse_args()
a.url = safenet.start_url(a.url)

if not shutil.which("lighthouse"):
    sys.exit("`lighthouse` not found in PATH. Install it with: npm install -g lighthouse (Chrome or Chromium required)")
os.makedirs(a.out, exist_ok=True)
safenet.private_output(a.out)

flags = "--headless=new"
if hasattr(os, "geteuid") and os.geteuid() == 0:
    flags += " --no-sandbox"  # Chrome refuses to start as root otherwise
    print("note: running as root, so Chrome starts without its sandbox. Audit sites you do not trust as a normal user.", file=sys.stderr)

proxy = netguard.GuardProxy()
flags += " " + " ".join(proxy.flags())   # every request of Lighthouse's Chrome is judged by safenet, like the other scripts

runs = []
failed_runs = 0
for i in range(1, a.runs + 1):
    path = os.path.join(a.out, f"run{i}.json")
    cmd = ["lighthouse", a.url, f"--chrome-flags={flags}", "--output=json", f"--output-path={path}", "--quiet"]
    work = netguard.short_tempdir("sa-lh-")      # Lighthouse's Chrome keeps its profile here: short path, and the marker used to stop it
    env = {**os.environ, "TMPDIR": work}
    if a.device == "desktop":
        cmd.append("--preset=desktop")
    # Lighthouse starts Chrome as a child: on a timeout, kill the whole process group, or Chrome stays behind for hours.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=a.timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        left = netguard.kill_marked(work)            # Chrome sits in a group of its own: stopped by the folder it works in
        netguard.cleanup_tempdir(work)
        print(f"run {i}: timeout (Lighthouse stopped, {left} Chrome process(es) stopped)", file=sys.stderr)
        failed_runs += 1
        continue
    netguard.cleanup_tempdir(work)
    if proc.returncode != 0 or not os.path.exists(path):
        print(f"run {i} failed: {stderr[-300:]}", file=sys.stderr)
        failed_runs += 1
        continue
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    final = d.get("finalDisplayedUrl") or d.get("finalUrl") or a.url
    why = safenet.check(final, safenet.default_allow_private(a.url))
    if why:
        os.remove(path)
        sys.exit(f"refused: the page led to {final[:160]} ({why}). Lighthouse had already loaded it, nothing from it is kept")
    au = d["audits"]
    if d.get("runtimeError") or (d.get("categories", {}).get("performance") or {}).get("score") is None:
        # Lighthouse could not measure the page (blank page, no paint, error): nothing to put in a median
        print(f"run {i}: Lighthouse could not score the page ({(d.get('runtimeError') or {}).get('code', 'no performance score')}); run ignored", file=sys.stderr)
        failed_runs += 1
        continue

    def num(k):
        return au.get(k, {}).get("numericValue")

    runs.append({
        "run": i,
        "scores": {k: (None if v.get("score") is None else round(v["score"] * 100)) for k, v in d["categories"].items()},
        "fcp_ms": num("first-contentful-paint"), "lcp_ms": num("largest-contentful-paint"),
        "tbt_ms": num("total-blocking-time"), "cls": num("cumulative-layout-shift"),
        "si_ms": num("speed-index"), "ttfb_ms": num("server-response-time"), "tti_ms": num("interactive"),
        "total_bytes": num("total-byte-weight"),
    })

if not runs:
    proxy.stop()
    sys.exit("no run produced a performance score" + (f" ({failed_runs} failed)" if failed_runs else ""))


def agg(vals):
    v = [x for x in vals if x is not None]
    return {"median": statistics.median(v), "min": min(v), "max": max(v)} if v else None


def digest(path):
    d = json.load(open(path, encoding="utf-8"))
    au = d["audits"]
    out = {"lighthouse_version": d.get("lighthouseVersion"), "form_factor": d.get("configSettings", {}).get("formFactor")}
    failed = []
    for k, v in au.items():
        if v.get("scoreDisplayMode") in ("binary", "numeric", "metricSavings") and v.get("score") is not None and v["score"] < 0.9:
            failed.append({"id": k, "title": v.get("title"), "value": v.get("displayValue"), "score": round(v["score"], 2)})
    out["failed_audits"] = sorted(failed, key=lambda x: x["score"])[:40]

    def items(k, n=6, keys=()):
        """First n items of an audit, scalar fields only (optionally restricted to `keys`)."""
        det = au.get(k, {}).get("details", {})
        rows = []
        for it in (det.get("items") or [])[:n]:
            if not isinstance(it, dict):
                continue
            row = {}
            for kk, val in it.items():
                if keys and kk not in keys:
                    continue
                if isinstance(val, dict):
                    val = val.get("selector") or val.get("url") or val.get("snippet")
                if isinstance(val, (str, int, float)) and val != "":
                    row[kk] = val[:140] if isinstance(val, str) else (round(val, 1) if isinstance(val, float) else val)
            if row:
                rows.append(row)
        return rows

    def first(*ids, n=6):
        for k in ids:
            r = items(k, n)
            if r:
                return r
        return []
    out["contrast_offenders"] = [
        {"selector": (it.get("node") or {}).get("selector"), "explanation": ((it.get("node") or {}).get("explanation") or "")[:200]}
        for it in au.get("color-contrast", {}).get("details", {}).get("items", [])[:8]]
    out["bootup_top"] = items("bootup-time", 6, ("url", "total", "scripting"))
    out["unused_js_top"] = items("unused-javascript", 6, ("url", "wastedBytes"))
    out["third_party_top"] = first("third-party-summary", "third-parties-insight")
    out["render_blocking"] = first("render-blocking-resources", "render-blocking-insight")
    out["duplicated_or_legacy_js"] = first("duplicated-javascript-insight", "legacy-javascript-insight", n=4)
    out["forced_reflow"] = first("forced-reflow-insight", n=3)
    out["dom_size"] = first("dom-size-insight", n=3)
    out["image_issues"] = {k: au.get(k, {}).get("displayValue") for k in ("uses-optimized-images", "modern-image-formats", "uses-responsive-images", "offscreen-images") if au.get(k, {}).get("score") not in (None, 1)}
    lcp = au.get("largest-contentful-paint-element", {}).get("details", {})
    if lcp.get("items"):
        try:
            node = lcp["items"][0]["items"][0]["node"]
            out["lcp_element"] = {"selector": node.get("selector"), "snippet": (node.get("snippet") or "")[:160]}
        except Exception:
            pass
    bd = au.get("lcp-breakdown-insight", {}).get("details", {})
    if bd.get("items"):
        try:
            out["lcp_breakdown_ms"] = {x.get("label"): round(x.get("duration", 0)) for x in bd["items"][0].get("items", bd["items"]) if isinstance(x, dict) and "duration" in x}
        except Exception:
            pass
    out["bfcache_failures"] = [x.get("reason") for x in au.get("bf-cache", {}).get("details", {}).get("items", [])][:6] if isinstance(au.get("bf-cache", {}).get("details", {}).get("items"), list) else None
    return out


perf = [r["scores"]["performance"] for r in runs]
median_run = min(runs, key=lambda r: abs(r["scores"]["performance"] - statistics.median(perf)))
summary = {
    "url": a.url, "device": a.device, "runs_ok": len(runs), "runs": runs,
    "scores": {c: agg([r["scores"][c] for r in runs if c in r["scores"]]) for c in runs[0]["scores"]},
    "metrics": {m: agg([r[m] for r in runs]) for m in ("fcp_ms", "lcp_ms", "tbt_ms", "cls", "si_ms", "ttfb_ms", "tti_ms", "total_bytes")},
    "perf_spread": max(perf) - min(perf),
    "unstable": (max(perf) - min(perf)) > 10 or len(runs) < 2,
    "digest_source_run": median_run["run"],
    "digest": digest(os.path.join(a.out, f"run{median_run['run']}.json")),
    "runs_failed": failed_runs,
    "blocked_by_proxy": proxy.refused[:20],
    "guard_connections": proxy.served,
    "note": "INP is a field metric and is not measured by Lighthouse; TBT is only a lab proxy.",
}
with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as fh:
    json.dump(summary, fh, ensure_ascii=False, indent=2)
proxy.stop()
print(json.dumps({k: summary[k] for k in ("url", "device", "runs_ok", "scores", "metrics", "perf_spread", "unstable")}, ensure_ascii=False, indent=2))
