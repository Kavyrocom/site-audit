# SEO on-page (`seo`)

Sources: `facts.json` (head, headings, links, images, structured data), `crawl/pages.jsonl` and `crawl/summary.json`.

## Check

1. **Title.** One per page, unique, descriptive, main topic first, brand last. About 30 to 60 characters displays fully on most results (`title_len`); beyond about 65 it is often truncated. The real limit is the width in pixels, not the count of characters (wide letters take more room): treat these numbers as a guide, and check a long title in a search result preview. Duplicate titles across pages (`duplicate_titles`) are a real finding.
2. **Meta description.** Present, unique, 70 to 160 characters, written as a promise with a reason to click. Missing is a low to medium finding (Google may rewrite it); duplicated across many pages is medium.
3. **Headings.** One clear `h1` that says what the page is about and matches the search intent; logical `h2` sections. Several `h1` is a low finding in HTML5 but check that the second one is not a decorative element. No `h1` on a content page is medium. Note that `facts.py` counts `h1` in the raw HTML only.
4. **Search intent match.** Does the page answer the query implied by its title and `h1`? Is the main topic covered in depth compared with what a searcher expects? (`deduced`.)
5. **Content depth.** `thin_content_under_150_words` on pages meant to rank. Thin on a contact or legal page is fine.
6. **Internal links.** Important pages reachable in 3 clicks or fewer (`deep_pages_depth_over_3`), descriptive anchor text (`generic_anchor_text` count: "click here", "read more"), no page with a single inlink that matters (`single_inlink_pages`), no orphans.
7. **Images.** `alt` on meaningful images (`missing_alt_attr` counts missing attributes; `alt=""` is correct for decorative images), modern formats, dimensions set, descriptive file names.
8. **Structured data.** Types present (`jsonld_types`) fit the page: `Organization`/`WebSite` on the home, `Article`/`BlogPosting` on posts, `Product`/`Offer` on products, `FAQPage` only if the questions are visible and you do not promise a rich result for it (since 2023 Google shows FAQ rich results only for well-known government and health sites), `BreadcrumbList` on deep pages. An empty or invalid block is worse than none (check `invalid_jsonld_blocks`). Never recommend markup for content that is not visible on the page.
9. **Social sharing tags.** `og:title`, `og:description`, `og:image` (`open_graph`, `twitter`): they control how links look when shared.
10. **International.** `hreflang` pairs reciprocal and consistent with `html_lang` when the site has several languages.
11. **Keyword and cannibalisation.** Several pages with the same title or `h1` target the same query: pick one, merge or differentiate.

## Traps

- Do not state keyword rankings or search volumes without a data source. Without Search Console or a rank tool, say "not measured".
- `meta keywords` is ignored by Google: not a finding.
- A page can be technically perfect and still not rank because the topic is not wanted: say what you cannot know.
