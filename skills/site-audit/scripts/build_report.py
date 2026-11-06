#!/usr/bin/env python3
"""Validate findings.json, compute scores, and render the audit report (stdlib only).

Usage:
    python3 -I build_report.py findings.json [--out report.md] [--json report.json]

The model writes findings.json (see templates/findings.example.json). This script is the quality gate:
it REFUSES a report in which a finding has no evidence, an unknown value, or a domain has no strength, then
computes scores and ranking deterministically so that two audits of the same findings give the same report.

Outputs: report.md (the audit) and action-plan.md (the fix plan: ordered steps, owner, how to verify).
Exit codes: 0 ok, 2 validation errors (nothing written).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redact  # noqa: E402
import safenet  # noqa: E402

CORE_DOMAINS = ("technical", "seo", "performance", "ux", "cro", "copy")   # SKILL.md: the minimum for a marketing page
DOMAINS = {  # id: (weight, fr, en)
    "technical": (12, "Technique et indexation", "Technical and indexability"),
    "seo": (15, "SEO", "SEO"),
    "performance": (15, "Rapidité", "Speed"),
    "accessibility": (8, "Accessibilité", "Accessibility"),
    "ux": (10, "UX et mobile", "UX and mobile"),
    "cro": (15, "Conversion (CRO)", "Conversion (CRO)"),
    "copy": (10, "Copywriting", "Copywriting"),
    "security": (5, "Sécurité", "Security"),
    "privacy_tracking": (5, "Tracking et consentement", "Tracking and consent"),
    "ai_visibility": (5, "Visibilité IA", "AI visibility"),
}
SEV = {"critical": 40, "high": 20, "medium": 8, "low": 3}
SEV_RANK = {"critical": 8, "high": 4, "medium": 2, "low": 1}
IMPACT = {"high": 3, "medium": 2, "low": 1}
EFFORT = {"low": 1, "medium": 2, "high": 3}
CONF_PENALTY = {"measured": 1.0, "deduced": 0.7, "hypothesis": 0.4}
CONF_RANK = {"measured": 1.0, "deduced": 0.8, "hypothesis": 0.5}
OWNERS = {  # id: (fr, en)
    "developer": ("Développeur ou agence web", "Developer or web agency"),
    "marketing": ("Marketing", "Marketing"),
    "content": ("Rédaction ou contenu", "Writer or content"),
    "owner": ("Propriétaire du site", "Site owner"),
    "host": ("Hébergeur ou CDN", "Host or CDN"),
}

MODES = {"agent", "assisted", "human"}      # who applies the fix
RISKS = {"low", "medium", "high"}           # reversibility and blast radius
NEED_KINDS = {"access", "info", "content", "decision"}
CHECK_TYPES = {"wp", "ssh", "ftp", "files"}   # the commands of access_check.py
NEED_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
FINDING_ID = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
DEPTHS = {"external", "external_internal"}   # outside view only, or outside view plus read-only access to the back end
LAYERS = {"external", "internal"}            # where a finding's proof comes from

L = {
    "fr": {
        "coverage": "Domaines audités : {n} sur {total}.", "worst": "Si les {k} constats déduits ou hypothétiques se confirment tous : {worst}/100 (contre {now}/100 aujourd'hui).",
        "title": "Audit de {url}", "date": "Date", "scope": "Périmètre", "device": "Appareil", "pages": "Pages auditées",
        "scope_page": "page seule", "scope_site": "site complet (échantillon : {n} pages)", "ro": "Lecture seule : rien n'a été modifié sur le site.",
        "depth": "Profondeur", "depth_external": "externe (ce qu'un visiteur voit)", "depth_internal": "externe + interne (accès en lecture : {acc})", "internal_tag": "interne",
        "objective": "Objectif de la page", "given": "donné", "inferred": "déduit, à confirmer",
        "verdict": "Verdict", "global": "Score global", "indic": "Scores indicatifs, calculés à partir des constats (méthode en bas de page).",
        "domain": "Domaine", "score": "Score", "works": "Ce qui marche", "top": "Les priorités", "detail": "Détail par domaine",
        "problems": "Problèmes à traiter", "nothing": "Aucun problème relevé.", "plan": "Plan d'action", "week": "Cette semaine",
        "month": "Ce mois-ci", "later": "Ensuite", "nm": "Non mesuré et limites", "method": "Méthode et preuves", "evidence": "Preuve",
        "action": "Action", "effort": "Effort", "impact": "Impact", "confidence": "Confiance", "where": "Pages",
        "sev": {"critical": "Critique", "high": "Élevée", "medium": "Moyenne", "low": "Faible"},
        "lvl": {"low": "faible", "medium": "moyen", "high": "élevé"},
        "conf": {"measured": "mesuré", "deduced": "déduit", "hypothesis": "hypothèse"},
        "plan_title": "Plan d'action : {url}", "plan_intro": "Basé sur l'audit du {date}. Score actuel : {score}/100. {n} actions : {a} cette semaine, {b} ce mois-ci, {c} ensuite. Coche chaque case une fois la correction faite et vérifiée.",
        "plan_week": "Cette semaine : gains rapides", "plan_month": "Ce mois-ci", "plan_later": "Ensuite", "owner": "Responsable", "why": "Pourquoi", "todo": "À faire", "verify": "Comment vérifier",
        "goal": "Objectif", "after": "Après les corrections", "after_txt": "Relance l'audit sur les mêmes pages avec le même périmètre et compare : les constats corrigés doivent disparaître et les scores monter. Score avant : {score}/100.", "see_plan": "Le plan détaillé, étape par étape, avec responsable et vérification, est dans `action-plan.md`.",
        "empty": "Aucune action dans cette phase.",
        "exec": "Exécution", "risk_word": "risque", "need": "Il faut", "nothing_more": "rien de plus", "rollback": "Retour arrière",
        "mode": {"agent": "l'agent applique après ton GO", "assisted": "l'agent prépare, quelqu'un applique", "human": "à faire par un humain"},
        "risk": {"low": "faible", "medium": "moyen", "high": "élevé"},
        "kind": {"access": "accès", "info": "information", "content": "contenu à fournir", "decision": "décision"},
        "needs_title": "Ce que l'agent doit recevoir de toi", "needs_intro": "Pour appliquer le plan, l'agent a besoin de ces éléments. Il te les demande en une fois avant de commencer. Si un élément manque ou ne marche plus en cours de route, il s'arrête sur cette action, te le redemande et passe aux suivantes seulement si tu le décides.", "needs_none": "L'agent n'a besoin de rien de plus.", "actions_word": "actions", "action_word": "action",
        "run_title": "Faire appliquer ce plan par l'agent",
        "run_txt": ["Dis : « applique le plan d'action ».", "L'agent traite les actions par ordre de priorité (le numéro devant chaque action).", "Il ne commence une action que s'il a tout ce qu'il lui faut. Sinon il te demande le complément, avec la liste ci-dessous.", "Pour chaque action prête, il te montre ce qu'il va changer, le risque et le retour arrière, et attend ton GO. Rien n'est appliqué sans GO.", "Après chaque action, il vérifie le résultat avec « Comment vérifier » puis coche la case."],
        "method_txt": "Chaque constat porte une preuve, une gravité, un effort, un impact et un niveau de confiance. Score d'un domaine = 100 moins la somme des pénalités (critique 40, élevée 20, moyenne 8, faible 3), réduites à 70 % si le constat est déduit et à 40 % si c'est une hypothèse (le rapport donne aussi le score si tous ces constats incertains se confirmaient). Le score global est la moyenne pondérée des domaines audités. Une priorité est classée selon gravité x impact / effort, pondérée par la confiance.",
    },
    "en": {
        "coverage": "Domains audited: {n} of {total}.", "worst": "If the {k} deduced or hypothetical findings all turn out true: {worst}/100 (against {now}/100 today).",
        "title": "Audit of {url}", "date": "Date", "scope": "Scope", "device": "Device", "pages": "Pages audited",
        "scope_page": "single page", "scope_site": "whole site (sample: {n} pages)", "ro": "Read-only: nothing was modified on the site.",
        "depth": "Depth", "depth_external": "external (what a visitor sees)", "depth_internal": "external + internal (read-only access: {acc})", "internal_tag": "internal",
        "objective": "Page objective", "given": "provided", "inferred": "inferred, to be confirmed",
        "verdict": "Verdict", "global": "Overall score", "indic": "Indicative scores computed from the findings (method at the bottom).",
        "domain": "Domain", "score": "Score", "works": "What works", "top": "Top priorities", "detail": "Detail by domain",
        "problems": "Problems to fix", "nothing": "No problem found.", "plan": "Action plan", "week": "This week",
        "month": "This month", "later": "Later", "nm": "Not measured and limits", "method": "Method and evidence", "evidence": "Evidence",
        "action": "Action", "effort": "Effort", "impact": "Impact", "confidence": "Confidence", "where": "Pages",
        "sev": {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"},
        "lvl": {"low": "low", "medium": "medium", "high": "high"},
        "conf": {"measured": "measured", "deduced": "deduced", "hypothesis": "hypothesis"},
        "plan_title": "Action plan: {url}", "plan_intro": "Based on the audit of {date}. Current score: {score}/100. {n} actions: {a} this week, {b} this month, {c} later. Tick each box once the fix is done and verified.",
        "plan_week": "This week: quick wins", "plan_month": "This month", "plan_later": "Later", "owner": "Owner", "why": "Why", "todo": "To do", "verify": "How to verify",
        "goal": "Goal", "after": "After the fixes", "after_txt": "Rerun the audit on the same pages with the same scope and compare: fixed findings should be gone and scores higher. Score before: {score}/100.", "see_plan": "The detailed plan, step by step, with owner and verification, is in `action-plan.md`.",
        "empty": "No action in this phase.",
        "exec": "Execution", "risk_word": "risk", "need": "Needs", "nothing_more": "nothing more", "rollback": "Rollback",
        "mode": {"agent": "the agent applies after your GO", "assisted": "the agent prepares, someone applies", "human": "a human does it"},
        "risk": {"low": "low", "medium": "medium", "high": "high"},
        "kind": {"access": "access", "info": "information", "content": "content to provide", "decision": "decision"},
        "needs_title": "What the agent needs from you", "needs_intro": "To apply the plan, the agent needs these items. It asks for them once, before starting. If one is missing or stops working halfway, it stops on that action, asks you again, and only moves on if you decide so.", "needs_none": "The agent needs nothing more.", "actions_word": "actions", "action_word": "action",
        "run_title": "Have the agent apply this plan",
        "run_txt": ["Say: \"apply the action plan\".", "The agent works through the actions in priority order (the number in front of each action).", "It only starts an action when it has everything it needs. Otherwise it asks you for the missing piece, using the list below.", "For each ready action it shows what it will change, the risk and the rollback, and waits for your GO. Nothing is applied without a GO.", "After each action it checks the result with \"How to verify\", then ticks the box."],
        "method_txt": "Every finding carries evidence, severity, effort, impact and a confidence level. Domain score = 100 minus the sum of penalties (critical 40, high 20, medium 8, low 3), reduced to 70% when deduced and 40% when a hypothesis (the report also gives the score if all those uncertain findings turn out true). The overall score is the weighted mean of the audited domains. Priorities are ranked by severity x impact / effort, weighted by confidence.",
    },
}
FORBIDDEN = "\u2014"  # em dash: never in deliverables we publish


def _texts(node, path="$"):
    """Every string of the findings file with its path, so a refusal tells where the value is."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _texts(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _texts(v, f"{path}[{i}]")


