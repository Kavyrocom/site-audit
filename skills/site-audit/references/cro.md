# Conversion (`cro`)

Sources: the rendered text `shots/rendered-mobile.txt` and `shots/rendered.json` (`buttons_and_links` with position, `forms_visible`, `fixed_or_sticky`), the screens `shots/mobile-NN.png`, and `facts.json` (`cta_candidates`, `forms`, `tel_mailto_links`). All findings here are `deduced` unless an analytics source is given. Never invent a conversion rate or a gain.

Start from the objective: what is the one action this page must earn? If it is not given, infer it and mark it `inferred`.

## Check (in this order, by weight on conversion)

1. **Message match and promise.** Within 5 seconds on the first screen: who it is for, what result they get, why this and not another. Is the headline a benefit or a label? Does it match the source of the visit (ad, search, social) as far as you can tell?
2. **Primary call to action.** One main action, visible above the fold on mobile, with a verb and the outcome ("Book my audit"), repeated after each major proof block. Count competing actions of the same visual weight (`cta_candidates`). Vague labels ("Submit", "Learn more") are a finding.
3. **Proof.** Testimonials with name and result, numbers of customers, logos, case studies, press, guarantees, certifications. Placed near the decision, not in a footer. Absence of any proof on the screens you saw is usually the biggest deduced gap; if the page is one screen long, say so. Fake or generic proof is worse than none.
4. **Offer clarity and price.** What exactly is received, for whom, at what price or what next step. Hidden price on a page that sells is friction; a clear "what happens after I click" lowers anxiety.
5. **Objections.** The 3 doubts of this visitor (price, time, risk, "will it work for me") answered on the page: FAQ, guarantee, comparison, before and after.
6. **Friction.** Fields in forms (`forms[*].fields`), forced account creation, steps count, unclear next step, mandatory phone number, distracting navigation on a landing page, a cookie banner hiding the button on mobile.
7. **Trust.** Real company information, contact options (`tel_mailto_links`), legal pages, secure payment signals, consistent branding, recent dates.
8. **Urgency and scarcity.** Only if real. Fake countdowns are a trust finding.
9. **Follow-up capture.** If a visitor is not ready, is there a lower-commitment path (lead magnet, newsletter, demo video)?
10. **Instrumentation.** Are conversions measurable (tags detected in `trackers_detected`)? A page that sells and tracks nothing cannot be optimised: report it, with the consent caveat.

## How to write a conversion finding

Observation (what the visitor sees), the likely effect on the objective in words (not numbers), the concrete change, and the test that would confirm it ("A/B the headline with the benefit version for two weeks or 1,000 visitors"). Mark `deduced`; use `hypothesis` for a guess about audience behaviour.

## Traps

- No "best practice" without the visitor's context: a long page can convert better than a short one for a high-priced offer.
- Do not recommend adding a popup, a countdown or more text by reflex.
- Do not call the page "bad". Say which step of the visit loses people, and why you think so.
