"""Does the test suite notice when a rule is broken? Breaks one rule at a time in a COPY of the repository and
runs the tests that are supposed to protect it. A mutant that leaves the tests green is a rule nobody checks.

    python3 -I tests/mutation_check.py            # all mutants (a few minutes)
    python3 -I tests/mutation_check.py M01 M08    # some of them

Exit code 0: every mutant was caught. 1: at least one survived. The file is not named test_*.py on purpose:
unittest discovery does not run it.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SC = "skills/site-audit/scripts/"

# id: (what is broken, file, old text, new text, tests that must go red)
MUTANTS = {
    # Two layers protect the evidence rule (required field, then minimum length): the mutant removes both.
    "M01": ("a finding without evidence is accepted", SC + "build_report.py", [('"observation", "evidence", "action"):', '"observation", "action"):'), ("if len(ev.strip()) < floor:", "if False:")], "", ["test_build_report.py", "test_report_scoring_and_order.py"]),
    "M04": ("critical weight 40 -> 30", SC + "build_report.py", '"critical": 40', '"critical": 30', ["test_report_scoring_and_order.py"]),
    "M06": ("a 'measured' evidence of any length is accepted", SC + "build_report.py", 'if len(ev.strip()) < floor:', 'if False:', ["test_report_scoring_and_order.py"]),
    "M08": ("a GO may skip the priority order", SC + "fix_tracker.py", "if earlier and not a.out_of_order:", "if False:", ["test_report_scoring_and_order.py"]),
    "M16": ("VAT-inclusive and VAT-exclusive prices reported as a conflict", SC + "consistency.py", "if vat_gap(x, y) and any(", "if False and any(", ["test_report_scoring_and_order.py", "test_consistency.py"]),
    "M17": ("a 'from' price reported as a conflict", SC + "consistency.py", 'if any("from" in m["qualifiers"] for m in lowers) and', "if False and", ["test_report_scoring_and_order.py", "test_consistency.py"]),
    "M21": ("ssh host and user are not validated", SC + "access_check.py", "if not HOST_RE.match(a.host or \"\") or not USER_RE.match(a.user or \"\"):", "if False:", ["test_secrets_and_access.py", "test_access_and_lh_site.py"]),
    "M22": ("a GitHub token is not masked", SC + "redact.py", "(?:ghp|gho|ghu|ghs|ghr)_", "(?:NOPE)_", ["test_redact.py"]),
    "M23": ("a JWT is not masked", SC + "redact.py", r"\beyJ[A-Za-z0-9_\-]{8,}", r"\bNOPE[A-Za-z0-9_\-]{8,}", ["test_redact.py"]),
    "M31": ("a sitemap with a DTD or entities is parsed", SC + "crawl.py", 'if re.search(r"<!(DOCTYPE|ENTITY)", r["body"], re.I) or', "if", ["test_hardening.py", "test_crawl.py"]),
    "M40": ("a private address is judged public", SC + "safenet.py", "bad = [a for a in addrs if not _is_public(a)]", "bad = []", ["test_hardening.py", "test_browser_guard_and_robots.py"]),
    "M41": ("the crawler ignores the group written for its own name", SC + "robotsrules.py", "chosen = own or [g for g in groups if \"*\" in g[0]]", "chosen = [g for g in groups if \"*\" in g[0]]", ["test_hardening.py", "test_browser_guard_and_robots.py"]),
    # M42 (click even when no banner was found) was dropped: the same rule is enforced a second time inside the click
    # script, so removing the outer check changes nothing anyone can observe. M43 removes the inner one.
    "M43": ("devtools clicks any button saying refuse, not only the banner's", SC + "devtools.py", "for (const {el, btns} of banners())", "for (const {el, btns} of [{el: document.body, btns: deep(document.body, BTN)}])", ["test_devtools.py"]),
    "M44": ("fix_tracker accepts a token as a note", SC + "fix_tracker.py", "if TOKENISH.search(text) or any(k in redact.HIGH_CONFIDENCE for k in secrets):", "if False:", ["test_secrets_and_access.py"]),
    "M45": ("an agent name is accepted as the owner of the GO", SC + "fix_tracker.py", "if NOT_A_PERSON.search(owner) or OWNER_TOKEN.search(owner):", "if False:", ["test_secrets_and_access.py", "test_guard_proxy_and_tracker.py"]),
    "M46": ("access_check follows a redirect, so it forwards the Authorization header", SC + "access_check.py", "_opener = urllib.request.build_opener(NoRedirect)", "_opener = urllib.request.build_opener()", ["test_secrets_and_access.py"]),
    # M47 only REPLACES the safe call by the unsafe one inside a throwaway copy, to prove that a test notices it.
    "M47": ("FTPS without certificate verification", SC + "access_check.py", "ssl.create_default_context()", "ssl._create_unverified_context()", ["test_secrets_and_access.py"]),
    "M48": ("build_report crashes with a traceback on a malformed file", SC + "build_report.py", "except (KeyError, TypeError, AttributeError, ValueError) as e:", "except ZeroDivisionError as e:", ["test_report_scoring_and_order.py"]),
    "M49": ("a null Google score becomes 0", SC + "psi.py", '(None if v.get("score") is None else round(v["score"] * 100))', 'round((v.get("score") or 0) * 100)', ["test_psi.py"]),
    "M51": ("robots.txt wildcards are not read", SC + "robotsrules.py", 'return anchored, body.split("*")', "return anchored, [body]", ["test_browser_guard_and_robots.py", "test_guard_proxy_and_tracker.py"]),
    "M52": ("a robots.txt answering 503 allows everything", SC + "robotsrules.py", "status >= 500", "status >= 9999", ["test_browser_guard_and_robots.py"]),
    "M53": ("a CGNAT / Tailscale address is judged public", SC + "safenet.py", "return bool(ip.is_global) and not (", "return not (", ["test_browser_guard_and_robots.py"]),
    "M54": ("the browser guard lets every request through", SC + "render.py", "self._verdicts[key] = safenet.browser_refusal(url, self.guard_private)", "self._verdicts[key] = None", ["test_browser_guard_and_robots.py"]),
    "M55": ("a click may navigate or submit after the refuse button", SC + "render.py", 'if (not why and self.block_navigation and', 'if (False and self.block_navigation and', ["test_devtools.py", "test_browser_guard_and_robots.py"]),
    "M56": ("a button tied to a form by form= may be clicked", SC + "devtools.py", "if (el.form || el.closest('form') || el.hasAttribute('form')) return false;", "if (false) return false;", ["test_devtools.py"]),
    "M57": ("a WordPress application password is left in clear", SC + "redact.py", '("wp_app_password", re.compile(r"(?<![A-Za-z0-9])', '("wp_app_password", re.compile(r"(?!)(?<![A-Za-z0-9])', ["test_browser_guard_and_robots.py"]),
    "M58": ("a note that says 'verified' but 'error' is accepted as a proof", SC + "fix_tracker.py", "|errors?|erreurs?|", "|", ["test_secrets_and_access.py"]),
    "M59": ("an access check of any age is a proof", SC + "fix_tracker.py", "if age > 6 * 3600 or age < -300:", "if False:", ["test_secrets_and_access.py"]),
    "M60": ("the GO owner declared at init is not enforced", SC + "fix_tracker.py", "        if not same(by, owner):", "        if False:", ["test_secrets_and_access.py"]),
    "M61": ("a <link rel=canonical> to an http page counts as mixed content", SC + "facts.py", 'if is_link and not re.search(', 'if False and re.search(', ["test_browser_guard_and_robots.py"]),
    "M62": ("a Lighthouse timeout leaves Chrome running", SC + "lh_median.py", "os.killpg(proc.pid, signal.SIGKILL)", "proc.kill()", ["test_browser_guard_and_robots.py"]),
    "M63": ("build_report lets a secret into a report", SC + "build_report.py", "        if secrets:\n", "        if False:\n", ["test_personal_data_and_leaks.py"]),
    "M64": ("an e-mail address is not masked", SC + "redact.py", r'("email", re.compile(r"(?<![\w.+\-])', r'("email", re.compile(r"(?!)(?<![\w.+\-])', ["test_personal_data_and_leaks.py"]),
    "M65": ("an IPv4 address is not masked", SC + "redact.py", r'("ipv4", re.compile(r"(?<![\w.\-])', r'("ipv4", re.compile(r"(?!)(?<![\w.\-])', ["test_personal_data_and_leaks.py"]),
    "M66": ("the audit folder is not protected from git", SC + "safenet.py", "if os.path.isdir(top) and not os.path.exists(gi):", "if False:", ["test_personal_data_and_leaks.py"]),
    "M67": ("--aws-secret-access-key (a prefixed long flag) is not masked", SC + "redact.py", "(--(?:[a-z0-9]+-)*(?:password|passwd", "(--(?:password|passwd", ["test_personal_data_and_leaks.py"]),
    "M68": ("Chrome starts without the filtering proxy", SC + "render.py", "flags = (*flags, *(self.proxy.flags() if self.proxy else ()))", "flags = (*flags,)", ["test_guard_proxy_and_tracker.py"]),
    "M69": ("the proxy connects to the NAME it judged, not to the address (rebinding)", SC + "netguard.py", "return socket.create_connection((a, port), timeout=timeout), None", "return socket.create_connection((host, port), timeout=timeout), None", ["test_guard_proxy_and_tracker.py"]),
    "M70": ("the proxy lets a private address through", SC + "netguard.py", "    else:\n        bad = [a for a in addrs if not safenet._is_public(a)]", "    else:\n        bad = []", ["test_guard_proxy_and_tracker.py"]),
    "M70b": ("a private audit may reach any private address, not only its start host", SC + "netguard.py", "not safenet._is_public(a) and not safenet.private_allowed(a)]", "False]", ["test_guard_proxy_and_tracker.py", "test_private_host_and_evidence_masks.py"]),
    "M71": ("on a tie Disallow wins over Allow", SC + "robotsrules.py", "(length == best[0] and allow and not best[1])", "(False)", ["test_guard_proxy_and_tracker.py", "test_browser_guard_and_robots.py"]),
    "M72": ("a byte order mark hides robots.txt", SC + "robotsrules.py", r'.lstrip("\ufeff")', '.lstrip("")', ["test_guard_proxy_and_tracker.py"]),
    "M73": ("robots.txt answering 429 means everything is allowed", SC + "robotsrules.py", "or status == 429:", "or False:", ["test_guard_proxy_and_tracker.py"]),
    "M74": ("the crawler requests links robots.txt forbids, to check them", SC + "crawl.py", "if u not in pages and allowed(u)][: a.check_links]", "if u not in pages][: a.check_links]", ["test_guard_proxy_and_tracker.py"]),
    "M75": ("the crawler asks for sitemaps although robots.txt answered 5xx", SC + "crawl.py", "if rp.disallow_all and not a.ignore_robots:\n            break", "if False:\n            break", ["test_guard_proxy_and_tracker.py"]),
    "M76": ("psi.py says ok after a failed call", SC + "psi.py", 'if problems and res["status"] == "ok":', "if False:", ["test_guard_proxy_and_tracker.py"]),
    "M77": ("a Lighthouse run without a score is counted", SC + "lh_median.py", 'if d.get("runtimeError") or (d.get("categories", {}).get("performance") or {}).get("score") is None:', "if False:", ["test_guard_proxy_and_tracker.py"]),
    "M78": ("defer needs no name", SC + "fix_tracker.py", 'by = person(st, a.by, "the decision to skip it")', 'by = a.by or "x"', ["test_guard_proxy_and_tracker.py"]),
    "M79": ("two actions may be approved at the same time", SC + "fix_tracker.py", "    if busy:\n", "    if False:\n", ["test_guard_proxy_and_tracker.py"]),
    "M80": ("init accepts no owner (both layers: the option and the check)", SC + "fix_tracker.py", [('("--owner", {"required": True,', '("--owner", {"required": False,'), ("    if not owner:\n        die(\"--owner is required", "    if False:\n        die(\"--owner is required")], "", ["test_guard_proxy_and_tracker.py"]),
    "M90": ("a host name that resolves to a private address switches the guard off", SC + "safenet.py", 'if low == "localhost" or low.endswith(".localhost") or (named and named == low):', "if True:", ["test_hardening.py", "test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M91": ("crawler workers have no shared clock", SC + "crawl.py", "at = max(now, self._next)", "at = now", ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M92": ("the proxy forwards what was pipelined behind a request", SC + "netguard.py", "body = rest[:length]", "body = rest", ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M93": ("the response head has no total deadline", SC + "facts.py", "r = _open_by_deadline(req, timeout, timeout)", "r = _opener.open(req, timeout=timeout)", ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M94": ("a redirect target is not checked against robots.txt", SC + "facts.py", "refusal = hop_check(nxt) if hop_check else None", "refusal = None", ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M96": ("one strategy answering still ends as no_key", SC + "psi.py", 'if not any(x.get("lab") for x in res["strategies"].values()):\n            res.update(status="no_key"', 'if True:\n            res.update(status="no_key"', ["test_pacing_redirects_psi_and_proxy_reuse.py", "test_psi.py"]),
    "M97": ("hours and days are not compared in one unit", SC + "consistency.py", 'if (r["unit"] == q["unit"] or (r["hours"] is not None and q["hours"] is not None)) and sh', 'if r["unit"] == q["unit"] and sh', ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M98": ("a label before a colon is cut off the price", SC + "consistency.py", r":(?=\s)(?!\s*(?:\d|[€$£]))", r":(?=\s)", ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M99": ("a button saying refuse and accept is clicked as the refuse button", SC + "devtools.py", r'optionnels?))?\s*[.!]?\s*$", re.I)', r'optionnels?))?\b", re.I)', ["test_pacing_redirects_psi_and_proxy_reuse.py", "test_devtools.py"]),
    "M100": ("a .gitignore is written in any folder whose name starts with site-audit-", SC + "safenet.py", "if AUDIT_FOLDER.match(part):", 'if part.startswith("site-audit-"):', ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M101": ("link-local (cloud metadata) is reachable from a private audit", SC + "safenet.py", "if ip.is_link_local or ip.is_multicast or ip.is_unspecified:", "if False:", ["test_private_host_and_evidence_masks.py"]),
    "M102": ("a password inside an XML element is not masked", SC + "redact.py", '(<(?P<t>" + NAME', '(<(?P<t>NOPE" + NAME', ["test_pacing_redirects_psi_and_proxy_reuse.py", "test_private_host_and_evidence_masks.py"]),
    "M103": ("the build gate refuses a sentence that only mentions a token", SC + "redact.py", 'return len(v) >= 6 and (', 'return True or (', ["test_pacing_redirects_psi_and_proxy_reuse.py"]),
    "M104": ("a refused --force init resets the state before checking the owner", SC + "fix_tracker.py", 'if NOT_A_PERSON.search(owner) or OWNER_TOKEN.search(owner):\n        die("--owner must be the name of a person', 'if NOT_A_PERSON.search(owner) and False:\n        die("--owner must be the name of a person', ["test_pacing_redirects_psi_and_proxy_reuse.py", "test_secrets_and_access.py"]),
    "M110": ("the crawler's redirect check no longer applies robots.txt", SC + "crawl.py", 'return None if allowed(u) else "redirect to a URL that robots.txt forbids"', "return None", ["test_robots_cleanup_and_linear_masking.py"]),
    "M111": ("a link behind a forbidden redirect is requested again with GET", SC + "crawl.py", 'if r["status"] == 0 and "robots.txt forbids" in str(r.get("error") or ""):', "if False:", ["test_robots_cleanup_and_linear_masking.py"]),
    "M112b": ("no process is ever stopped by the folder it works in", SC + "netguard.py", "if marker in args and pid.isdigit() and int(pid) != os.getpid():", "if False:", ["test_robots_cleanup_and_linear_masking.py"]),
    "M113": ("the tool runs Lighthouse with the usual, possibly long, TMPDIR", SC + "netguard.py", 'return tempfile.mkdtemp(prefix=prefix, dir=base)', 'return tempfile.mkdtemp(prefix=prefix)', ["test_robots_cleanup_and_linear_masking.py"]),
    "M114": ("a JSON answer that is not an object is accepted", SC + "psi.py", "return j if isinstance(j, dict) else None", "return j", ["test_robots_cleanup_and_linear_masking.py"]),
    "M115": ("the proxy waits for the upstream to close after a complete response", SC + "netguard.py", "while announced is None or sent < announced:", "while True:", ["test_robots_cleanup_and_linear_masking.py"]),
    "M116": ("a name only has to start at a word boundary again (quadratic)", SC + "redact.py", 'NAME_START = r"(?<![A-Za-z0-9_.\\-])"', 'NAME_START = r"\\b"', ["test_robots_cleanup_and_linear_masking.py"]),
    "M117": ("a cookie header may span blank lines (quadratic)", SC + "redact.py", "(?im)^([ \\t]*(set-)?cookie[ \\t]*:[ \\t]*)(.+)$", "(?im)^(\\s*(set-)?cookie\\s*:\\s*)(.+)$", ["test_robots_cleanup_and_linear_masking.py"]),
    "M118": ("a sentence mentioning user_login erases the lines after it", SC + "redact.py", "if not ((len(cells) >= 2", "if False and not ((len(cells) >= 2", ["test_robots_cleanup_and_linear_masking.py"]),
    "M119": ("any number and street word with a capital further on is an address, even a sentence", SC + "redact.py", 'if re.search(r"\\b[A-ZÀ-Ý][A-Za-zÀ-ÿ\'\\-]{2,}", after):', "if True:", ["test_robots_cleanup_and_linear_masking.py"]),
    "M120": ("a month is 720 hours again", SC + "consistency.py", '"month": 730', '"month": 720', ["test_robots_cleanup_and_linear_masking.py"]),
    "M121": ("a .localhost name keeps the addresses a resolver gives for it", SC + "safenet.py", '    if host == "localhost" or host.endswith(".localhost"):\n        # a', '    if False:\n        # a', ["test_robots_cleanup_and_linear_masking.py"]),
    "M122": ("a model name inside a real name refuses the person", SC + "fix_tracker.py", "|copilot|codex|subagent|", "|gemini|kimi|mistral|hermes|copilot|codex|subagent|", ["test_robots_cleanup_and_linear_masking.py"]),
    "M81": ("a hand-written access check is accepted (no seal)", SC + "fix_tracker.py", "if not safenet.sealed(c):", "if False:", ["test_secrets_and_access.py"]),
    "M82": ("an access proved by a check of another type", SC + "fix_tracker.py", 'if want_type and c.get("type") != want_type:', "if False:", ["test_secrets_and_access.py"]),
    "M83": ("--ref may be a pasted value, not a variable that exists", SC + "fix_tracker.py", 'if ref is not None and not ref.startswith("vault:") and ref not in os.environ:', "if False:", ["test_secrets_and_access.py"]),
    "M84": ("`keyword`, `passed` and `tokens` are taken for secret names", SC + "redact.py", "(?<![a-z])key(?![a-z]))", "(?<![a-z])key)", ["test_guard_proxy_and_tracker.py"]),
    "M85": ("a price in a long paragraph never meets the same price stated alone", SC + "consistency.py", 'if a["page"] != b["page"] and na and na == nb and len(na) >= 5 and na not in GENERIC:', "if False:", ["test_guard_proxy_and_tracker.py"]),
    "M86": ("an action plan with ticked boxes is overwritten", SC + "build_report.py", "if os.path.exists(plan_path) and not a.overwrite_plan:", "if False:", ["test_guard_proxy_and_tracker.py"]),
    "M88": ("a second srcset candidate over http is not counted", SC + "facts.py", 'urls += [cand.strip().split()[0] for cand in val.split(",") if cand.strip()]', "urls += []", ["test_guard_proxy_and_tracker.py"]),
    "M89": ("an AI robot's own group in robots.txt is ignored", SC + "facts.py", 'rb = robotsrules.Robots(status, robots_body or "", tok)', 'rb = robotsrules.Robots(status, robots_body or "", "SiteAuditSkill")', ["test_guard_proxy_and_tracker.py"]),
    "M50": ("a non-http address is accepted", SC + "safenet.py", [('if m and m.group(1).lower() not in ("http", "https"):', "if False:"), ("    if other:", "    if False:")], "", ["test_report_scoring_and_order.py"]),
}


BROKEN_MUTANT = re.compile(r"NameError|SyntaxError|IndentationError|ImportError|ModuleNotFoundError|AttributeError: module")


def run(copy, tests):
    """The first test file that goes red, as (name, assertion?). assertion? is False when the failure is the mutant itself crashing
    (a renamed symbol, a syntax error): that proves a test runs the code, not that it checks the rule."""
    for t in tests:
        try:
            r = subprocess.run([sys.executable, "-I", "-m", "unittest", "discover", "-s", os.path.join(copy, "tests"), "-p", t],
                               capture_output=True, text=True, timeout=600, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        except subprocess.TimeoutExpired:
            return t, True                  # a mutant that makes a test file hang is seen: the suite does not pass
        if r.returncode != 0:
            return t, not BROKEN_MUTANT.search(r.stdout + r.stderr)
    return None, False


def baseline(tests_needed):
    """Every test file a mutant relies on must be green on the untouched copy, or 'caught' means nothing (a test that
    cannot pass would catch every mutant). Returns the files that are not green."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = os.path.join(tmp, "copy")
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "examples"))
        return [t for t in sorted(tests_needed) if run(copy, [t])[0]]