def _singular(text):
    """The templates are written for several items: one item reads right as well."""
    for many, one in (("Si les 1 constats déduits ou hypothétiques se confirment tous", "Si le constat déduit ou hypothétique se confirme"),
                      ("If the 1 deduced or hypothetical findings all turn out true", "If the deduced or hypothetical finding turns out true"),
                      (" 1 actions :", " 1 action :"), (" 1 actions:", " 1 action:")):
        text = text.replace(many, one)
    return text


def validate(d):
    errs, warns = [], []
    if not isinstance(d, dict):
        return ["the findings file must be a JSON object with meta, findings and strengths"], warns
    meta = d.get("meta")
    if not isinstance(meta, dict):
        return ["meta: missing object"], warns
    for key in ("findings", "strengths"):
        items = d.get(key, [])
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            errs.append(f"{key}: must be a list of objects")
    if not isinstance(meta.get("domains_audited", []), list):
        errs.append("meta.domains_audited: must be a list of domain ids")
    if errs:
        return errs, warns
    for k in ("url", "scope", "date", "verdict", "domains_audited"):
        if not meta.get(k):
            errs.append(f"meta.{k}: required")
    if meta.get("scope") not in ("page", "site"):
        errs.append("meta.scope: must be 'page' or 'site'")
    if meta.get("scope") == "site" and not meta.get("pages_audited"):
        errs.append("meta.pages_audited: required when scope is 'site'")
    if meta.get("objective") and meta.get("objective_source") not in ("given", "inferred"):
        errs.append("meta.objective_source: 'given' or 'inferred'")
    depth = meta.get("audit_depth", "external")
    if depth not in DEPTHS:
        errs.append(f"meta.audit_depth: one of {', '.join(sorted(DEPTHS))}")
    if depth == "external_internal":
        ia = meta.get("internal_access")
        if not isinstance(ia, list) or not [x for x in ia if str(x).strip()]:
            errs.append("meta.internal_access: required when audit_depth is 'external_internal': list the accesses access_check.py confirmed (for example 'ssh', 'wp'). No verified access means the audit is 'external'.")
    audited = meta.get("domains_audited") or []
    for dom in audited:
        if dom not in DOMAINS:
            errs.append(f"meta.domains_audited: unknown domain '{dom}' (allowed: {', '.join(DOMAINS)})")
    left_out = [dom for dom in CORE_DOMAINS if dom not in audited and not any(re.match(rf"\s*{re.escape(dom)}\s*:", str(x).lower()) for x in (d.get("not_measured") or []))]
    if left_out:
        warns.append(f"domains left out without a word: {', '.join(left_out)}. A marketing page is audited on {', '.join(CORE_DOMAINS)}; "
                     "audit the missing ones, or name each in not_measured with the reason (for example 'performance: Lighthouse not installed')")
    findings = d.get("findings", [])
    strengths = d.get("strengths", [])
    seen_ids = set()
    need_registry = {}
    for i, f in enumerate(findings, 1):
        tag = f"findings[{i}] '{(f.get('title') or '?')[:40]}'"
        for k in ("domain", "title", "severity", "effort", "impact", "confidence", "observation", "evidence", "action"):
            if not str(f.get(k, "")).strip():
                errs.append(f"{tag}: '{k}' is required")
        if f.get("domain") not in DOMAINS:
            errs.append(f"{tag}: unknown domain '{f.get('domain')}'")
        if f.get("layer") is not None and f.get("layer") not in LAYERS:
            errs.append(f"{tag}: layer must be 'external' or 'internal'")
        if f.get("layer") == "internal" and depth != "external_internal":
            errs.append(f"{tag}: layer 'internal' but meta.audit_depth is not 'external_internal': an internal finding needs a verified access")
        elif f["domain"] not in audited:
            errs.append(f"{tag}: domain '{f['domain']}' is not listed in meta.domains_audited")
        if f.get("severity") not in SEV:
            errs.append(f"{tag}: severity must be one of {list(SEV)}")
        if f.get("effort") not in EFFORT:
            errs.append(f"{tag}: effort must be one of {list(EFFORT)}")
        if f.get("impact") not in IMPACT:
            errs.append(f"{tag}: impact must be one of {list(IMPACT)}")
        if f.get("confidence") not in CONF_PENALTY:
            errs.append(f"{tag}: confidence must be one of {list(CONF_PENALTY)}")
        steps = f.get("fix_steps")
        if not isinstance(steps, list) or not steps or not all(isinstance(x, str) and x.strip() for x in steps):
            errs.append(f"{tag}: 'fix_steps' must be a non-empty list of concrete steps")
        elif len(steps) > 8:
            warns.append(f"{tag}: {len(steps)} fix steps: split the finding or shorten")
        if not str(f.get("verify", "")).strip():
            errs.append(f"{tag}: 'verify' is required (how to confirm the fix worked, with a threshold or a command)")
        if f.get("owner") not in OWNERS:
            errs.append(f"{tag}: owner must be one of {list(OWNERS)}")
        ev = str(f.get("evidence", ""))
        floor = {"measured": 8, "deduced": 12, "hypothesis": 8}.get(f.get("confidence"), 8)
        if len(ev.strip()) < floor:
            errs.append(f"{tag}: the evidence is too short to be one (at least {floor} characters: what was seen, where)")
        if f.get("confidence") == "measured" and not (re.search(r"\d|\.(?:json|jsonl|png|html|md|txt)\b|\b[A-Za-z][A-Za-z-]+:\s*\S", ev) and len(ev.split()) >= 3):
            errs.append(f"{tag}: a 'measured' finding must say what was seen and where, with a value or the file it comes from (a number, a header and its value, a file name), in at least 3 words: a bare file name or 'header absent' is not a proof")
        if f.get("severity") == "critical" and f.get("confidence") == "hypothesis":
            warns.append(f"{tag}: critical severity on a hypothesis: verify it before reporting")
        fid = f.get("id")
        if not isinstance(fid, str) or not FINDING_ID.match(fid):
            errs.append(f"{tag}: 'id' is required (letters, digits, - or _, 20 characters max, for example F1)")
        else:
            if fid in seen_ids:
                errs.append(f"{tag}: duplicate id '{fid}'")
            seen_ids.add(fid)
        ex = f.get("execution")
        if not isinstance(ex, dict):
            errs.append(f"{tag}: 'execution' is required: {{mode, risk, needs, rollback}}")
        else:
            if ex.get("mode") not in MODES:
                errs.append(f"{tag}: execution.mode must be one of {sorted(MODES)}")
            if ex.get("risk") not in RISKS:
                errs.append(f"{tag}: execution.risk must be one of {sorted(RISKS)}")
            if ex.get("risk") in ("medium", "high") and ex.get("mode") != "human" and not str(ex.get("rollback", "")).strip():
                errs.append(f"{tag}: execution.rollback is required when risk is medium or high")
            needs = ex.get("needs")
            if not isinstance(needs, list):
                errs.append(f"{tag}: execution.needs must be a list (empty if nothing is needed)")
                needs = []
            for k, nd in enumerate(needs, 1):
                nt = f"{tag} needs[{k}]"
                if not isinstance(nd, dict) or not NEED_ID.match(str(nd.get("id", ""))):
                    errs.append(f"{nt}: 'id' required, lowercase snake_case (for example wp_admin_access)")
                    continue
                if nd.get("kind") not in NEED_KINDS:
                    errs.append(f"{nt}: kind must be one of {sorted(NEED_KINDS)}")
                if not str(nd.get("what", "")).strip():
                    errs.append(f"{nt}: 'what' is required (say exactly what the agent must receive)")
                if nd.get("check_type") is not None and nd.get("check_type") not in CHECK_TYPES:
                    errs.append(f"{nt}: check_type must be one of {sorted(CHECK_TYPES)} (the access_check.py command that proves this access), or absent")
                prev = need_registry.setdefault(nd["id"], (nd.get("kind"), bool(nd.get("secret"))))
                if prev != (nd.get("kind"), bool(nd.get("secret"))):
                    errs.append(f"{nt}: need '{nd['id']}' is declared elsewhere with a different kind or secret flag: reuse one definition")
            if ex.get("mode") == "agent" and not str(meta.get("agent_access", "")).strip():
                warns.append(f"{tag}: mode 'agent' but meta.agent_access is empty: the agent has no declared way to apply it, use 'assisted'")
            if ex.get("mode") == "agent" and not any(isinstance(n, dict) and n.get("kind") == "access" for n in needs):
                warns.append(f"{tag}: mode 'agent' but no 'access' need: how will the agent apply it? Use 'assisted' if it cannot")
    for i, s in enumerate(strengths, 1):
        tag = f"strengths[{i}]"
        if s.get("domain") not in DOMAINS:
            errs.append(f"{tag}: unknown domain '{s.get('domain')}'")
        if not str(s.get("text", "")).strip() or not str(s.get("evidence", "")).strip():
            errs.append(f"{tag}: 'text' and 'evidence' are required (a strength is a verified fact, not a compliment)")
    for dom in audited:
        if dom in DOMAINS and not any(s.get("domain") == dom for s in strengths):
            errs.append(f"domain '{dom}' is audited but lists no strength: look for what works and prove it, or remove the domain")
    # Nothing secret and, for an internal audit, nothing personal goes into a document that is meant to be shared.
    internal = meta.get("audit_depth") == "external_internal"
    for path, text in _texts(d):
        secrets, personal = redact.sensitive_kinds(text)
        if secrets:
            errs.append(f"{path}: contains what looks like a secret ({', '.join(secrets)}): mask it with redact.py or describe it without the value")
        if personal:
            msg = f"{path}: contains personal data ({', '.join(personal)}): an email address, an IP address or a phone number. Aggregate (a count, a role) or mask it"
            (errs if internal else warns).append(msg + ("" if internal else " (public contact details of the audited site are tolerated in an outside audit; check it is not someone's private data)"))
    blob = json.dumps(d, ensure_ascii=False)
    if FORBIDDEN in blob:
        errs.append("text contains an em dash (U+2014): replace it with a colon, a comma or a period")
    if meta.get("scope") == "page" and any("pages" in f and len(f.get("pages") or []) > 1 for f in findings):
        warns.append("scope is 'page' but a finding lists several pages")
    return errs, warns


