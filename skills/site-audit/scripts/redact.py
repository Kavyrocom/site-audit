#!/usr/bin/env python3
"""Mask secrets in text before it is saved as audit evidence (stdlib only).

Usage:
    some_read_only_command | python3 -I redact.py --out internal/name.txt
    python3 -I redact.py --out internal/name.txt < file
    some_read_only_command | python3 -I redact.py          # masked text on stdout, nothing saved

Internal audits read configuration files and command output that can carry passwords, keys and tokens. Evidence
files end up in the report folder and may be shared, so every internal command's output goes through this script
first. `--out` writes the masked text to the file (so the agent needs no shell redirection). It keeps the NAME of
a setting and masks the value ("DB_PASSWORD = [REDACTED]"): the name is the evidence, the value never is. It is a
safety net, not a licence to cat a secrets file: do not read `.env` or `wp-config.php` when
`wp config list --fields=name` or a grep for the setting name is enough.

What it recognises: values next to a secret-looking name (assignments, JSON keys, PHP define(), quoted values with
spaces, command-line flags such as `mysql -pVALUE` or `--password=VALUE`), HTTP Authorization and Cookie headers,
user:password in URLs, secrets in query strings, private-key blocks, JWTs, WordPress application passwords (six
groups of four), "the password is ..." in plain sentences, and the key formats of the usual providers (GitHub,
GitLab, Anthropic, OpenAI, AWS, Google, Stripe, Slack, npm, Hugging Face, SendGrid, DigitalOcean).
Personal data: e-mail addresses, IP addresses (loopback excepted), telephone numbers and French street addresses
become [EMAIL], [IP], [PHONE] and [ADDRESS]; values of fields such as user_login, display_name, billing_email or
billing_address_1 are masked; the rows of a user table (`wp user list`, CSV or boxed) keep only their numeric ID. It
cannot mask a person's name in free text: count instead (`wp user list --format=count`). It masks the formats it
knows, nothing more: read the result before you share it.
What it cannot know: a secret with no recognisable name or format, in free text. Read the masked file before
sharing it. Exit code 0 (the number of masked values goes to stderr), 2 when --out cannot be written.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402

MASK = "[REDACTED]"
EMAIL, IP, PHONE, ADDRESS = "[EMAIL]", "[IP]", "[PHONE]", "[ADDRESS]"
# A name is a secret's name when the keyword stands as a word of its own: `keyword`, `passed`, `tokens` and `salted` are not.
NAME_START = r"(?<![A-Za-z0-9_.\-])"      # a name begins where a run of name characters begins: one start per run keeps the scan linear
NAME = (r"[A-Za-z0-9_.\-]*(?:pass(?:word|wd|phrase)?(?![a-z])|pwd|secret|token(?![a-z])|api[_-]?key|apikey|private[_-]?key|access[_-]?key|account[_-]?key|salt(?![a-z])|"
        r"credential|auth(?:orization)?[_-]?key|client[_-]?secret|signature|bearer|dsn|session[_-]?id|nonce|db[_-]?user(?![a-z])|(?<![a-z])key(?![a-z]))[A-Za-z0-9_.\-]{0,100}")


def _keep_name(m):
    return f"{m.group('k')}{m.group('q1')}{m.group('sep')}{m.group('q2')}{MASK}{m.group('q2')}"


def _assign(m):
    return m.group(0) if MASK in m.group("v") else _keep_name(m)


def _cookie(m):
    """`Cookie:` carries only name=value pairs: mask every value. `Set-Cookie:` starts with the cookie itself and
    continues with attributes (Path, Expires, SameSite...) that are useful evidence: mask the first value only."""
    pairs = re.compile(r"(\b[\w.\-]+=)[^;\s,]+")
    return m.group(1) + pairs.sub(lambda x: x.group(1) + MASK, m.group(3), count=1 if m.group(2) else 0)


# the value of a personal field: runs to the end of the field, not just to a space
_PV = r"(?!\s|\[REDACTED\]|\[EMAIL\]|\[IP\]|\[PHONE\])[^\n'\",;&|<>)}]+[^\s'\",;&|<>)}]"

def _wp_password(m):
    """Six words of four letters in title case ("Find Your Best Plan With Ease") are a title: a real application
    password has a digit or a capital inside a group, not only at the start of each one."""
    s = m.group(0)
    if re.search(r"\d", s) or any(ch.isupper() for part in s.split(" ") for ch in part[1:]):
        return MASK
    return s


def _secretish(v):
    """A value that looks like a secret rather than a word: a digit or a symbol in it, or a long run of characters."""
    v = v.strip("'\" ")
    return len(v) >= 6 and (bool(re.search(r"\d", v)) or bool(re.search(r"[^\w\s\-.]", v)) or len(v) >= 16) and "REDACTED" not in v


def _user_table(m):
    """The rows under a header that names user_login, display_name or user_email keep their numeric ID and nothing else."""
    header = m.group(1).strip()
    cells = [c.strip() for c in re.split(r"\||\t|,|\s{2,}", header) if c.strip()]
    fields = set(re.findall(r"\b(?:user_login|display_name|user_email|user_nicename)\b", header))
    # a table header is made of short cells; a sentence that merely mentions user_login is not a header, and the lines after it are not rows
    if not ((len(cells) >= 2 and all(len(c.split()) <= 2 and len(c) <= 30 for c in cells)) or len(fields) >= 2):
        return m.group(0)
    rows = []
    for line in m.group(2).split("\n"):
        if not line.strip() or re.fullmatch(r"[\s+|=\-]+", line):
            rows.append(line)
            continue
        k = re.match(r"^(\s*\|?\s*\d+\s*(?:\||,|\t|\s{2,}))", line)
        rows.append((k.group(1) if k else "") + MASK)
    return m.group(1) + "\n".join(rows)


ARTICLE = r"(?:d[eu]s?|d'|l[ae]s?|l')"


def _address(m):
    """A street address names its street: a capitalised word, or a postal code and a city. `3 avenue : le plan`,
    `2 chemin de fer` and `4 cours et 3 passage piétons` are sentences about something else."""
    t = m.group(0)
    if re.search(r"\b\d{5}\s+[A-ZÀ-Ý]", t):
        return ADDRESS
    after = re.sub(r"(?i)^\d{1,3}(?:\s?(?:bis|ter))?,?\s+(?:rue|avenue|av\.|boulevard|bd|impasse|all[ée]e|chemin|place|quai|route|cours|square|passage)\s+", "", t)
    first = after.split(" ")[0] if after else ""
    if re.match(r"(?i)^" + ARTICLE + "$", first) or first[:1].isupper():
        if re.search(r"\b[A-ZÀ-Ý][A-Za-zÀ-ÿ'\-]{2,}", after):
            return ADDRESS
    return t


RULES = [
    ("pem", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S), lambda m: MASK),
    # WordPress application password: six groups of four letters/digits with a capital or a digit AFTER the first character
    # (so six ordinary four-letter words in a row, "What does your site look like", are left alone). FIRST, before the name=value rules would cut it after the
    # first group and leave the other twenty characters in clear.
    ("wp_app_password", re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9][a-z ]{0,27}[A-Z0-9])(?:[A-Za-z0-9]{4} ){5}[A-Za-z0-9]{4}(?![A-Za-z0-9])"), lambda m: _wp_password(m)),
    # a YAML block value: `password: |` followed by indented lines
    ("yaml_block", re.compile(r"(?im)^([ \t]*" + NAME + r"[ \t]*:[ \t]*[|>][-+]?[ \t]*\n)((?:[ \t]+\S.*(?:\n|\Z))+)"), lambda m: m.group(1) + "  " + MASK + "\n"),
    ("php_define", re.compile(r"""(define\(\s*['"]""" + NAME + r"""['"]\s*,\s*)(['"])(?:\\.|(?!\2).)*\2""", re.I), lambda m: f"{m.group(1)}'{MASK}'"),
    # <password>value</password> and <add key="DB_PASSWORD" value="x" />: the name sits in one place, the value in another
    ("xml_secret", re.compile(r"(?i)(<(?P<t>" + NAME + r")\b[^>]*>)(?!\[REDACTED\])[^<\s][^<]*?(</(?P=t)\s*>)"), lambda m: m.group(1) + MASK + m.group(3)),
    ("xml_key_value", re.compile(r"(?i)(\bkey\s*=\s*['\"](?:" + NAME + r")['\"]\s+value\s*=\s*)(['\"])(?!\[REDACTED\])[^'\"]*\2"), lambda m: m.group(1) + m.group(2) + MASK + m.group(2)),
    # NAME = "value with spaces" / NAME: 'value' / "NAME": "value"  (a quoted value runs to its closing quote)
    ("assign_quoted", re.compile(r"""(?P<k>""" + NAME_START + NAME + r""")(?P<q1>['"]?)(?P<sep>\s*(?:=>|=|:)\s*)(?P<q2>['"])(?P<v>(?:\\.|(?!(?P=q2)).)*)(?P=q2)""", re.I), _assign),
    # NAME=value, NAME: value (unquoted: up to the next space, quote, comma or bracket)
    ("assign", re.compile(r"""(?P<k>""" + NAME_START + NAME + r""")(?P<q1>['"]?)(?P<sep>\s*(?:=>|=|:)\s*)(?P<q2>)(?P<v>[^\s'",;)}&\[\]]{3,})""", re.I), _assign),
    ("auth_header", re.compile(r"(?i)\b(authorization\s*:\s*(?!(?:\w+\s+)?\[REDACTED\])(?:(?:basic|bearer|token|digest|negotiate)\s+)?)[^\s\"']+"), lambda m: m.group(1) + MASK),
    ("other_auth_headers", re.compile(r"(?i)\b((?:proxy-authorization|x-api-key|x-auth-token)\s*:\s*)[^\s\"']+"), lambda m: m.group(1) + MASK),
    ("cookie_header", re.compile(r"(?im)^([ \t]*(set-)?cookie[ \t]*:[ \t]*)(.+)$"), _cookie),
    ("url_userinfo", re.compile(r"((?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]*://[^/\s:@]*:)(?!\[REDACTED\])[^@\s/]+(@)", re.I), lambda m: m.group(1) + MASK + m.group(2)),
    ("query_secret", re.compile(r"(?i)([?&](?:" + NAME + r"|sig|mc_eid|mc_cid|fbclid|gclid|msclkid)=)[^&\s#'\"<>)]+"), lambda m: m.group(1) + MASK),
    # mysql -pSECRET, mysqldump -pSECRET (no space between the flag and the value)
    ("cli_dash_p", re.compile(r"(?i)(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^\n|;&]*?\s-p)(?=\S)(\S+)"), lambda m: m.group(1) + MASK),
    # command lines: --password VALUE (with a space), sshpass -p VALUE, curl -u user:VALUE
    ("cli_long_flag", re.compile(r"(?i)(--(?:[a-z0-9]+-)*(?:password|passwd|pass|passphrase|token|secret|key|apikey|api-key|access-key|secret-access-key|auth-token|client-secret)[ \t]+)(?!\[REDACTED\])(?:'[^']*'|\"[^\"]*\"|[^\s'\"]+)"), lambda m: m.group(1) + MASK),
    ("sshpass", re.compile(r"(?i)(\bsshpass\s+-p\s*)(?!\[REDACTED\])(?:'[^']*'|\"[^\"]*\"|\S+)"), lambda m: m.group(1) + MASK),
    ("curl_user", re.compile(r"(?i)(\b(?:curl|wget|http|https)\b[^\n|;&]{0,300}?\s(?:-u|--user|--http-user)[ =]['\"]?[^\s:'\"]+:)(?!\[REDACTED\])(?:[^\s'\"]+)"), lambda m: m.group(1) + MASK),
    # htpasswd hashes (apr1, bcrypt, sha-crypt), webhooks, bot tokens
    ("htpasswd", re.compile(r"((?<![\w.\-])[\w.\-]+:)(\$(?:apr1|2[aby]|1|5|6|y)\$[^\s:]+|\{SHA\}[A-Za-z0-9+/=]+)"), lambda m: m.group(1) + MASK),
    ("webhooks", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_\-]+|https://(?:discord|discordapp)\.com/api/webhooks/\d+/[A-Za-z0-9_\-]+"), lambda m: MASK),
    # a Sentry-style DSN: the public key sits in front of the @ of the host
    ("dsn_key", re.compile(r"(?i)(\bhttps?://)[0-9a-f]{20,}(@[\w.\-]*(?:sentry|ingest)[\w.\-]*)"), lambda m: m.group(1) + MASK + m.group(2)),
    # a table of users (wp user list): header naming user_login / display_name / user_email, then one row per user
    ("user_table", re.compile(r"(?im)^((?![^\n]*\b(?:user_login|display_name|user_email|user_nicename)\b['\"]?[ \t]*(?:=>|=|:))[^\n]*\b(?:user_login|display_name|user_email|user_nicename)\b[^\n]*\n)((?:[ \t]*\S[^\n]*(?:\n|\Z))+)"), _user_table),
    # the database host, unless it is the local machine: an internal host name says how the infrastructure is laid out
    ("db_host", re.compile(r"(?i)(\bDB[_-]?HOST['\"]?\s*(?:=>|=|:|,)\s*['\"]?)(?!localhost\b|127\.0\.0\.1\b|\[REDACTED\])[^'\"\s,;)]+"), lambda m: m.group(1) + MASK),
    # name=value pairs that identify a person (wp user list, query strings, form dumps)
    ("person_fields", re.compile(r"(?i)(\b(?:user[_-]?login|user[_-]?email|user[_-]?name|username|display[_-]?name|(?:billing|shipping)[_-]?(?:email|phone|first[_-]?name|last[_-]?name|company|address[_-]?\d?|city|postcode)|siret|siren)\b['\"]?\s*(?:=>|=|:)\s*['\"]?)" + _PV), lambda m: m.group(1) + MASK),
    # ordinary words (phone, email, login...) only as `word=value` or as a JSON key, never `phone: the` in a sentence
    ("person_words", re.compile(r"(?i)(\b(?:e?mail|phone|telephone|first[_-]?name|last[_-]?name|login)\s*(?:=>|=)\s*['\"]?|['\"](?:e?mail|phone|telephone|first[_-]?name|last[_-]?name|login)['\"]\s*:\s*['\"])" + _PV), lambda m: m.group(1) + MASK),
    ("telegram", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b"), lambda m: MASK),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), lambda m: MASK),
    ("aws", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), lambda m: MASK),
    ("github", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), lambda m: MASK),
    ("gitlab", re.compile(r"\bgl(?:pat|ptt)-[A-Za-z0-9_\-]{16,}"), lambda m: MASK),
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"), lambda m: MASK),
    ("openai", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{24,}"), lambda m: MASK),
    ("stripe_slack_google", re.compile(r"\b(?:xox[abprs]-[A-Za-z0-9-]{10,}|(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}|whsec_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_\-]{35}|ya29\.[A-Za-z0-9_\-]{20,})"), lambda m: MASK),
    ("misc_providers", re.compile(r"\b(?:[0-9a-f]{32}-us\d{1,2}|npm_[A-Za-z0-9]{30,}|hf_[A-Za-z0-9]{30,}|dop_v1_[a-f0-9]{40,}|SG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,})"), lambda m: MASK),
    # "the password is X", "mot de passe : X", "mdp = X" in plain sentences
    ("sentence", re.compile(r"(?i)\b((?:mot de passe|mdp|password|passwd|passphrase|pw|pass|pwd|secret|token|api key|clé api)\s*(?:is|was|are|est|=|:|->)\s*)(?!\[REDACTED\])(['\"]?)([^\s'\",;]{3,})\2"), lambda m: m.group(1) + m.group(2) + MASK + m.group(2)),
    ("sentence_no_sign", re.compile(r"(?i)\b((?:mot de passe|mdp|password|passwd|pwd|pw|identifiants?(?:\s+\w+)?|credentials?(?:\s+\w+)?|login(?:\s+\w+)?)\s+(?:[/|]\s+)?)(?!\[REDACTED\]|(?:is|est|was|are)\b)(?=[^\s'\",;]*[\d!@#$%^&*])([^\s'\",;]{4,})"), lambda m: m.group(1) + MASK),
    # personal data: e-mail addresses, IP addresses, telephone numbers. Loopback and the unspecified address are not
    # personal, so they stay readable.
    # a French street address: number, street type, name, optionally the postcode and town
    ("address", re.compile(r"(?i)\b\d{1,3}(?:\s?(?:bis|ter))?,?\s+(?:rue|avenue|av\.|boulevard|bd|impasse|all[ée]e|chemin|place|quai|route|cours|square|passage)\s+[^\n,;.]{2,40}(?:,?\s*\d{5}\s+(?-i:[A-ZÀ-Ý][A-Za-zÀ-ÿ'\-]+(?: [A-ZÀ-Ý][A-Za-zÀ-ÿ'\-]+){0,2}))?(?=[\s,;.]|$)"), _address),
    ("email", re.compile(r"(?<![\w.+\-])[A-Za-z0-9][A-Za-z0-9._%+\-]*@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,}\b"), lambda m: EMAIL),
    ("ipv4", re.compile(r"(?<![\w.\-])(?<!version )(?<!versions )(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w\-]|\.\d)"), lambda m: m.group(0) if m.group(0).startswith(("127.", "0.0.0.0")) else IP),
    ("ipv6", re.compile(r"(?i)(?<![\w:.])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4}){0,5})?|:(?::[0-9a-f]{1,4}){1,7})(?![\w:])"), lambda m: m.group(0) if m.group(0) in ("::", "::1") else IP),
    ("phone", re.compile(r"(?<![\w.])(?:\+\d{1,3}[ .\-]?\(?\d\)?(?:[ .\-]?\d{2,3}){3,5}|(?<!\d)0[1-9](?:[ .\-]?\d{2}){4}(?!\d)|\(\d{3}\)[ .\-]?\d{3}[ .\-]\d{4}(?!\d))(?![\w])"), lambda m: PHONE),
    # the user of a web server log line: `ip - alice [05/Nov/2026:07:46:12 +0100]`
    ("log_user", re.compile(r"(?m)^((?:\d{1,3}\.){3}\d{1,3}|\[IP\]|[0-9a-fA-F:]{3,39}) - (?!-|\[REDACTED\])[^\s\[]+( \[\d{2}/[A-Za-z]{3}/\d{4}:)"), lambda m: m.group(1) + " - " + MASK + m.group(2)),
]