def main():
    chosen = sys.argv[1:] or list(MUTANTS)
    unknown = [c for c in chosen if c not in MUTANTS]
    if unknown:
        print("unknown mutant(s):", ", ".join(unknown), file=sys.stderr)
        return 2
    survivors = []
    not_green = baseline({t for mid in chosen for t in MUTANTS[mid][4]})
    if not_green:
        print("The untouched copy is not green: " + ", ".join(not_green) + ". Fix the tests first; a mutant 'caught' by a red test means nothing.", file=sys.stderr)
        return 3
    with tempfile.TemporaryDirectory() as tmp:
        for mid in chosen:
            what, rel, old, new, tests = MUTANTS[mid]
            pairs = old if isinstance(old, list) else [(old, new)]
            copy = os.path.join(tmp, "copy")
            shutil.rmtree(copy, ignore_errors=True)
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__", "examples"))
            path = os.path.join(copy, rel)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            missing = [o for o, _ in pairs if o not in text]
            if missing:
                print(f"{mid}: PATTERN NOT FOUND, the mutant tests nothing ({rel}: {missing[0][:60]!r})")
                survivors.append(mid)
                continue
            for o, n in pairs:
                text = text.replace(o, n, 1)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            red, by_assertion = run(copy, tests)
            if red and not by_assertion:
                print(f"{mid}: only CRASHED the code ({red} went red on a NameError/ImportError, not on a check): counts as a survivor  [{what}]")
                survivors.append(mid)
                continue
            print(f"{mid}: {'caught by ' + red if red else 'SURVIVED (no test breaks)'}  [{what}]")
            if not red:
                survivors.append(mid)
    print(f"\n{len(chosen) - len(survivors)} of {len(chosen)} mutants caught." + (f" Survivors: {', '.join(survivors)}" if survivors else ""))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