def compute(d):
    meta, findings = d["meta"], d.get("findings", [])
    audited = meta["domains_audited"]
    scores = {}
    for dom in audited:
        pen = sum(SEV[f["severity"]] * CONF_PENALTY[f["confidence"]] for f in findings if f["domain"] == dom)
        scores[dom] = max(0, round(100 - pen))
    wsum = sum(DOMAINS[x][0] for x in audited)
    overall = round(sum(scores[x] * DOMAINS[x][0] for x in audited) / wsum) if wsum else 0
    ranked = []
    for i, f in enumerate(findings, 1):
        r = SEV_RANK[f["severity"]] * IMPACT[f["impact"]] / EFFORT[f["effort"]] * CONF_RANK[f["confidence"]]
        ranked.append((r, i, f))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    top = [f for _, _, f in ranked[:5]]
    week = [f for _, _, f in ranked if f["effort"] == "low" and f["impact"] in ("medium", "high")]
    ids = {id(x) for x in week}
    month = [f for _, _, f in ranked if id(f) not in ids and (f["severity"] in ("critical", "high") or f["impact"] == "high" or (f["effort"] == "medium" and f["impact"] == "medium"))]
    ids |= {id(x) for x in month}
    later = [f for _, _, f in ranked if id(f) not in ids]
    return scores, overall, ranked, top, {"week": week, "month": month, "later": later}


