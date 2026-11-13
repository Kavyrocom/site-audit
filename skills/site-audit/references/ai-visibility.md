# AI visibility (`ai_visibility`)

How easily AI assistants and AI search can read, understand and cite the site. Sources: `facts.json` (`site_level` for `llms.txt` and `robots.txt`, `structured_data`, headings), `crawl`.

Be honest about the state of the field: there is no proven ranking recipe for AI answers. Findings here are `deduced` or `hypothesis`, never `critical`.

## Check

1. **Crawl access.** `facts.json` holds the whole `robots.txt` (`site_level.robots_txt_full`) and, for each known AI robot, whether it may fetch `/` and whether a group names it (`site_level.ai_crawlers_robots`). Training crawlers: GPTBot, ClaudeBot, CCBot, Bytespider. Search and citation crawlers: OAI-SearchBot, Claude-SearchBot, PerplexityBot. Fetchers that act for a person who asked a question: ChatGPT-User, Claude-User, Perplexity-User (blocking them keeps your pages out of the answer that person asked for). `Google-Extended` and `Applebot-Extended` are robots.txt tokens, not robots: they only say whether the content may feed those companies' AI, and the normal Googlebot/Applebot keep crawling. Is the choice made on purpose? Report what the file says; do not recommend allowing or blocking without the owner's goal.
2. **Content readable without JavaScript.** If the main text only appears after JS, most AI crawlers will not see it (`crawl` warning).
3. **Answer-friendly structure.** Clear `h2`/`h3` questions with short direct answers, definitions, lists, tables, dated facts. These help both people and extraction.
4. **Entity clarity.** Who is the organisation or author: `Organization`/`Person` schema with real content, consistent name, an About page, author bylines, `sameAs` links to real profiles. Empty structured data blocks are a finding.
5. **Citability.** Original data, named sources, numbers with dates, quotes attributed. Vague content is not cited.
6. **`llms.txt`.** `site_level./llms.txt.status`. It is an emerging convention with unproven effect: absence is `low` at most, say so.
7. **Freshness.** Visible publication or update dates on content that ages.
8. **Sub-questions.** A question is often answered from several narrower questions around it. A page or a section that answers each of them gives more chances to be found and quoted. Check that the main sub-questions of the subject are answered, in the page or in a section.

## Traps

- Read this domain after `seo`. Google states that AI Overviews are built to show only information backed by top web results, so a page generally has to appear in the classic results first. Do not turn an example into a rate.
- Do not promise citations or traffic from AI. Say what makes content easier to read and quote.
- Do not recommend hiding content or special markup "for AI" that users cannot see.
