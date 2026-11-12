# Fix mode: apply the action plan

Use when the person says "apply the plan", "fix it", "corrige", "applique le plan", or asks to start on the fixes after an audit. You need the audit folder `<W>` with `findings.json` and `action-plan.md`. `<S>` is this skill's `scripts/` folder.

`fix_tracker.py` is the referee. It refuses what the rules forbid (exit code 2): approving an action with something missing, skipping the priority order, marking done without a GO or a proof, storing a secret. If it refuses, do what it says, do not look for a way around it.

## The five rules

1. **Priority order.** Actions are numbered by priority (P1 first), the same ranking as "Les priorités" in the report. Work in that order.
2. **One GO per action.** A GO is a clear yes from the person for that action. A GO for several actions at once ("go for all the ready ones", "GO for P5 and P6") is not a GO: ask for each action one after the other and wait for each answer. The tracker cannot check that you really asked (it only queues one action at a time and refuses a second `approve` while one is open), so this rule is yours to keep. You never give a GO yourself: `--by` is the person's name. When you skip a blocked action, quote the person's words with `--out-of-order --reason`.
3. **Nothing starts with something missing.** An action is ready only when every item it needs has been provided. If one is missing, you ask the person for it, you do not guess, improvise a substitute, invent content (testimonials, numbers, quotes) or use an access that was not given for this job.
4. **No secrets in chat or in files.** Never ask for a password or token to be pasted. Ask them to put it in the agent's secret store or environment and tell you its name. The tracker keeps the name only and refuses anything that looks like a token.
5. **Verify, then tick.** After applying, run the action's `verify` and record what it returned. No proof, no done.

## Protocol

**A. Start**

```
python3 -I <S>/fix_tracker.py init --findings <W>/findings.json --owner "<name of the person who gives the GO>" --state <W>/fix-state.json
python3 -I <S>/fix_tracker.py status --state <W>/fix-state.json
```

`--owner` is required: ask the person for the name they sign with if you do not know it. From then on `approve` and `defer` accept only that name. If `init` complains that the findings are invalid, run `build_report.py` and fix `findings.json` first.

**B. Ask for everything missing, once**

```
python3 -I <S>/fix_tracker.py needs --state <W>/fix-state.json
```

Send ONE message to the person, in their language, grouped as access, information, content to provide, decision. For each item say what exactly you need and which action it unlocks (by priority number), most urgent first. Also ask, in the same message: production or staging, is there a recent backup, is anything off limits. Offer the way out: "if you prefer, I start with what is ready and we defer the rest".

For an `access`, check it yourself with a read-only probe before you record it. For ssh, WordPress (application password), FTP/FTPS and a site folder, use `python3 -I <S>/access_check.py ssh|wp|ftp|files ...`: it reads only and tells you what the access allows (write rights, WP-CLI, role). Its `ok: true` is the proof: add `--out <W>/access-wp.json` and pass that file to the tracker with `provide --check`, which refuses a missing or failed check. For anything else (git, CDN, tag manager), do a read call yourself. Record the access only after the probe worked:

```
python3 -I <S>/fix_tracker.py provide --need wp_admin_access --ref WP_APP_PASSWORD --check <W>/access-wp.json --state <W>/fix-state.json
python3 -I <S>/fix_tracker.py provide --need consent_rules --note "analytics only after consent, ads never before" --state <W>/fix-state.json
```

If a probe fails, tell the person what failed and keep the item missing. If an access is lost later, `provide --need X --revoke` puts it back to missing.

**C. Loop, one action at a time**

```
python3 -I <S>/fix_tracker.py next --state <W>/fix-state.json
```

