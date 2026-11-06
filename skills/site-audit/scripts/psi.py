#!/usr/bin/env python3
"""Google's own speed data for a URL: PageSpeed Insights (lab) + Chrome UX Report (real users), with freshness.

Usage:
    python3 -I psi.py <url> [--strategy mobile|desktop|both] [--key-env NAME] [--history] [--out dir]

Wants a free Google API key in the environment (name it with --key-env, or set PAGESPEED_API_KEY, PSI_API_KEY
or GOOGLE_API_KEY). Create it at https://console.cloud.google.com/apis/credentials and enable "PageSpeed
Insights API" and "Chrome UX Report API". Without a key the script still tries PageSpeed Insights once, but Google's
shared quota is almost always exhausted (HTTP 429) and the CrUX API answers 403: the script then writes psi.json
with status "no_key" and exits 3, and the report must say "Google data not measured". When the shared quota does
answer, the lab run is returned (status "ok", exit 0) and the field data stays "not measured".
Exit codes: 0 everything asked was returned; 3 no key and nothing returned; 4 something is missing (status
"partial": some calls failed, or "failed": none worked, or "quota_exceeded"), read `errors` before quoting a number.
The key is read from the environment only. It is never printed or written.

Two kinds of numbers, never mix them in one sentence:
  lab    one FRESH simulated run made by Google when you call (Lighthouse, mid-range phone, Google data center).
         Good to find causes and to check a fix right away. One run: it moves a little between calls.
  field  real Chrome users, 75th percentile over the trailing 28 days (CrUX, refreshed daily). It is an aggregate
         of the past, not a fresh measurement: a fix only shows up gradually, over up to 28 days.
For field data this script reports what you must check before trusting it:
  scope     "page" (this URL had enough traffic) or "origin" (not enough: the numbers are for the whole site and
            say nothing precise about this page)
  period    first and last day of the 28-day window, and how many days old the last day is (stale if > 10)
  history   with --history: the weekly p75 series, to see whether it is getting better or worse
PageSpeed Insights returns its own copy of the field data and the CrUX API returns the source; both are kept in
psi.json under their own names (this script does not compare them), and the report says which one a number comes from.
Every call has a 90 s limit for the whole answer and the run has 300 s in all.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402

PSI = os.environ.get("SITEAUDIT_PSI_ENDPOINT", "https://www.googleapis.com/pagespeedonline/v5/runPagespeed")
CRUX = os.environ.get("SITEAUDIT_CRUX_ENDPOINT", "https://chromeuxreport.googleapis.com/v1/records:queryRecord")
CRUX_HIST = os.environ.get("SITEAUDIT_CRUX_HISTORY_ENDPOINT", "https://chromeuxreport.googleapis.com/v1/records:queryHistoryRecord")
KEY_ENVS = ("PAGESPEED_API_KEY", "PSI_API_KEY", "GOOGLE_API_KEY")
STALE_DAYS = 10

THRESH = {  # good upper bound, poor lower bound
    "lcp_ms": (2500, 4000), "inp_ms": (200, 500), "cls": (0.1, 0.25), "fcp_ms": (1800, 3000), "ttfb_ms": (800, 1800)}
CRUX_NAMES = {"largest_contentful_paint": "lcp_ms", "interaction_to_next_paint": "inp_ms", "cumulative_layout_shift": "cls",
              "first_contentful_paint": "fcp_ms", "experimental_time_to_first_byte": "ttfb_ms"}
PSI_NAMES = {"LARGEST_CONTENTFUL_PAINT_MS": "lcp_ms", "INTERACTION_TO_NEXT_PAINT": "inp_ms", "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
             "FIRST_CONTENTFUL_PAINT_MS": "fcp_ms", "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb_ms"}


def rate(metric, v):
    if v is None or metric not in THRESH:
        return None
    good, poor = THRESH[metric]
    return "good" if v <= good else ("poor" if v > poor else "needs improvement")


def cwv_pass(m):
    core = [rate("lcp_ms", (m.get("lcp_ms") or {}).get("p75")), rate("cls", (m.get("cls") or {}).get("p75"))]
    inp = (m.get("inp_ms") or {}).get("p75")
    if inp is not None:
        core.append(rate("inp_ms", inp))
    if any(x is None for x in core):
        return None
    return all(x == "good" for x in core)


def parse_dt(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_psi(resp, now=None):
    now = now or datetime.now(timezone.utc)
    lr = resp.get("lighthouseResult") or {}
    au = lr.get("audits") or {}
    nv = lambda k: (round(au[k]["numericValue"], 3) if k in au and au[k].get("numericValue") is not None else None)
    cfg = lr.get("configSettings") or {}
    ft = parse_dt(lr.get("fetchTime"))
    lab = {
        "fetch_time": lr.get("fetchTime"), "age_seconds": round((now - ft).total_seconds()) if ft else None,
        "lighthouse_version": lr.get("lighthouseVersion"), "form_factor": cfg.get("formFactor") or (cfg.get("emulatedFormFactor")),
        "scores": {k: (None if v.get("score") is None else round(v["score"] * 100)) for k, v in (lr.get("categories") or {}).items()},
        "metrics": {"fcp_ms": nv("first-contentful-paint"), "lcp_ms": nv("largest-contentful-paint"), "tbt_ms": nv("total-blocking-time"),
                    "cls": nv("cumulative-layout-shift"), "speed_index_ms": nv("speed-index"), "tti_ms": nv("interactive"), "server_response_ms": nv("server-response-time")},
        "warnings": (lr.get("runWarnings") or [])[:5],
        "environment": {"user_agent": (lr.get("environment") or {}).get("hostUserAgent"), "benchmark_index": (lr.get("environment") or {}).get("benchmarkIndex")},
    }
    opp = []
    for k, a in au.items():
        d = a.get("details") or {}
        if d.get("type") == "opportunity" and (d.get("overallSavingsMs") or 0) > 100:
            opp.append({"id": k, "title": a.get("title"), "savings_ms": round(d["overallSavingsMs"]), "savings_kb": round((d.get("overallSavingsBytes") or 0) / 1024)})
    lab["opportunities"] = sorted(opp, key=lambda o: -o["savings_ms"])[:8]
    return lab, psi_field(resp.get("loadingExperience")), psi_field(resp.get("originLoadingExperience"), origin=True)


def psi_field(le, origin=False):
    if not le or not le.get("metrics"):
        return {"scope": "none", "metrics": {}}
    out = {}
    for k, v in le["metrics"].items():
        name = PSI_NAMES.get(k)
        if not name:
            continue
        p = v.get("percentile")
        p = (p / 100.0) if (name == "cls" and p is not None) else p     # PSI gives CLS multiplied by 100
        out[name] = {"p75": p, "rating": rate(name, p), "psi_category": v.get("category")}
    return {"scope": "origin" if (origin or le.get("origin_fallback")) else "page", "origin_fallback": bool(le.get("origin_fallback")),
            "overall": le.get("overall_category"), "metrics": out, "core_web_vitals_pass": cwv_pass(out)}


def ymd(d):
    try:
        return date(int(d["year"]), int(d["month"]), int(d["day"]))
    except (KeyError, TypeError, ValueError):
        return None


def parse_crux(resp, today=None, scope="page"):
    today = today or datetime.now(timezone.utc).date()
    rec = resp.get("record") or {}
    cp = rec.get("collectionPeriod") or {}
    first, last = ymd(cp.get("firstDate")), ymd(cp.get("lastDate"))
    out = {}
    for k, v in (rec.get("metrics") or {}).items():
        name = CRUX_NAMES.get(k)
        if not name:
            continue
        p = (v.get("percentiles") or {}).get("p75")
        try:
            p = float(p) if p is not None else None
        except (TypeError, ValueError):
            p = None
        dens = [round(h.get("density", 0), 3) for h in (v.get("histogram") or [])]
        out[name] = {"p75": p, "rating": rate(name, p), "good_share": dens[0] if dens else None, "poor_share": dens[-1] if len(dens) == 3 else None}
    age = (today - last).days if last else None
    return {"scope": scope, "form_factor": (rec.get("key") or {}).get("formFactor"), "metrics": out, "core_web_vitals_pass": cwv_pass(out),
            "period": {"first": str(first) if first else None, "last": str(last) if last else None,
                       "window_days": ((last - first).days + 1) if first and last else None, "days_since_last": age,
                       "stale": (age > STALE_DAYS) if age is not None else None}}      # None: no period came with the data, freshness unknown


def parse_history(resp):
    rec = resp.get("record") or {}
    periods = rec.get("collectionPeriods") or []
    out = {"periods": len(periods), "last_period_end": str(ymd((periods[-1] or {}).get("lastDate"))) if periods else None, "trend": {}}
    for k, v in (rec.get("metrics") or {}).items():
        name = CRUX_NAMES.get(k)
        series = (v.get("percentilesTimeseries") or {}).get("p75s") or []
        vals = []
        for x in series:
            try:
                vals.append(float(x))
            except (TypeError, ValueError):
                vals.append(None)
        real = [x for x in vals if x is not None]
        if not name or len(real) < 2:
            continue
        latest, ago = real[-1], real[max(0, len(real) - 5)]
        ch = round(100 * (latest - ago) / ago, 1) if ago else None
        out["trend"][name] = {"latest_p75": latest, "p75_four_periods_earlier": ago, "change_pct": ch,
                              "direction": None if ch is None else ("worse" if ch > 5 else ("better" if ch < -5 else "stable")), "series": [x for x in vals][-12:]}
    return out


CALL_LIMIT = 90        # seconds for one call, whole answer included (a server that drips bytes cannot hold it longer)
TOTAL_LIMIT = 300      # seconds for all the calls of one run
_T0 = time.monotonic()


def _as_dict(text):
    try:
        j = json.loads(text)
    except ValueError:
        return None
    return j if isinstance(j, dict) else None


def http(url, body=None, timeout=CALL_LIMIT):
    left = TOTAL_LIMIT - (time.monotonic() - _T0)
    if left <= 0:
        return 0, {"error": {"message": f"the {TOTAL_LIMIT} s budget of this run is used up"}}
    timeout = max(1, min(timeout, left))
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST" if data else "GET")
    box = {}

    def run():
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                box["r"] = (r.status, r.read(5_000_000).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            try:
                box["r"] = (e.code, e.read(1_000_000).decode("utf-8", "replace"))
            except OSError:
                box["r"] = (e.code, "")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            box["e"] = f"network error: {type(e).__name__}"
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return 0, {"error": {"message": f"no complete answer after {int(timeout)} s"}}
    if "e" in box:
        return 0, {"error": {"message": box["e"]}}
    status, text = box["r"]
    j = _as_dict(text)
    if j is None:
        return (status if status != 200 else 0), {"error": {"message": "the answer is not a JSON object"}}
    return status, j


def err_text(status, j, key):
    m = ((j.get("error") or {}).get("message") or "")
    m = m.replace(key, "***") if key else m
    return f"HTTP {status}: {m[:160]}" if status else m[:160]


def interpretation(res):
    notes = ["lab = one fresh simulated run made by Google at the time of the call; use it to find causes and to verify a fix straight away.",
             "field = real Chrome users, 75th percentile over the trailing 28 days: an aggregate of the past, not a fresh measurement; a fix shows up gradually over up to 28 days."]
    for strat, s in res["strategies"].items():
        cp, co = s.get("crux_page"), s.get("crux_origin")
        if cp and cp.get("status") == "no_data":
            notes.append(f"[{strat}] this page has too little traffic for its own field data: any field number you quote is for the whole origin, not this page.")
        elif not cp and s.get("psi_field_page", {}).get("scope") == "origin":
            notes.append(f"[{strat}] PageSpeed Insights fell back to origin-level field data: it does not describe this page.")
        for label, c in (("page", cp), ("origin", co)):
            if c and c.get("period") and c["period"].get("stale") is None and c.get("metrics"):
                notes.append(f"[{strat}] the {label} field data came without its period: its freshness is unknown, say so.")
            if c and c.get("period") and c["period"].get("stale"):
                notes.append(f"[{strat}] the {label} field data ends {c['period']['days_since_last']} days ago: it is stale, say so.")
        lab, c = s.get("lab") or {}, cp if (cp and cp.get("metrics")) else (co if co and co.get("metrics") else None)
        if c and lab.get("metrics", {}).get("lcp_ms") is not None and c["metrics"].get("lcp_ms", {}).get("p75") is not None:
            l, f = lab["metrics"]["lcp_ms"], c["metrics"]["lcp_ms"]["p75"]
            if (l <= 2500) != (f <= 2500):
                notes.append(f"[{strat}] lab LCP {round(l)} ms and field LCP p75 {round(f)} ms fall on different sides of the 2.5 s limit: report both, say which one real visitors live, and do not average them.")
    return notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--strategy", choices=("mobile", "desktop", "both"), default="mobile")
    ap.add_argument("--key-env", help="name of the environment variable holding the API key")
    ap.add_argument("--history", action="store_true", help="also read the CrUX History API (weekly p75 series)")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    url = safenet.start_url(a.url)
    os.makedirs(a.out, exist_ok=True)
    safenet.private_output(a.out)
    path = os.path.join(a.out, "psi.json")
    names = ([a.key_env] if a.key_env else []) + list(KEY_ENVS)
    key = None
    for n in names:
        v = os.environ.get(n)
        if v:
            key = v
            break
    res = {"url": url, "strategies": {}, "status": "ok", "interpretation": []}
    no_key_msg = (f"No Google API key in the environment (looked for {', '.join(names)}). Without a key the shared quota is almost always exhausted (HTTP 429) and the Chrome UX Report API refuses the call (403). "
                  "Create a free key (APIs: PageSpeed Insights API and Chrome UX Report API), put it in the environment, name it with --key-env. Report: Google data not measured.")
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url))
    for strat in (["mobile", "desktop"] if a.strategy == "both" else [a.strategy]):
        s = {"errors": []}
        q = [("url", url), ("strategy", strat)] + ([("key", key)] if key else []) + [("category", c) for c in ("performance", "accessibility", "best-practices", "seo")]
        st, j = http(PSI + "?" + urllib.parse.urlencode(q))
        if st == 200:
            s["lab"], s["psi_field_page"], s["psi_field_origin"] = parse_psi(j)
        else:
            s["errors"].append("PageSpeed Insights " + err_text(st, j, key))
            if st == 429:
                res["status"] = "quota_exceeded"
        if not key:
            res["strategies"][strat] = s
            continue
        ff = "PHONE" if strat == "mobile" else "DESKTOP"
        for scope, body in (("page", {"url": url, "formFactor": ff}), ("origin", {"origin": origin, "formFactor": ff})):
            st, j = http(f"{CRUX}?key={urllib.parse.quote(key)}", body)
            if st == 200:
                s["crux_" + scope] = parse_crux(j, scope=scope)
            elif st == 404:
                s["crux_" + scope] = {"status": "no_data", "scope": scope, "message": "Chrome UX Report has no data for this " + ("URL (too little traffic)" if scope == "page" else "origin")}
            else:
                s["errors"].append(f"CrUX {scope} " + err_text(st, j, key))
            if a.history:
                st, j = http(f"{CRUX_HIST}?key={urllib.parse.quote(key)}", body)
                if st == 200:
                    s["history_" + scope] = parse_history(j)
                elif st != 404:
                    s["errors"].append(f"CrUX history {scope} " + err_text(st, j, key))
        res["strategies"][strat] = s
    if not key:
        res["key_missing"] = no_key_msg
        if not any(x.get("lab") for x in res["strategies"].values()):
            res.update(status="no_key", message=no_key_msg)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(res, fh, ensure_ascii=False, indent=2)
            print(no_key_msg, file=sys.stderr)
            return 3
    # An error is never "ok": with a key, a failed call means the report would be missing data it believes it has.
    problems = [e for x in res["strategies"].values() for e in x["errors"]]
    got_data = any(x.get("lab") or any((x.get(k) or {}).get("metrics") for k in ("crux_page", "crux_origin")) for x in res["strategies"].values())
    if problems and res["status"] == "ok":
        res["status"] = "partial" if got_data else "failed"
    elif res["status"] == "quota_exceeded" and not got_data:
        res["status"] = "failed" if key else "quota_exceeded"
    elif res["status"] == "quota_exceeded" and any(x.get("lab") for x in res["strategies"].values()):
        res["status"] = "partial"                  # one strategy answered, the other hit the quota: read `errors`
    res["interpretation"] = interpretation(res)
    if not key:
        res["interpretation"].append("No API key: the Chrome UX Report API was not called, so the field period and its freshness are unknown. Use the field numbers PageSpeed Insights returned with that reserve.")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    for strat, s in res["strategies"].items():
        lab = s.get("lab") or {}
        m = lab.get("metrics", {})
        print(f"[{strat}] lab (fresh run {lab.get('fetch_time')}): scores {lab.get('scores')}, LCP {m.get('lcp_ms')} ms, TBT {m.get('tbt_ms')} ms, CLS {m.get('cls')}")
        for label in ("crux_page", "crux_origin"):
            c = s.get(label)
            if not c:
                continue
            if c.get("status") == "no_data":
                print(f"[{strat}] field {c['scope']}: no data")
                continue
            p = c["period"]
            fm = c["metrics"]
            print(f"[{strat}] field {c['scope']} p75 over {p['window_days']} days ending {p['last']} ({p['days_since_last']} days ago{', STALE' if p['stale'] else ''}): "
                  f"LCP {(fm.get('lcp_ms') or {}).get('p75')} ms, INP {(fm.get('inp_ms') or {}).get('p75')} ms, CLS {(fm.get('cls') or {}).get('p75')}, CWV pass: {c['core_web_vitals_pass']}")
        for e in s["errors"]:
            print(f"[{strat}] problem: {e}")
    for n in res["interpretation"][2:]:
        print("-", n)
    print("written:", path)
    return 0 if res["status"] == "ok" else 4


if __name__ == "__main__":
    sys.exit(main())
