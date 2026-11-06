# Copywriting (`copy`)

Sources: `shots/rendered-mobile.txt` (the visible text after JavaScript, in reading order), `rendered.json` headings and buttons, `consistency/consistency.json` (contradictions between pages), and the screens. Findings are `deduced`, except a contradiction you proved by quoting both passages, which is `measured`.

Judge the writing against the objective and the reader, not your taste. Quote the exact sentence you criticise (it is the evidence), and propose a rewrite in the same language as the site.

## Check

1. **Headline.** Says the result for the reader in plain words. Test: would it still make sense on a competitor's site? If yes, it is too generic.
2. **Clarity over cleverness.** Short sentences, concrete nouns, one idea per block. Jargon, buzzwords and empty adjectives ("innovative", "unique", "solution") are a finding with a quoted example.
3. **Reader focus.** Count "you" against "we". A page that talks mostly about the company is a finding.
4. **Benefits before features.** For each feature, is the consequence for the reader stated?
5. **Specificity.** Numbers, names, time frames, outcomes. "Save time" versus "cut your weekly reporting from 3 hours to 20 minutes" only if the page can prove it.
6. **Structure and scanning.** Headings that tell the story on their own, short paragraphs, bullets for lists, bold on what matters. Mobile: no block above about 5 lines.
7. **Calls to action.** Verb plus outcome, consistent across the page, with a line that lowers anxiety under the button when it helps.
8. **Tone and consistency.** One voice throughout, matching the audience. Mixed formal and informal address is a finding.
9. **Credibility of claims.** Superlatives and promises without proof ("the best", "guaranteed results"). Note legal risks (health, finance, earnings claims) for a human to review.
10. **Microcopy.** Form labels, error messages, button states, empty states, 404 page.
11. **Spelling and grammar.** List real errors with their location, not style preferences.

## Consistency of terms and facts (run `consistency.py`, site scope)

A site that says two things about the same thing loses trust and sales. `python3 -I <S>/consistency.py --pages crawl/pages.jsonl --out consistency` lists **candidates**, with the exact passages and the pages. It never decides: you read each snippet and keep only the real contradictions.

| Candidate | What it means | Keep it when |
|---|---|---|
| `price_conflicts` | the same service or product shown at different amounts | both passages name the same offer, same period, same currency, and the gap is not VAT (HT/TTC), a "from" price, a discount, an option or an instalment |
| `quantity_conflicts` | the same promise with different numbers ("delivery in 48 h" here, "5 working days" there; "free from 60 EUR" and "free from 75 EUR") | both are promises about the same thing, not two different examples |
| `contact_issues` | several phones, e-mails or addresses; a `tel:` or `mailto:` link that does not match the text | the site is one business at one place, not several branches |
| `name_variants` | the brand spelled several ways | the variants are for the same name, not a product vs. a company |
| `cta_variants` | one destination, many button texts | it hurts the message (say "Book", "Reserve", "Get a quote", "Contact" for one form) |
| `year_claims` | "since 2016" vs "since 2020", "10 years of experience" vs a founding year, stale copyright year | the figures can be added up and they do not match |

Also read the rendered text yourself for what the script cannot see: a different benefit promised in the headline and in the button, the offer called three names, "free" next to a price, tutoiement and vouvoiement mixed, a guarantee on one page and none on the legal page. If the site is built with JavaScript, say the script read only the initial HTML.

**A consistency finding must quote both passages with their page** (`evidence`), name which one looks right when the site itself shows it (the checkout, the legal page, the invoice), and have the owner decide the truth: you never decide which price is the real one. Price and promise contradictions are usually `high` when they sit on a conversion page, because they break trust at the moment of choice.

## Traps

- Do not rewrite the whole page. Give the 3 to 5 changes that matter and one model rewrite of the headline and the main call to action.
- Do not invent testimonials or numbers in your rewrite: use placeholders like `[number]` for what the owner must supply.
- A contradiction is not a different example: "Gain: 8h per week" for a sales team and "4h" for accounting, or two reminders "48h before" and "24h before" on one page, are not contradictions. Check the context before you write it down.
- Keep the owner's voice. If the site has a clear voice, adapt to it.
