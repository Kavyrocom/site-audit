#!/usr/bin/env python3
"""Track and enforce the execution of an action plan (stdlib only).

The audit produces findings.json and action-plan.md. This script is the state machine that lets an agent apply
the plan safely: priority order, one GO per action, nothing started until every needed item has been provided.

Usage:
    fix_tracker.py init     --findings F.json --owner NAME [--state fix-state.json] [--force]
    fix_tracker.py status   [--state S]
    fix_tracker.py needs    [--state S]                     what is still missing, to ask the person ONCE
    fix_tracker.py provide  --need ID [--ref NAME] [--note TEXT] [--check access.json] [--revoke] [--state S]
    fix_tracker.py next     [--state S] [--json]            next action in priority order, ready or blocked
    fix_tracker.py approve  --id F1 --by NAME [--out-of-order --reason TEXT] [--state S]   agent actions only
    fix_tracker.py handoff  --id F1 --note TEXT [--state S]  assisted/human action: instructions given
    fix_tracker.py done     --id F1 --proof TEXT [--plan action-plan.md] [--state S]
    fix_tracker.py fail     --id F1 --reason TEXT [--state S]
    fix_tracker.py defer    --id F1 --by NAME --reason TEXT [--state S]       the person's choice, with their words
    fix_tracker.py reopen   --id F1 [--state S]

Rules enforced here (exit code 2 when broken):
  - an action is READY only when mode is not 'human' and every need is provided
  - the agent applies only mode 'agent' actions, one GO each; 'assisted' and 'human' ones are handed off
  - `approve` needs READY, the name given at `init --owner`, no more urgent action still open (unless --out-of-order
    with the reason the person gave), and no other action already approved and not finished: one GO at a time,
    so a risky action is never approved together with another
  - `defer` (skipping an action) is the person's choice too: it needs --by, the same name, and their words in --reason
  - an access is proved by the file access_check.py --out wrote (marked by the script, fresh, of the type the need declares), not by a sentence
  - `done` needs an approved action (applied by the agent) or a handed-off one (applied by a human), plus a proof
  - secrets are never stored: a need flagged secret is provided by --ref (the NAME of the env variable or vault
    entry), and any note that looks like a token is refused
Every change is appended to fix-log.md next to the state file, and `done` ticks the box in action-plan.md.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_report as br  # noqa: E402
import redact  # noqa: E402
import safenet  # noqa: E402

# A long run of letters and digits is a secret only when it mixes both (a slug such as "very-long-article-about-plumbing" is not one)
LONG_MIXED = r"(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])(?<![/\w-])[A-Za-z0-9_\-]{28,}"
OWNER_TOKEN = re.compile(r"[A-Za-z0-9_\-]{28,}|bearer\s+\S+|password\s*[=:]|secret\s*[=:]", re.I)
TOKENISH = re.compile(LONG_MIXED + r"|bearer\s+\S+|password\s*[=:]|passwd\s*[=:]|secret\s*[=:]|api[_-]?key\s*[=:]", re.I)
REF_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_./:@-]{0,60}$")
# A GO comes from a person. These names are the agent, a tool or a pronoun, never the person who decided.
NOT_A_PERSON = re.compile(r"^(?:agent|assistant|bot|ai|ia|llm|me|myself|self|moi|auto|automatic|system|script|user|utilisateur|human|claude(?:\s+code)?|codex|hermes|"
                          r"(?:the\s+|le\s+|la\s+|un\s+|une\s+)?(?:owner|propri[eé]taire|client|customer|boss|patron|chef|admin|administrator|root|go|yes|oui|ok|okay|test|nobody|none|unknown|n/?a|someone|quelqu.un)|a\.?\s?i\.?|(?:gemini|mistral|kimi|llama|hermes|deepseek|qwen|grok)(?:\s+(?:pro|flash|ultra|large|small|agent|bot|ai|\d[\w.\-]*))?)$"
                          r"|(?<![A-Za-z])(?:agent|assistant|bot|robot|llm|gpt\w*|chatgpt\w*|copilot|codex|subagent|opus|sonnet|haiku|"
                          r"perplexity|openai|anthropic|the\s+user|l.utilisateur|le\s+chat)(?![A-Za-z])|(?<![A-Za-z])c1aude(?![a-z])|(?<![A-Za-z])claude\s+(?:code|opus|sonnet|haiku|\d)|\buser\d+\b", re.I)
# A verified access says so, with a success marker, and says nothing that undoes it.
PROBE_OK = re.compile(r"\b(?:verified|tested|checked|vérifié|testé)\b", re.I)
PROBE_SUCCESS = re.compile(r"\b2\d\d\b|\bok\b|\btrue\b|\bsuccess\w*\b|\bréussi\w*\b", re.I)
PROBE_FAIL = re.compile(r"\b(?:un(?:verified|tested|checked)|not|pas|non|failed|fails?|failure|cannot|can't|refus\w*|rejet\w*|rejected|denied|forbidden|unauthori[sz]ed|"
                        r"timeout|timed\s+out|errors?|erreurs?|échecs?|echecs?|invalid\w*|expired|expiré\w*|wrong|bad)\b|\b[45]\d\d\b|n't\b", re.I)
OPEN = {"pending", "approved", "failed"}  # statuses that still block less urgent actions


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(2)


def clean(label, text, maxlen=300):
    """Free text that will be written to the state and to fix-log.md: never a secret, never a wall of output."""
    if text is None:
        return None
    text = text.strip()
    if len(text) > maxlen:
        die(f"{label} is too long ({len(text)} > {maxlen} characters): say what you checked and what it returned, not the output")
    secrets, personal = redact.sensitive_kinds(text)
    if TOKENISH.search(text) or any(k in redact.HIGH_CONFIDENCE for k in secrets):
        die(f"{label} looks like it holds a secret or a long token: nothing of the kind is ever stored. "
            "Say where it lives (the variable or vault entry name) and reword without the value")
    if personal:
        die(f"{label} holds personal data (an e-mail address, an IP address, a telephone number or a person's identifier): the log is a "
            "file people share. Say what you checked without it")
    return text


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        die(f"cannot read state {path}: {e} (run `init` first)")


def save(path, st):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    safenet.private_output(path)


def log(state_path, line):
    with open(os.path.join(os.path.dirname(os.path.abspath(state_path)), "fix-log.md"), "a", encoding="utf-8") as fh:
        fh.write(f"- {now()} {line}\n")


def person(st, by, what="the GO"):
    """The name of the person who decides: the owner declared at init, written as that person says it."""
    by = clean("--by", by, 60)
    owner = (st.get("owner") or "").strip()
    same = lambda p, q: re.sub(r"\W+", " ", p).casefold().strip() == re.sub(r"\W+", " ", q).casefold().strip()
    if not by:
        die(f"--by is required: the name of the person who gave {what}")
    if owner:
        if not same(by, owner):
            die(f"{what} of this audit comes from {owner} (declared at init). --by must be that name, as the person said it. "
                "If someone else may decide, run `init --force --owner` again with their name")
    elif NOT_A_PERSON.search(by):
        die(f"--by must be the name of the person who gave {what}, never the agent")
    return by


def find(st, fid):
    for a in st["actions"]:
        if a["id"] == fid:
            return a
    die(f"unknown action id '{fid}'")


def missing(st, a):
    return [n for n in a["needs"] if not st["needs"][n]["provided"]]


def readiness(st, a):
    if a["status"] in ("done", "deferred", "failed", "approved", "handed_off"):
        return a["status"]
    if a["mode"] == "human":
        return "human"
    return "blocked" if missing(st, a) else "ready"


def label(st, a):
    r = readiness(st, a)
    if r == "blocked":
        return "blocked: needs " + ", ".join(missing(st, a))
    return r


def cmd_init(a):
    if os.path.exists(a.state) and not a.force:
        die(f"{a.state} already exists (use --force to rebuild, this resets progress)")
    try:
        with open(a.findings, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError) as e:
        die(f"cannot read {a.findings}: {e}")
    try:
        errs, _ = br.validate(d)
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        die(f"{a.findings} is malformed ({type(e).__name__}: {e}); run build_report.py to see what is wrong")
    if errs:
        die("findings.json is not valid, run build_report.py first:\n - " + "\n - ".join(errs))
    owner = (a.owner or "").strip()                   # everything is checked before the old state is touched
    if not owner:
        die("--owner is required: the name of the person who gives the GO, as they write it (ask them if you do not know it)")
    if NOT_A_PERSON.search(owner) or OWNER_TOKEN.search(owner):
        die("--owner must be the name of a person: not an agent, a tool or a role (this check only catches the obvious ones, the GO still has to come from a person)")
    if os.path.exists(a.state):
        old = load(a.state)
        counts = {}
        for x in old.get("actions", []):
            counts[x["status"]] = counts.get(x["status"], 0) + 1
        backup = f"{a.state}.bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        n = 1
        while os.path.exists(backup):                  # two rebuilds in the same second must not overwrite each other
            n += 1
            backup = f"{a.state}.bak-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{n}"
        os.replace(a.state, backup)
        log(a.state, f"init --force: previous state kept as {os.path.basename(backup)} (" + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + ")")
    scores, overall, ranked, top, plan = br.compute(d)
    phase = {f["id"]: k for k in ("week", "month", "later") for f in plan[k]}
    reg = br.collect_needs(d)
    st = {"version": 1, "created": now(), "owner": owner or None, "url": d["meta"]["url"], "language": d["meta"].get("language", "en"),
          "source": os.path.basename(a.findings), "score_before": overall,
          "needs": {nid: {"kind": r["kind"], "what": r["what"], "secret": r["secret"], "check_type": r.get("check_type"), "provided": False, "ref": None, "note": None, "provided_at": None}
                    for nid, r in reg.items()},
          "actions": []}
    for n, (_, _, f) in enumerate(ranked, 1):
        ex = f["execution"]
        st["actions"].append({
            "id": f["id"], "priority": n, "title": f["title"], "phase": phase[f["id"]], "mode": ex["mode"], "risk": ex["risk"],
            "rollback": ex.get("rollback", ""), "needs": [x["id"] for x in ex["needs"]] if ex["mode"] != "human" else [],
            "fix_steps": f["fix_steps"], "verify": f["verify"], "observation": f["observation"], "pages": f.get("pages", []),
            "status": "pending", "approved_by": None, "approved_at": None, "done_at": None, "proof": None, "reason": None})
    save(a.state, st)
    log(a.state, f"init: {len(st['actions'])} actions, {len(st['needs'])} needs, score before {overall}/100")
    print(f"state written: {a.state} ({len(st['actions'])} actions in priority order, {len(st['needs'])} distinct needs)")


def cmd_status(a):
    st = load(a.state)
    counts = {}
    for x in st["actions"]:
        r = readiness(st, x)
        counts[r] = counts.get(r, 0) + 1
    print(f"{st['url']} | score before: {st['score_before']}/100 | " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    for x in st["actions"]:
        print(f"P{x['priority']:<2} {x['id']:<5} [{label(st, x)}] ({x['mode']}, risk {x['risk']}) {x['title'][:80]}")


def cmd_needs(a):
    st = load(a.state)
    users = {}
    for x in st["actions"]:
        if x["status"] in ("done", "deferred") or x["mode"] == "human":
            continue
        for n in x["needs"]:
            if not st["needs"][n]["provided"]:
                users.setdefault(n, []).append(x["priority"])
    if not users:
        print("Nothing is missing: every open action has what it needs.")
        return
    print("Missing, to ask the person in ONE message (most urgent action first):")
    for n, prios in sorted(users.items(), key=lambda kv: min(kv[1])):
        r = st["needs"][n]
        how = "give the NAME of the env variable or vault entry (never the value in chat)" if r["secret"] else "answer in a sentence"
        print(f"- {n} [{r['kind']}] {r['what']}  | needed by P{', P'.join(str(p) for p in sorted(prios))} | {how}")


def cmd_provide(a):
    st = load(a.state)
    if a.need not in st["needs"]:
        die(f"unknown need '{a.need}' (known: {', '.join(st['needs'])})")
    r = st["needs"][a.need]
    if a.revoke:
        r.update(provided=False, ref=None, note=None, provided_at=None)
        save(a.state, st)
        log(a.state, f"need {a.need}: revoked")
        print(f"{a.need}: marked missing again")
        return
    note = clean("--note", a.note, 240)
    ref = clean("--ref", a.ref, 61)
    if ref is not None and not REF_OK.match(ref):
        die("--ref is a NAME (an env variable or a vault entry), letters, digits and _ . / : @ - only")
    if ref is not None and not ref.startswith("vault:") and ref not in os.environ:
        die(f"--ref {ref} is not a variable of this environment. Give the NAME of an environment variable that exists here "
            "(its value is never read), or `vault:NAME` for an entry of a vault. A pasted value is not a name")
    if a.check:
        note = note_from_check(a.check, note, r.get("check_type"))
    if r["secret"]:
        if not ref:
            die(f"'{a.need}' is a credential: give --ref NAME (the env variable or vault entry name, not the value)")
    elif not note:
        die(f"'{a.need}' needs --note: what the person gave, in a sentence")
    if r["kind"] == "access" and a.check:
        pass                                    # the proof is the JSON itself, already read by note_from_check
    elif r["kind"] == "access" and not (note and PROBE_OK.search(note) and PROBE_SUCCESS.search(note) and not PROBE_FAIL.search(note)):
        die("an access is provided only after a read-only probe succeeded. Best: `access_check.py ... --out check.json`, then "
            "`provide --check check.json`. Otherwise say it in --note with a success marker, for example 'verified: GET /wp-json 200' "
            "(words like 'untested', 'failed', 'not checked' or an HTTP 4xx/5xx are refused)")
    r.update(provided=True, ref=ref, note=note, provided_at=now())
    save(a.state, st)
    log(a.state, f"need {a.need}: provided" + (f" (ref {a.ref})" if a.ref else ""))
    print(f"{a.need}: provided")


def note_from_check(path, note, want_type=None):
    """Build the note from the JSON that access_check.py wrote: the proof is its `ok: true`, not a sentence."""
    try:
        with open(path, encoding="utf-8") as fh:
            c = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        die(f"--check {path}: cannot read the access_check result ({e})")
    if not isinstance(c, dict) or c.get("ok") is not True or "type" not in c:
        die(f"--check {path}: that access check did not succeed (ok is not true). Follow its next_step and run it again")
    if not safenet.sealed(c):
        die(f"--check {path}: that file was not written by access_check.py (its seal is missing or broken). Run access_check.py with --out")
    if want_type and c.get("type") != want_type:
        die(f"--check {path}: this need is proved by an access_check.py '{want_type}' check, and that file is a '{c.get('type')}' check")
    try:
        age = (datetime.now(timezone.utc) - datetime.strptime(c.get("checked_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds()
    except ValueError:
        die(f"--check {path}: no valid checked_at in it. Run access_check.py again with --out (an old or hand-written file is not a proof)")
    if age > 6 * 3600 or age < -300:
        die(f"--check {path}: that check is {int(age // 60)} minutes old. Run it again, an access is proven by a fresh probe")
    detail = re.sub(r"\s+", " ", str(c.get("detail", "")))[:120]
    text = f"verified by access_check.py {c['type']}: ok, {detail}" + (f" | {note}" if note else "")
    return clean("--check detail", text, 300)


def work_order(x):
    lines = [f"P{x['priority']} {x['id']} - {x['title']}", f"Why: {x['observation']}", "Steps:"]
    lines += [f"  {i}. {s}" for i, s in enumerate(x["fix_steps"], 1)]
    lines += [f"Verify: {x['verify']}", f"Risk: {x['risk']}" + (f" | Rollback: {x['rollback']}" if x["rollback"] else "")]
    if x["pages"]:
        lines.append("Pages: " + ", ".join(x["pages"][:8]))
    return "\n".join(lines)


def cmd_next(a):
    st = load(a.state)
    cur = next((x for x in st["actions"] if x["status"] in OPEN), None)
    waiting = [x["id"] for x in st["actions"] if x["status"] == "handed_off"]
    if cur is None:
        left = [x["id"] for x in st["actions"] if x["status"] not in ("done", "deferred", "handed_off")]
        deferred = [x["id"] for x in st["actions"] if x["status"] == "deferred"]
        state = "finished" if not (waiting or deferred) else ("waiting_on_person" if waiting else "only_deferred")
        out = {"state": state, "waiting_on_person": waiting, "deferred": deferred, "left": left}
        if a.json:
            print(json.dumps(out))
        elif state == "finished":
            print("All actions are done.")
        else:
            print(f"Nothing left for the agent to start. Waiting on the person: {', '.join(waiting) or 'none'}. Deferred: {', '.join(deferred) or 'none'}.")
        return
    r = readiness(st, cur)
    res = {"id": cur["id"], "priority": cur["priority"], "readiness": r, "mode": cur["mode"], "risk": cur["risk"],
           "missing": missing(st, cur) if cur["mode"] != "human" else [], "title": cur["title"]}
    res["waiting_on_person"] = waiting
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
        return
    print(f"NEXT: {cur['id']} (P{cur['priority']}) readiness={r}" + (f" | waiting on the person: {', '.join(waiting)}" if waiting else ""))
    if r == "ready" and cur["mode"] == "assisted":
        print(work_order(cur))
        print("\nAssisted: prepare the exact snippet, text or settings, give them to the person who applies them, then `handoff`.")
    elif r == "ready":
        print(work_order(cur))
        print("\nShow this to the person (what changes, risk, rollback) and wait for an explicit GO, then `approve`.")
    elif r == "blocked":
        print(f"BLOCKED, missing: {', '.join(res['missing'])}. Ask the person (see `needs`), do NOT guess, do NOT start.")
    elif r == "human":
        print(work_order(cur))
        print("\nA human applies this one. Give the instructions, then `handoff`, and verify when they say it is done.")
    elif r == "approved":
        print(work_order(cur))
        print("\nApproved: apply it, run the Verify step, then `done --proof` or `fail --reason`.")
    elif r == "failed":
        print(f"FAILED earlier: {cur['reason']}. Report it, then `reopen` (retry) or `defer` (skip) as the person decides.")


def cmd_approve(a):
    st = load(a.state)
    x = find(st, a.id)
    a.by = person(st, a.by)       # (the script cannot prove who answered: it forces the owner's name into the log, which is the trail)
    busy = [y["id"] for y in st["actions"] if y["status"] == "approved" and y["id"] != x["id"]]
    if busy:
        die(f"{', '.join(busy)} is approved and not finished. One GO at a time: apply it, verify it, `done` or `fail`, then ask for the next GO")
    if x["mode"] != "agent":
        die(f"{x['id']} is '{x['mode']}': the agent does not apply it itself. Prepare what is needed, then use `handoff`")
    if x["status"] not in ("pending",):
        die(f"{x['id']} is '{x['status']}', only a pending action can be approved")
    m = missing(st, x)
    if m:
        die(f"{x['id']} is blocked, missing: {', '.join(m)}. Ask the person first")
    earlier = [y for y in st["actions"] if y["priority"] < x["priority"] and y["status"] in OPEN]
    a.reason = clean("--reason", a.reason, 300)
    if earlier and not a.out_of_order:
        die(f"more urgent actions are still open: {', '.join(y['id'] for y in earlier)}. Priority order applies; "
            "if the person chose to skip ahead, pass --out-of-order --reason with their words")
    if earlier and not (a.reason or "").strip():
        die("--out-of-order needs --reason (what the person said)")
    x.update(status="approved", approved_by=a.by.strip(), approved_at=now())
    save(a.state, st)
    log(a.state, f"{x['id']}: GO by {a.by.strip()}" + (f" OUT OF ORDER ({a.reason})" if earlier else ""))
    print(f"{x['id']}: approved by {a.by.strip()}")


def cmd_handoff(a):
    st = load(a.state)
    x = find(st, a.id)
    if x["status"] not in ("pending", "failed"):
        die(f"{x['id']} is '{x['status']}'")
    if x["mode"] == "agent":
        die(f"{x['id']} is an agent action: use approve, then done")
    if x["mode"] == "assisted" and missing(st, x):
        die(f"{x['id']} still needs: {', '.join(missing(st, x))}. Ask the person first")
    a.note = clean("--note", a.note, 300)
    x.update(status="handed_off", reason=a.note)
    save(a.state, st)
    log(a.state, f"{x['id']}: handed off ({a.note})")
    print(f"{x['id']}: handed off, waiting for the person")


def tick_plan(path, fid):
    if not path or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, n = re.subn(r"^(### - )\[ \](.*\(" + re.escape(fid) + r"\)\s*)$", r"\1[x]\2", text, flags=re.M)
    if n:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
    return bool(n)


def cmd_done(a):
    st = load(a.state)
    x = find(st, a.id)
    if x["status"] not in ("approved", "handed_off"):
        die(f"{x['id']} is '{x['status']}': it must be approved (agent applied) or handed off (human applied) before done")
    a.proof = clean("--proof", a.proof, 600)
    if len((a.proof or "").strip()) < 8:
        die("--proof is required: what you checked and what it returned")
    x.update(status="done", done_at=now(), proof=a.proof.strip())
    save(a.state, st)
    plan = a.plan or os.path.join(os.path.dirname(os.path.abspath(a.state)), "action-plan.md")
    ticked = tick_plan(plan, x["id"])
    log(a.state, f"{x['id']}: DONE ({a.proof.strip()[:160]})")
    print(f"{x['id']}: done" + (" (box ticked in the plan)" if ticked else ""))


def cmd_fail(a):
    st = load(a.state)
    x = find(st, a.id)
    if x["status"] not in ("approved", "handed_off"):
        die(f"{x['id']} is '{x['status']}'")
    a.reason = clean("--reason", a.reason, 300)
    x.update(status="failed", reason=a.reason)
    save(a.state, st)
    log(a.state, f"{x['id']}: FAILED ({a.reason})")
    print(f"{x['id']}: failed, roll back if anything was changed: {x['rollback'] or 'no rollback defined'}")


def cmd_defer(a):
    st = load(a.state)
    x = find(st, a.id)
    if x["status"] in ("done",):
        die(f"{x['id']} is already done")
    by = person(st, a.by, "the decision to skip it")
    a.reason = clean("--reason", a.reason, 300)
    if len((a.reason or "").strip()) < 6:
        die("--reason is required: what the person said when they chose to skip it")
    x.update(status="deferred", reason=a.reason)
    save(a.state, st)
    log(a.state, f"{x['id']}: deferred by {by} ({a.reason})")
    print(f"{x['id']}: deferred")


def cmd_reopen(a):
    st = load(a.state)
    x = find(st, a.id)
    if x["status"] not in ("failed", "deferred", "handed_off"):
        die(f"{x['id']} is '{x['status']}', nothing to reopen")
    x.update(status="pending", reason=None, approved_by=None, approved_at=None)
    save(a.state, st)
    log(a.state, f"{x['id']}: reopened")
    print(f"{x['id']}: pending again")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *args):
        sp = sub.add_parser(name)
        sp.add_argument("--state", default="fix-state.json")
        for spec, kw in args:
            sp.add_argument(spec, **kw)
        sp.set_defaults(fn=fn)
    add("init", cmd_init, ("--findings", {"required": True}), ("--force", {"action": "store_true"}), ("--owner", {"required": True, "help": "name of the person who gives the GO; --by must then match it"}))
    add("status", cmd_status)
    add("needs", cmd_needs)
    add("provide", cmd_provide, ("--need", {"required": True}), ("--ref", {}), ("--note", {}), ("--check", {"help": "JSON written by access_check.py --out"}), ("--revoke", {"action": "store_true"}))
    add("next", cmd_next, ("--json", {"action": "store_true"}))
    add("approve", cmd_approve, ("--id", {"required": True}), ("--by", {"required": True}), ("--out-of-order", {"action": "store_true"}), ("--reason", {}))
    add("handoff", cmd_handoff, ("--id", {"required": True}), ("--note", {"required": True}))
    add("done", cmd_done, ("--id", {"required": True}), ("--proof", {"required": True}), ("--plan", {}))
    add("fail", cmd_fail, ("--id", {"required": True}), ("--reason", {"required": True}))
    add("defer", cmd_defer, ("--id", {"required": True}), ("--by", {"required": True}), ("--reason", {"required": True}))
    add("reopen", cmd_reopen, ("--id", {"required": True}))
    a = ap.parse_args()
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
