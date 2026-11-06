# Speed (`performance`)

Sources: `lh/summary.json` (3 runs, median, min, max, `unstable`, `digest`), `psi.json` (Google: fresh lab run + real-user field data with its dates), `lh-site/lh-site.json` (several pages at once), `devtools/devtools.json` (network, third parties, main thread, console), `facts.json` (`assets`, `images`, `headers`).

## Lab and field are two different things

| | Lab | Field |
|---|---|---|
| What | one simulated run made now, on a mid-range phone model | real Chrome visitors |
| Freshness | **fresh**: made seconds ago | **not fresh**: 75th percentile over the trailing 28 days, refreshed daily |
| Good for | finding the cause, checking a fix right now | knowing what visitors live, and whether it gets better or worse |
| Sources | `lh_median.py`, `lh_site.py`, `psi.py` (`lab`) | `psi.py` (`crux_page`, `crux_origin`, `history_*`) |

**Never put a lab number and a field number in the same sentence without naming each.** A fix shows up in field data gradually: the window slides every day, so the number is fully clean only 28 days after the fix. Verify a fix with the lab, then watch the field.

Before you quote field data, read these in `psi.json` (the script computes them, do not guess):
1. **Scope.** `crux_page` has data = this page. `crux_page.status = no_data`, or PageSpeed `psi_field_page.scope = origin`: the numbers describe the whole site and say nothing precise about this page. Say "site-wide" every time.
2. **Period.** `period.last` and `days_since_last`: more than 10 days means stale, say so; `stale: null` means no period came with the data, freshness unknown, say that. `window_days` is 28.
3. **Disagreement.** If `interpretation` says lab and field fall on different sides of a limit, report both and explain: real visitors have the field experience, the lab shows the cause.
4. **Direction.** With `--history`, `history_page.trend` tells whether LCP, INP or CLS got `worse`, `better` or stayed `stable` over the last periods: a stable "poor" and a worsening "good" are different findings.
5. **INP** only exists in field data. If there is none, write "INP not measured" and use lab TBT only as a hint.

Without a Google API key `psi.py` still returns the lab run when Google answers (exit 0, field data marked unknown). It exits 3 and writes `status: no_key` only when nothing usable came back: write "Google data not measured" in `not_measured` and tell the person how to get a free key (Google Cloud console: enable "PageSpeed Insights API" and "Chrome UX Report API"). A site with too little traffic has no field data at all: that is normal, say it.

## Thresholds (Core Web Vitals, "good" at the 75th percentile of real users)

| Metric | Good | Needs improvement | Poor |
|---|---|---|---|
| LCP (largest content visible) | 2.5 s or less | up to 4 s | over 4 s |
| INP (reaction to a tap) | 200 ms or less | up to 500 ms | over 500 ms |
| CLS (layout shift) | 0.1 or less | up to 0.25 | over 0.25 |

Lighthouse measures a lab version: LCP, CLS, TBT (a proxy for INP), FCP, Speed Index. **INP is a field metric and is not measured by Lighthouse.** Say "lab" in the evidence.

## Which tool for what

- `lh_median.py <url> --runs 3`: the reference for the page that matters. Three runs in series, median, spread.
- `lh_site.py --site <url> --pages crawl/pages.jsonl --max 10` (Unlighthouse underneath): **screening** many pages, one run each, worst first. Out of the box Unlighthouse skips the 4x CPU slowdown that Lighthouse and PageSpeed apply on mobile (the scores come out flattering; the wrapper's own check of the settings used is the proof, not a figure from us), so the wrapper restores it and checks the settings Lighthouse really used; if `comparable` is false, do not quote the numbers. Confirm the worst two or three pages with `lh_median.py`.
- `psi.py <url> --strategy both --history`: Google's own fresh lab run **and** real-user field data with its dates. Needs a free API key. Use it for the field side and as a cross-check of the lab.
- `devtools.py <url> --after-refuse`: what the browser's network panel shows, and what loads before consent. It explains the lab numbers; it does not replace them.

## Check

1. **Stability first.** If `unstable` is true or `perf_spread` is above 10 points, the run was disturbed: say so, lower the confidence to `deduced`, and ideally rerun on an idle machine.
2. **Reading order.** LCP (`metrics.lcp_ms.median`) and the LCP element (`digest.lcp_element`): is it an image, a heading, a hero video? Is it preloaded and not lazy-loaded? `digest.lcp_breakdown_ms` tells whether the delay is server, discovery or render.
3. **Main thread.** TBT over 200 ms: look at `digest.bootup_top` and `digest.third_party_top`. Name the scripts and their cost in ms, not "too much JavaScript".
4. **Weight.** `metrics.total_bytes` (a home page above 2 MB on mobile is heavy), `digest.unused_js_top`, `digest.duplicated_or_legacy_js`, `assets.external_scripts`, `assets.inline_script_kb`.
5. **Images.** `digest.image_issues`, `images.modern_format`, `images.without_dimensions` (causes layout shift), `images.lazy` (should not be applied to the LCP image).
6. **Render blocking.** `digest.render_blocking`: CSS and sync scripts in the head.
7. **Server and cache.** `metrics.ttfb_ms`, compression, `cache-control` on static assets, CDN.
8. **Layout shift.** `metrics.cls`, and `digest.failed_audits` for fonts and unsized media.
9. **Third parties.** Tags, chat widgets, consent tools, pixels: list the heaviest with their blocking time and say which ones can be delayed until after interaction.
10. **Forced reflows, DOM size, back/forward cache:** report only if `digest` lists them with a value.
11. **DevTools view** (`devtools.json`): `requests.third_party` (how many requests and KB come from other hosts, by category: analytics, ads, session replay, chat, fonts), `requests.by_type` (what weighs), `failed_requests` (404 and blocked calls the page still makes), `mixed_content`, `console` errors, `main_thread.script_ms` and `dom_nodes`. These numbers come from one unthrottled run on the audit machine: they rank causes, they are not scores, and they do not compare with Lighthouse.

## Traps

- Never report a single score as truth: give the median and range ("80, between 78 and 81 over 3 runs").
- A "poor" lab LCP caused by a throttled CPU can be fine for real users: say the confidence level.
- Do not recommend an optimisation plugin as a fix: name the cause (which script, which image) and the action.
- An action must have an order of magnitude from the data (for example "analytics.js costs 678 ms of scripting"), not from guesses.
