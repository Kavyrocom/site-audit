#!/usr/bin/env python3
"""Compare two audits of the same site: what the second one no longer reports (stdlib only).

Usage:
    python3 -I audit_diff.py first/findings.json second/findings.json [--out audit-diff.md] [--json audit-diff.json]

The natural moment for this is after the fixes: rerun the audit on the same pages with the same scope,
build its findings.json, then compare. Both files must pass the quality gate of build_report.py (an
audit that was never validated is not comparable), and they must be two audits of the same site.

What it says, and what it refuses to say:
  - a finding is "the same problem" in both audits when its domain, its pages and its normalised title
    match. The id (F1, F2...) is NOT used: the model numbers findings fresh in every audit
  - a finding of the first audit the second does not report is a CANDIDATE fix, never a confirmed one:
    it may have been fixed, reworded, or its page not measured this time. Its "how to verify" line is
    recalled so it can be checked before anyone calls it fixed
  - a finding whose domain the second audit dropped is "not audited this time", a separate list: an
    absent domain is not a fixed problem either
  - scores are recomputed from the findings of each audit with the same arithmetic as the report
  - the second audit must be the newer one, and the two must have the same host (www ignored)

Outputs: audit-diff.md (the comparison) and, with --json, a machine-readable copy.
Exit codes: 0 ok, 2 usage or validation errors (nothing written).
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_report as br  # noqa: E402  the same validation and the same scores as the report
import safenet  # noqa: E402


def die(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(2)


def load_audit(path):
    """A findings file that passes the quality gate, or exit 2."""
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        die(f"cannot read {path}: {e}")
    try:
        errs, warns = br.validate(d)
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        die(f"{path} is malformed ({type(e).__name__}: {e}); run build_report.py on it to see what is wrong")
    for w in warns:
        print(f"WARNING ({os.path.basename(path)}):", w, file=sys.stderr)
    if errs:
        die(f"{path} does not pass the quality gate (run build_report.py on it to see every error):\n - "
            + "\n - ".join(errs[:8]) + (f"\n - ... and {len(errs) - 8} more" if len(errs) > 8 else ""))
    return d


def host_of(url):
    """The host of the audited site, case and www ignored: two audits of the same site, or a refusal."""
    raw = str(url or "")
    if "//" not in raw:
        raw = "//" + raw
    netloc = (urlsplit(raw).netloc or "").casefold()
    return netloc[4:] if netloc.startswith("www.") else netloc


def norm_title(title):
    """A title is the same when only its case, spacing or punctuation changed."""
    return re.sub(r"\W+", " ", str(title)).casefold().strip()


def fkey(f):
    return (f.get("domain"), tuple(sorted(f.get("pages") or [])), norm_title(f.get("title")))


def match(first, second):
    """Pair the findings the two audits describe the same way. Duplicates pair one by one."""
    pool = {}
    for f in second:
        pool.setdefault(fkey(f), []).append(f)
    pairs, gone = [], []
    for f in first:
        q = pool.get(fkey(f))
        if q:
            pairs.append((f, q.pop(0)))
        else:
            gone.append(f)
    return pairs, gone, [f for q in pool.values() for f in q]


L = {
    "fr": {
        "title": "Comparaison des deux audits : {url}", "first": "Premier audit", "second": "Second audit",
        "scores": "Scores", "domain": "Domaine", "overall": "Score global", "change": "Écart",
        "gone": "Que le second audit ne signale plus ({n})",
        "gone_intro": "Chacun est un correctif candidat, pas un correctif confirmé : il a pu être corrigé, reformulé, ou sa page n'a pas été mesurée cette fois. Vérifie-le avant de dire qu'il est corrigé.",
        "check": "pour confirmer", "was": "gravité", "sev_down": "gravité en baisse", "sev_up": "gravité en hausse",
        "sev_same": "gravité inchangée", "still": "Toujours signalé ({n})", "new": "Nouveau dans le second audit ({n})",
        "not_audited": "Domaine non audité cette fois ({n})",
        "na_intro": "Le second audit n'a pas audité ce domaine : une absence ici n'est pas une correction.",
        "scope_warn": "Les deux audits n'ont pas le même périmètre ({a} puis {b}) : un constat peut être absent seulement parce que le second audit n'a pas visité les mêmes pages.",
        "pages_warn": "Le second audit a couvert moins de pages ({b} contre {a}) : un constat absent peut vivre sur une page non visitée.",
        "domains_warn": "Le second audit ne couvre pas les mêmes domaines (nouveaux : {added}, abandonnés : {dropped}) : le score global est calculé sur un autre mélange de domaines, compare le tableau par domaine.",
        "pages": "pages auditées", "scope": "périmètre",
    },
    "en": {
        "title": "Comparison of the two audits: {url}", "first": "First audit", "second": "Second audit",
        "scores": "Scores", "domain": "Domain", "overall": "Overall score", "change": "Change",
        "gone": "No longer reported by the second audit ({n})",
        "gone_intro": "Each is a candidate fix, not a confirmed one: it may have been fixed, reworded, or its page not measured this time. Check it before calling it fixed.",
        "check": "to confirm", "was": "severity", "sev_down": "severity down", "sev_up": "severity up",
        "sev_same": "same severity", "still": "Still reported ({n})", "new": "New in the second audit ({n})",
        "not_audited": "Domain not audited this time ({n})",
        "na_intro": "The second audit did not audit this domain: an absence here is not a fix.",
        "scope_warn": "The two audits do not have the same scope ({a} then {b}): a finding may be absent only because the second audit did not visit the same pages.",
        "pages_warn": "The second audit covered fewer pages ({b} against {a}): an absent finding may live on a page it did not visit.",
        "domains_warn": "The second audit does not cover the same domains (new: {added}, dropped: {dropped}): the overall score is computed on a different mix of domains, compare the per-domain table instead.",
        "pages": "pages audited", "scope": "scope",
    },
}


def render(url, a, b, scores_a, scores_b, gone, not_audited, pairs, new, warnings, lang):
    t = L[lang if lang in L else "en"]
    sev = br.L[lang if lang in br.L else "en"]["sev"]
    dom = {k: br.DOMAINS[k][1 if lang == "fr" else 2] for k in br.DOMAINS}
    out = []
    w = out.append
    w(f"# {t['title'].format(url=url)}\n")
    scope_a = a["meta"].get("scope", "page")
    scope_b = b["meta"].get("scope", "page")
    pa = f" · {a['meta'].get('pages_audited', '')} {t['pages']}" if scope_a == "site" else ""
    pb = f" · {b['meta'].get('pages_audited', '')} {t['pages']}" if scope_b == "site" else ""
    w(f"{t['first']}: {a['meta']['date']} · {t['scope']}: {scope_a}{pa} · {t['overall']}: {scores_a['overall']}/100  ")
    w(f"{t['second']}: {b['meta']['date']} · {t['scope']}: {scope_b}{pb} · {t['overall']}: {scores_b['overall']}/100\n")
    if warnings:
        for x in warnings:
            w(f"> {x}\n")
    w(f"## {t['scores']}\n")
    w(f"| {t['domain']} | {t['first']} | {t['second']} | {t['change']} |")
    w("|---|---|---|---|")
    for d in a["meta"]["domains_audited"]:
        if d in scores_b["scores"]:
            delta = scores_b["scores"][d] - scores_a["scores"][d]
            w(f"| {dom[d]} | {scores_a['scores'][d]}/100 | {scores_b['scores'][d]}/100 | {delta:+d} |")
    delta = scores_b["overall"] - scores_a["overall"]
    w(f"| **{t['overall']}** | {scores_a['overall']}/100 | {scores_b['overall']}/100 | **{delta:+d}** |")
    w("")
    if gone:
        w(f"## {t['gone'].format(n=len(gone))}\n")
        w(t["gone_intro"] + "\n")
        for f in gone:
            w(f"- **{f['title']}** · {dom[f['domain']]} · {t['was']} {sev[f['severity']]} · {t['check']} : {f['verify']}")
        w("")
    if pairs:
        w(f"## {t['still'].format(n=len(pairs))}\n")
        for old, new_f in pairs:
            move = (br.SEV_RANK[new_f["severity"]] - br.SEV_RANK[old["severity"]])
            word = t["sev_same"] if move == 0 else (t["sev_down"] if move < 0 else t["sev_up"])
            w(f"- **{old['title']}** · {dom[old['domain']]} · {sev[old['severity']]} → {sev[new_f['severity']]} ({word})")
        w("")
    if new:
        w(f"## {t['new'].format(n=len(new))}\n")
        for f in new:
            w(f"- **{f['title']}** · {dom[f['domain']]} · {sev[f['severity']]} · {f['observation']}")
        w("")
    if not_audited:
        w(f"## {t['not_audited'].format(n=len(not_audited))}\n")
        w(t["na_intro"] + "\n")
        for f in not_audited:
            w(f"- **{f['title']}** · {dom[f['domain']]} · {sev[f['severity']]}")
        w("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("first", help="findings.json of the earlier audit")
    ap.add_argument("second", help="findings.json of the newer audit, same site")
    ap.add_argument("--out", default="audit-diff.md")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args()
    fa, fb = load_audit(a.first), load_audit(a.second)
    if host_of(fa["meta"]["url"]) != host_of(fb["meta"]["url"]):
        die(f"these are two audits of two different sites ({host_of(fa['meta']['url'])} and {host_of(fb['meta']['url'])}). "
            "A comparison only makes sense between two audits of the same site")
    if str(fb["meta"].get("date", "")) < str(fa["meta"].get("date", "")):
        die(f"the second file's audit date ({fb['meta'].get('date')}) is before the first one's ({fa['meta'].get('date')}). "
            "Give the older audit first: the diff says what changed since then")
    warnings = []
    if fa["meta"].get("scope") != fb["meta"].get("scope"):
        warnings.append(L[fb["meta"].get("language", "en") if fb["meta"].get("language", "en") in L else "en"]["scope_warn"]
                        .format(a=fa["meta"].get("scope"), b=fb["meta"].get("scope")))
    if fa["meta"].get("scope") == "site" and fb["meta"].get("scope") == "site" and (fb["meta"].get("pages_audited") or 0) < (fa["meta"].get("pages_audited") or 0):
        warnings.append(L[fb["meta"].get("language", "en") if fb["meta"].get("language", "en") in L else "en"]["pages_warn"]
                        .format(a=fa["meta"].get("pages_audited"), b=fb["meta"].get("pages_audited")))
    t_warn = L[fb["meta"].get("language", "en") if fb["meta"].get("language", "en") in L else "en"]
    doms_a, doms_b = set(fa["meta"].get("domains_audited") or []), set(fb["meta"].get("domains_audited") or [])
    if doms_a != doms_b:
        warnings.append(t_warn["domains_warn"].format(added=", ".join(sorted(doms_b - doms_a)) or "-",
                                                     dropped=", ".join(sorted(doms_a - doms_b)) or "-"))
    sa = {"scores": br.compute(fa)[0], "overall": br.compute(fa)[1]}
    sb = {"scores": br.compute(fb)[0], "overall": br.compute(fb)[1]}
    pairs, gone, only_new = match(fa.get("findings", []), fb.get("findings", []))
    audited_b = set(fb["meta"].get("domains_audited") or [])
    not_audited = [f for f in gone if f["domain"] not in audited_b]     # computed before gone is filtered
    gone = [f for f in gone if f["domain"] in audited_b]
    lang = fb["meta"].get("language", "en")
    md = render(fb["meta"]["url"], fa, fb, sa, sb, gone, not_audited, pairs, only_new, warnings, lang)
    if br.forbidden_outside_quotes(md):
        print("the comparison contains an em dash outside a quotation, refusing", file=sys.stderr)
        return 2
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(md)
    if a.json_out:
        payload = {"url": fb["meta"]["url"],
                   "first": {"date": fa["meta"]["date"], "scope": fa["meta"].get("scope"), "pages_audited": fa["meta"].get("pages_audited"),
                             "overall": sa["overall"], "scores": sa["scores"]},
                   "second": {"date": fb["meta"]["date"], "scope": fb["meta"].get("scope"), "pages_audited": fb["meta"].get("pages_audited"),
                              "overall": sb["overall"], "scores": sb["scores"]},
                   "warnings": warnings,
                   "no_longer_reported": [{"id": f.get("id"), "title": f["title"], "domain": f["domain"], "severity": f["severity"],
                                            "verify": f["verify"]} for f in gone],
                   "still_reported": [{"id_first": o.get("id"), "id_second": n.get("id"), "title": o["title"], "domain": o["domain"],
                                        "severity_first": o["severity"], "severity_second": n["severity"],
                                        "change": ("same" if br.SEV_RANK[n["severity"]] == br.SEV_RANK[o["severity"]]
                                                   else ("down" if br.SEV_RANK[n["severity"]] < br.SEV_RANK[o["severity"]] else "up"))}
                                       for o, n in pairs],
                   "new": [{"id": f.get("id"), "title": f["title"], "domain": f["domain"], "severity": f["severity"], "observation": f["observation"]}
                           for f in only_new],
                   "not_audited": [{"id": f.get("id"), "title": f["title"], "domain": f["domain"]} for f in not_audited]}
        with open(a.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    warning = safenet.private_output(a.out)
    if warning:
        print(warning, file=sys.stderr)
    print(f"audit diff written: {a.out} ({len(gone)} no longer reported, {len(pairs)} still reported, {len(only_new)} new; "
          f"overall {sa['overall']}/100 -> {sb['overall']}/100)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