- **Ready, mode `agent`:** show the work order to the person in a short message: what changes, where, the risk, the rollback, how you will verify. Ask "GO ?" and stop. On a yes: `approve --id F1 --by "<their name>"`, apply the steps exactly as written, run the `verify`, then `done --id F1 --proof "<what you checked and the value>"`. If it fails: undo with the rollback, `fail --id F1 --reason "<what happened>"`, report it, and let the person choose `reopen` (retry) or `defer --id F1 --by "<their name>" --reason "<their words>"` (skip).
- **Blocked:** ask for the missing item (it should already have been asked in step B: remind them which action it blocks). Do not start a later action on your own. If the person says to skip ahead, `approve ... --out-of-order --reason "<their words>"` on the next ready one, or `defer --id F2 --by "<their name>" --reason "<their words>"` the blocked one. Skipping is the person's choice and is logged with their name, like a GO.
- **Mode `assisted` or `human`:** you cannot apply it. Prepare exactly what the person needs (the final text, the code snippet, the settings to change, a ticket for the developer), give it, then `handoff --id F2 --note "<what you sent>"`. Handed-off actions do not block you: move on. When they say it is done, run the `verify`, then `done`.
- **Waiting:** `next` lists what waits on the person. Remind them once at the end, not after every action.

**D. Finish**

`next` says "All actions are done" (or nothing is left for you to start). Give a table: done, failed, deferred, waiting on the person, each with its proof or reason. Then offer to rerun the audit on the same pages with the same scope, in a NEW work folder, and compare:

```
python3 -I <S>/audit_diff.py <W>/findings.json <new work folder>/findings.json --out <new work folder>/audit-diff.md
```

The rerun is what proves the fixes worked. Read the diff honestly: a finding the second audit no longer reports is a candidate fix, not a confirmed one (it may have been reworded, or its page not measured this time). Check it against the "how to verify" line the diff recalls before telling the person it is fixed, and also say what is new and what got worse. The diff refuses to compare two different sites, and a finding whose domain was not audited this time is listed separately, not as a fix.

## What to put in the GO message

Short, concrete, no jargon. Example (adapt the language to the person):

> Action 1 sur 7, priorité haute : forcer https sur tout le domaine.
> Ce que je change : la règle « Always Use HTTPS » dans Cloudflare, et deux adresses dans les réglages WordPress.
> Risque : moyen. Retour arrière : je désactive la règle et je remets les anciennes adresses (je les note avant).
> Vérification : `curl -I http://site.example/` doit répondre 301 vers https.
> GO ?

## Risk handling

- **low:** a GO per action is enough.
- **medium:** state the rollback in the GO message, and make sure a backup or a saved previous version exists before you touch anything.
- **high** (checkout, payments, DNS, site-wide redirects, indexing rules, legal text, anything hard to undo): ask for the GO with the rollback explicitly confirmed by the person, use staging first if there is one, and never batch it with other actions. That rule is yours to keep for every action, not the tracker's: `approve` only refuses to open a second action while another one is approved and not yet `done` or `fail`ed. It cannot know whether you asked the person once or twice. "GO for P5 and P6" is not a GO: ask for P5, wait for the answer, apply it, then ask for P6.

## Need kinds

| Kind | You do | Never |
|---|---|---|
| `access` | probe it read-only with `access_check.py ... --out`, then `provide --ref NAME --check <that file>`. `NAME` is an environment variable that exists in this session (its value is never read) or `vault:ENTRY`. The proof is the file, sealed by `access_check.py`, fresh, of the type the need declares in `check_type` (`wp`, `ssh`, `ftp`, `files`); a sentence in `--note` is accepted only for an access no script can test, with a success marker such as `verified: 200`. It is a declared proof, not a security boundary: the trail is the name in the log | ask for the secret in chat, reuse a credential for another purpose |
| `info` | take the person's answer in one sentence | assume it |
| `content` | draft from what they gave, with real facts only | invent a testimonial, a number, a name, a result |
| `decision` | present the options and the effect of each, record their words in `--note` | decide for them (price, legal wording, brand, budget) |

## Never

- Apply anything without a GO from the person, or give the GO yourself.
- Start an action with a missing need, or work around a refusal of `fix_tracker.py`.
- Change anything the action does not list, on pages or systems outside the audited site.
- Store a secret in a file, a note or the chat.
- Mark an action done without having run its verification.
