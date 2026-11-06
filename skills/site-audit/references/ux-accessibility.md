# UX, mobile and accessibility (`ux`, `accessibility`)

Sources: `shots/mobile-NN.png` and `desktop-NN.png` (look at them), `shots/rendered.json` (`fixed_or_sticky`, `small_tap_targets`, `buttons_and_links` with size and position, `horizontal_scroll`, `forms_visible`), `lh/summary.json` (`digest.contrast_offenders`, accessibility score, failed audits), `facts.json` (forms, viewport, links, headings).

## UX and mobile (`ux`)

1. **First screen on a phone** (`mobile-01.png`): in 5 seconds, can a stranger say what this is, who it is for, and what to do next? Is the main action visible without scrolling? Is something covering it? `rendered.json` `fixed_or_sticky` lists banners, chat bubbles and sticky bars with the share of the screen they cover (a banner above about 15% is worth a finding).
2. **Visual hierarchy.** One dominant element per screen. Size, contrast and spacing lead the eye to the headline, then the proof, then the button. Walls of text, equal-weight blocks and several competing buttons are findings.
3. **Navigation.** Few clear entries, the current page shown, the main call to action reachable from the menu, a way back home. No dead-end page.
4. **Tap targets and readability.** Targets of about 44 px or more (WCAG 2.2 minimum 24 px): `small_tap_targets` counts links and buttons under 40 px, and `buttons_and_links[*].h` names them. Text of 16 px or more on mobile, comfortable line length, `horizontal_scroll` false, `viewport` meta present.
5. **Forms** (`forms`): number of fields (each extra field costs completions), labels (`labels` vs `fields`), required marks, error handling, button text that says the result ("Get my audit", not "Submit"), no CAPTCHA unless needed.
6. **Feedback and states.** Buttons and links look clickable, focus is visible, loading and error states exist (only what you can see).
7. **Consistency.** Same style for the same action across pages (crawl titles and headings help).
8. **Popups and interstitials.** Intrusive overlays on arrival on mobile are a finding for UX and for search.

## Accessibility (`accessibility`)

Baseline target: WCAG 2.2 level AA. Automated tools find only part of the problems: say "automated checks only".

1. **Lighthouse accessibility score** and `digest.failed_audits` (names, values).
2. **Contrast.** `digest.contrast_offenders`: text 4.5:1 (3:1 for large text). Name the selectors; one element repeated is one finding.
3. **Text alternatives.** Images with `alt` where meaningful; icons-only buttons with an accessible name (`aria-label`).
4. **Structure.** One `h1`, logical heading order, landmarks (`main`, `nav`), `html lang` set.
5. **Forms.** Every field has a label (`forms[*].labels` against `fields`), errors are described in text, not only by color.
6. **Keyboard and focus.** Not measurable by these scripts: write it in `not_measured`, unless you tested it.
7. **Links.** Descriptive link text, not "click here" (`links.generic_anchor_text`).
8. **Motion and media.** Autoplay video or animation without a way to stop it.

## Traps

- A good Lighthouse accessibility score does not mean the site is accessible: say so.
- Do not claim legal compliance (RGAA, EAA, ADA). Say "gaps visible in automated checks".
- A cookie banner that traps focus or hides content on mobile is both a UX and an accessibility finding: report once, cross-reference.
