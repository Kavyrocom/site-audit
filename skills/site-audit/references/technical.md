# Technical and indexability (`technical`)

Sources: `facts.json` (`status`, `redirect_chain`, `site_level`, `headers`, `mixed_content_http_resources`), `crawl/summary.json` (`issues`).

## Check

1. **Reachability.** Status 200 on the target. Any 4xx or 5xx on linked pages: list them with the pages that link to them (`crawl` `error_pages`, `broken_internal_links_not_crawled`).
2. **One canonical host.** `site_level.http_to_https.ok` true in at most 1 hop. The `www` or non-`www` twin must redirect in one hop to the version that is canonical (`alt_host_*`). Several live versions = duplicate content.
3. **Redirects.** Chains of 2 or more hops (`redirect_chains_2plus_hops`) waste crawl budget and time: link straight to the final URL. Internal links that go through a redirect: fix the link.
4. **Soft 404.** `site_level.soft_404_test.status` must be 404 (410 is fine too). A 200, or a redirect to the home page, makes errors indexable.
5. **robots.txt.** Present, not blocking the whole site (`robots_disallow_all`), declares the sitemap, does not block CSS/JS needed to render. `Disallow` on a page you want ranked = critical.
6. **Sitemap.** Present, valid XML, same host, no duplicate URLs, contains only indexable 200 pages. Pages crawled but absent from the sitemap, and sitemap URLs that redirect, 404 or are `noindex`, are findings. Orphan detection (`in_sitemap_but_not_linked_from_crawl`) is only reliable when `orphan_check_reliable` is true.
7. **Indexability signals must agree.** `noindex` (meta or `x-robots-tag`), canonical pointing elsewhere (`canonical_points_elsewhere`), missing canonical on a page you want indexed. A `noindex` on a page that should rank is critical; on legal or account pages it is normal.
8. **HTML hygiene.** `doctype`, `charset`, `html_lang` present, valid JSON-LD (`invalid_jsonld_blocks` = 0), no mixed content (`mixed_content_http_resources` = 0), trailing-slash consistency.
9. **Rendering.** If the start page has almost no text but many scripts, the site is rendered by JavaScript: say the audit sees only initial HTML, and recommend server-side rendering or prerendering for content that must be indexed.
10. **Hosting signals.** TTFB (`ttfb_ms`): under 800 ms is acceptable, over 1.8 s is a clear problem. Compression (`content-encoding`), caching (`cache-control`, CDN headers).

## Traps

- Do not call a `noindex` on a thank-you, account, cart or legal page a defect, and do not recommend removing it from legal pages. The opposite is a finding: a checkout, cart or account page that is indexable or listed in the sitemap.
- A redirect from `/page` to `/page/` (one hop) is normal; the finding is inconsistent internal links.
- A page blocked by robots.txt was not crawled: you cannot judge its content, say so.
- `crawl` is a sample when `cap_reached` is true: write "among N pages crawled", never "the site has".