def score_if_confirmed(d):
    """Overall score if every deduced finding and every hypothesis turned out to be true (all penalties at full weight).

    The published score discounts uncertain findings (70% and 40%), so lowering a finding's confidence raises the
    score. Showing this figure next to it keeps that honest: the gap is the price of what is not yet proven.
    """
    audited = d["meta"]["domains_audited"]
    sc = {dom: max(0, round(100 - sum(SEV[f["severity"]] for f in d.get("findings", []) if f["domain"] == dom))) for dom in audited}
    wsum = sum(DOMAINS[x][0] for x in audited)
    return round(sum(sc[x] * DOMAINS[x][0] for x in audited) / wsum) if wsum else 0


def bar(n, width=10):
    k = round(n / 100 * width)
    return "█" * k + "░" * (width - k)


def render(d, scores, overall, top, plan):
    meta = d["meta"]
    lang = meta.get("language", "en") if meta.get("language") in L else "en"
    t = L[lang]
    findings, strengths = d.get("findings", []), d.get("strengths", [])
    out = []
    w = out.append
    w(f"# {t['title'].format(url=meta['url'])}\n")
    scope = t["scope_page"] if meta["scope"] == "page" else t["scope_site"].format(n=meta.get("pages_audited"))
    w(f"{t['date']}: {meta['date']} · {t['scope']}: {scope} · {t['device']}: {meta.get('device', 'mobile')}  ")
    if meta.get("audit_depth") == "external_internal":
        w(f"{t['depth']}: " + t["depth_internal"].format(acc=", ".join(str(x) for x in meta.get("internal_access", []))) + "  ")
    else:
        w(f"{t['depth']}: {t['depth_external']}  ")
    w(f"{t['ro']}\n")
    if meta.get("objective"):
        w(f"**{t['objective']}** : {meta['objective']} ({t['given'] if meta.get('objective_source') == 'given' else t['inferred']})\n")
    w(f"## 1. {t['verdict']}\n\n{meta['verdict']}\n")
    w(f"## 2. {t['global']} : {overall}/100\n\n{t['indic']}\n")
    worst = score_if_confirmed(d)
    uncertain = sum(1 for f in findings if f["confidence"] != "measured")
    w(t["coverage"].format(n=len(meta["domains_audited"]), total=len(DOMAINS)) + (" " + _singular(t["worst"].format(worst=worst, now=overall, k=uncertain)) if uncertain and worst != overall else "") + "\n")
    w(f"| {t['domain']} | {t['score']} | |\n|---|---|---|")
    for dom in meta["domains_audited"]:
        w(f"| {DOMAINS[dom][1 if lang == 'fr' else 2]} | {scores[dom]}/100 | `{bar(scores[dom])}` |")
    w("")
    w(f"## 3. {t['works']}\n")
    for dom in meta["domains_audited"]:
        items = [s for s in strengths if s["domain"] == dom]
        if items:
            w(f"**{DOMAINS[dom][1 if lang == 'fr' else 2]}**")
            for s in items:
                w(f"- {s['text']} _({t['evidence']} : {s['evidence']})_")
            w("")

    def card(f, n=None, heading=True):
        lines = []
        head = f"{n}. {f['title']}" if n else f['title']
        if heading:
            lines.append(f"### {head}  \n`{t['sev'][f['severity']]}` · {DOMAINS[f['domain']][1 if lang == 'fr' else 2]}" + (f" · {t['internal_tag']}" if f.get("layer") == "internal" else "") + "\n")
        lines.append(f"{f['observation']}\n")
        lines.append(f"- **{t['evidence']}** : {f['evidence']}")
        lines.append(f"- **{t['action']}** : {f['action']}")
        lines.append(f"- **{t['effort']}** : {t['lvl'][f['effort']]} · **{t['impact']}** : {t['lvl'][f['impact']]} · **{t['confidence']}** : {t['conf'][f['confidence']]}")
        if f.get("pages"):
            lines.append(f"- **{t['where']}** : " + ", ".join(f['pages'][:6]) + (" …" if len(f['pages']) > 6 else ""))
        lines.append("")
        return "\n".join(lines)

    w(f"## 4. {t['top']}\n")
    for n, f in enumerate(top, 1):
        w(card(f, n))
    w(f"## 5. {t['detail']}\n")
    for dom in meta["domains_audited"]:
        name = DOMAINS[dom][1 if lang == 'fr' else 2]
        w(f"### {name} : {scores[dom]}/100\n")
        fl = [f for f in findings if f["domain"] == dom]
        w(f"**{t['problems']}**\n")
        if not fl:
            w(f"{t['nothing']}\n")
        for f in sorted(fl, key=lambda x: -SEV_RANK[x["severity"]]):
            w(f"- `{t['sev'][f['severity']]}` **{f['title']}** : {f['observation']} _({t['evidence']} : {f['evidence']})_ → {f['action']}")
        w("")
    w(f"## 6. {t['plan']}\n")
    w(t["see_plan"] + "\n")
    for key in ("week", "month", "later"):
        w(f"**{t[key]}**")
        if plan[key]:
            for f in plan[key]:
                w(f"- {f['title']} ({t['owner']} : {OWNERS[f['owner']][0 if lang == 'fr' else 1]}, {t['effort']} {t['lvl'][f['effort']]}, {t['impact']} {t['lvl'][f['impact']]})")
        else:
            w("- –")
        w("")
    w(f"## 7. {t['nm']}\n")
    for x in d.get("not_measured", []) or ["–"]:
        w(f"- {x}")
    w("")
    w(f"## 8. {t['method']}\n")
    w(t["method_txt"] + "\n")
    if meta.get("sources"):
        w("Sources : " + ", ".join(f"`{s}`" for s in meta["sources"]) + "\n")
    return "\n".join(out)


