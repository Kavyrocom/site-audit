# Security headers and tracking (`security`, `privacy_tracking`)

Sources: `facts.json` (`headers`, `mixed_content_http_resources`, `trackers_detected`, `consent_tool_detected`, `assets.third_party_script_hosts`) and `devtools/devtools.json` (what the browser really loads and stores before and after a consent choice).

This is a passive check of what any visitor can see. It is not a penetration test: never probe, never send payloads.

## Security (`security`)

1. **HTTPS and HSTS.** Site on HTTPS, `strict-transport-security` present (max-age at least 6 months), no mixed content.
2. **Content Security Policy.** `content-security-policy` present; if absent, say it is a hardening gap (medium or low), not an incident.
3. **Clickjacking.** `x-frame-options` or CSP `frame-ancestors`.
4. **Content sniffing.** `x-content-type-options: nosniff`.
5. **Referrer and permissions.** `referrer-policy`, `permissions-policy`.
6. **Information leaks.** `server` and `x-powered-by` with exact versions.
7. **Third-party scripts.** Each external script host is trust you give away: list the heaviest and ask if each is needed. Subresource integrity is rare on tag managers: do not demand it.
8. **Exposed files.** You only checked `robots.txt`, sitemaps and `llms.txt`. Say you did not look for sensitive files.

## Tracking and consent (`privacy_tracking`)

1. **What loads.** `trackers_detected` lists analytics and ad pixels found in the HTML. A tag manager may load more after consent: say the list is a floor.
2. **Consent tool.** (In France the CNIL exempts from consent audience measurement that meets its conditions: strictly statistical, no cross-site tracking, limited retention. Do not call such a tool a violation without looking at how it is configured.) `consent_tool_detected`: is there a banner with a "Refuse all" as visible as "Accept all"? Look at the screenshot.
3. **Before consent.** Run `python3 -I <S>/devtools.py <url> --after-refuse --out devtools`: a fresh browser, no cookie, nothing clicked. Read `before_any_interaction` (tracker hosts that fired, tracker or third-party cookies already set, Google consent signals: `gcs=G100` means "denied", `G111` means "granted") and `after_refuse.verdict`. Four outcomes: nothing fired and no cookie before consent (strength); trackers fired before any choice (risk to review); the refuse button was found but trackers or cookies appeared after refusing (refusal not respected); no banner at all while trackers fire. Google tags that send `gcs=G100` after refusal are Google's consent mode working as designed; whether such pings are acceptable is a legal question for a lawyer or DPO, not for this script. A banner inside a closed shadow root or a cross-origin iframe cannot be read: `devtools.py` says so (`consent_iframes`) instead of concluding there is none. The script never clicks accept and never fills a form. Say where the audit machine is (a banner can depend on the visitor's country) and that it is one run.
4. **Instrumentation for conversion.** The opposite finding: a page that sells without any measurement.
5. **Legal pages.** Privacy policy and legal notice linked from the page.

## Traps

- Absence of a header is a hardening recommendation, not a vulnerability. Keep severity low to medium unless the site handles payments or logins.
- Cookie values are never read or stored by `devtools.py`: names, lifetime and flags only. Do not ask for more.
- Do not state legal compliance or violation: say "risk to review with a lawyer or DPO".