def redact(text):
    n = 0
    for _, rx, rep in RULES:
        text, k = rx.subn(rep, text)
        n += k
    return text, n


# Rules that only fire on something that really looks like a credential (a provider's format, a header, a flag, a URL
# with a password). The generic `name = value` rules are left out: a note that says "keyword: plombier" is not a leak.
HIGH_CONFIDENCE = frozenset({"pem", "wp_app_password", "php_define", "auth_header", "other_auth_headers", "cookie_header", "url_userinfo",
                             "query_secret", "cli_dash_p", "cli_long_flag", "sshpass", "curl_user", "htpasswd", "webhooks", "dsn_key",
                             "telegram", "jwt", "aws", "github", "gitlab", "anthropic", "openai", "stripe_slack_google", "misc_providers",
                             "sentence", "sentence_no_sign", "xml_secret", "xml_key_value"})
SOFT_VALUE = {"assign": "v", "assign_quoted": "v", "sentence": 3}     # rules whose hit counts only when the value looks like a secret
PII_RULES = frozenset({"email", "ipv4", "ipv6", "phone", "person_fields", "person_words", "user_table", "address", "log_user"})


def sensitive_kinds(text):
    """Names of the rules that would CHANGE this text (a value already masked does not count). Used as a gate by
    build_report.py: ("secret" kinds, "personal" kinds)."""
    secrets, personal = [], []
    for name, rx, rep in RULES:
        if name in SOFT_VALUE:                 # `Token: absent` is a sentence, `DB_PASSWORD = hunter2hunter2` is a leak
            hit = any(_secretish(m.group(SOFT_VALUE[name])) for m in rx.finditer(text))
        else:
            hit = rx.sub(rep, text) != text
        if hit:
            (personal if name in PII_RULES else secrets).append(name)
    return secrets, personal


def main():
    ap = argparse.ArgumentParser(description="Mask secrets and personal data in text read on stdin.")
    ap.add_argument("--out", help="write the masked text to this file instead of stdout (no shell redirection needed)")
    a = ap.parse_args()
    data = sys.stdin.read()
    out, n = redact(data)
    if a.out:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(out)
            safenet.private_output(a.out)
        except OSError as e:
            print(f"redact.py: cannot write {a.out}: {e}", file=sys.stderr)
            return 2
        print(f"redact.py: {n} value(s) masked, written to {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(out)
        print(f"redact.py: {n} value(s) masked", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