def priority_map(d):
    """finding id -> priority number (1 = most urgent), the same ranking as the report."""
    ranked = compute(d)[2]
    return {f["id"]: n for n, (_, _, f) in enumerate(ranked, 1)}


def collect_needs(d):
    """need id -> {kind, what, secret, findings:[ids]} for actions an agent may do (not human-only)."""
    reg = {}
    for f in d.get("findings", []):
        ex = f["execution"]
        if ex["mode"] == "human":
            continue
        for nd in ex["needs"]:
            r = reg.setdefault(nd["id"], {"kind": nd["kind"], "what": nd["what"], "secret": bool(nd.get("secret")), "check_type": nd.get("check_type"), "findings": []})
            r["findings"].append(f["id"])
    return reg


def render_plan(d, overall, plan):
    meta = d["meta"]
    lang = meta.get("language", "en") if meta.get("language") in L else "en"
    t = L[lang]
    i = 0 if lang == "fr" else 1
    prio = priority_map(d)
    out = []
    w = out.append
    a, b, c = len(plan["week"]), len(plan["month"]), len(plan["later"])
    w(f"# {t['plan_title'].format(url=meta['url'])}\n")
    w(_singular(t["plan_intro"].format(date=meta["date"], score=overall, n=a + b + c, a=a, b=b, c=c)) + "\n")
    w(f"## {t['run_title']}\n")
    for k, line in enumerate(t["run_txt"], 1):
        w(f"{k}. {line}")
    w("")
    w(f"## {t['needs_title']}\n")
    needs = collect_needs(d)
    if not needs:
        w(t["needs_none"] + "\n")
    else:
        w(t["needs_intro"] + "\n")
        for nid, r in sorted(needs.items(), key=lambda kv: min(prio[x] for x in kv[1]["findings"])):
            nums = ", ".join(str(n) for n in sorted(prio[x] for x in r["findings"]))
            word = t["action_word"] if len(r["findings"]) == 1 else t["actions_word"]
            w(f"- **{t['kind'][r['kind']]}** · `{nid}` : {r['what']} ({word} {nums})")
        w("")
    for key, head in (("week", "plan_week"), ("month", "plan_month"), ("later", "plan_later")):
        w(f"## {t[head]}\n")
        if not plan[key]:
            w(t["empty"] + "\n")
        for f in plan[key]:
            ex = f["execution"]
            w(f"### - [ ] {prio[f['id']]}. {f['title']} ({f['id']})\n")
            w(f"`{t['sev'][f['severity']]}` · {DOMAINS[f['domain']][1 + i]} · **{t['owner']}** : {OWNERS[f['owner']][i]} · {t['effort']} {t['lvl'][f['effort']]} · {t['impact']} {t['lvl'][f['impact']]}\n")
            w(f"**{t['goal']}** : {f['action']}\n")
            w(f"**{t['why']}** : {f['observation']}\n")
            w(f"**{t['todo']}**\n")
            for k, step in enumerate(f["fix_steps"], 1):
                w(f"{k}. {step}")
            w("")
            w(f"**{t['verify']}** : {f['verify']}\n")
            w(f"**{t['exec']}** : {t['mode'][ex['mode']]} · {t['risk_word']} {t['risk'][ex['risk']]}")
            need_txt = ", ".join(f"`{n['id']}` ({t['kind'][n['kind']]})" for n in ex["needs"]) or t["nothing_more"]
            w(f"**{t['need']}** : {need_txt}")
            if str(ex.get("rollback", "")).strip():
                w(f"**{t['rollback']}** : {ex['rollback']}")
            w("")
            if f.get("pages"):
                w(f"**{t['where']}** : " + ", ".join(f["pages"][:8]) + (" …" if len(f["pages"]) > 8 else "") + "\n")
    w(f"## {t['after']}\n")
    w(t["after_txt"].format(score=overall) + "\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("findings")
    ap.add_argument("--out", default="report.md")
    ap.add_argument("--json", dest="json_out", default=None)
    ap.add_argument("--plan", default=None, help="action plan path (default: action-plan.md next to --out)")
    ap.add_argument("--overwrite-plan", action="store_true", help="replace an action plan that already has ticked boxes (progress is lost)")
    a = ap.parse_args()
    try:
        d = json.load(open(a.findings, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {a.findings}: {e}", file=sys.stderr)
        return 2
    try:
        errs, warns = validate(d)
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        print(f"the findings file is malformed ({type(e).__name__}: {e}); report NOT written", file=sys.stderr)
        return 2
    for w_ in warns:
        print("WARNING:", w_, file=sys.stderr)
    if errs:
        print(f"{len(errs)} validation error(s), report NOT written:", file=sys.stderr)
        for e in errs:
            print(" -", e, file=sys.stderr)
        return 2
    try:
        scores, overall, ranked, top, plan = compute(d)
        md = render(d, scores, overall, top, plan)
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        print(f"the findings file is malformed ({type(e).__name__}: {e}); report NOT written", file=sys.stderr)
        return 2
    if FORBIDDEN in md:
        print("rendered report contains an em dash, refusing", file=sys.stderr)
        return 2
    plan_md = render_plan(d, overall, plan)
    if FORBIDDEN in plan_md:
        print("rendered action plan contains an em dash, refusing", file=sys.stderr)
        return 2
    plan_path = a.plan or os.path.join(os.path.dirname(os.path.abspath(a.out)), "action-plan.md")
    if os.path.exists(plan_path) and not a.overwrite_plan:
        try:
            with open(plan_path, encoding="utf-8") as fh:
                if re.search(r"^### - \[[xX]\]", fh.read(), re.M):
                    print(f"{plan_path} already has ticked boxes (fixes done): nothing written. Use --plan another/path, or --overwrite-plan to start the plan again", file=sys.stderr)
                    return 2
        except OSError:
            pass
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(plan_path, "w", encoding="utf-8") as fh:
        fh.write(plan_md)
    if a.json_out:
        json.dump({"overall": overall, "overall_if_uncertain_findings_confirmed": score_if_confirmed(d), "scores": scores, "top_priorities": [f.get("id") or f["title"] for f in top],
                   "counts": {s: sum(1 for f in d.get("findings", []) if f["severity"] == s) for s in SEV}},
                  open(a.json_out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"action plan written: {plan_path}")
    warning = safenet.private_output(a.out)
    if warning:
        print(warning, file=sys.stderr)
    print(f"report written: {a.out} (overall {overall}/100; {len(d.get('findings', []))} findings, {len(d.get('strengths', []))} strengths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
