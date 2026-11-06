"""robots.txt rules as RFC 9309 describes them (stdlib only).

Python's own parser does not read `*` and `$` in a path, and does not pick the longest matching rule, so a polite
crawler built on it crawls pages a site asked it to leave alone. This is the small part of the standard a crawler
needs:

  - the group for the crawler's own name wins over the group for `*`; if neither exists, everything is allowed;
  - a rule matches the start of the path plus query; `*` matches any run of characters, `$` anchors the end;
  - the longest matching rule wins, and `Allow` wins a tie;
  - robots.txt answered with 4xx (other than 429): no restriction. Answered with 5xx or 429, or not reachable:
    everything is disallowed (Google treats 429 like a server error).

A site controls this file, so the matching never uses a regular expression (a hostile rule like `/*a*a*a*a*b` would
make one backtrack for hours): a rule is cut at its `*` into literal pieces, found one after the other with
str.find, which is linear and fast. A rule longer than MAX_RULE characters is cut to that length (it then blocks at
least as much), only the first MAX_RULES rules are kept, and the path that is tested is cut at MAX_URL characters.
Raw non-ASCII characters and their %-encoded form are the same thing (`/café` and `/caf%C3%A9`).
"""
import string
import urllib.parse

MAX_RULE = 500
MAX_RULES = 1000
MAX_URL = 2048
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _normalize(text):
    """Make %-escapes comparable: unreserved characters are decoded, the others get upper-case hex digits."""
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "%" and i + 2 < len(text) + 1 and len(text[i + 1:i + 3]) == 2 and all(c in string.hexdigits for c in text[i + 1:i + 3]):
            code = chr(int(text[i + 1:i + 3], 16))
            out.append(code if code in _UNRESERVED else "%" + text[i + 1:i + 3].upper())
            i += 3
            continue
        if ord(ch) > 127 or ch == " ":
            out.append("".join("%" + format(b, "02X") for b in ch.encode("utf-8", "replace")))
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _compile(path):
    """(anchored, literal pieces between the stars). Consecutive stars are one star."""
    path = _normalize(path)
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    return anchored, body.split("*")


def _matches(rule, target):
    anchored, segs = rule
    first = segs[0]
    if not target.startswith(first):
        return False
    pos = len(first)
    if len(segs) == 1:
        return target == first if anchored else True
    for piece in segs[1:-1]:
        if piece:
            i = target.find(piece, pos)
            if i < 0:
                return False
            pos = i + len(piece)
    last = segs[-1]
    if not last:
        return True
    if anchored:
        return len(target) - len(last) >= pos and target.endswith(last)
    return target.find(last, pos) >= 0


class Robots:
    def __init__(self, status, body, token):
        self.token = token.lower()
        self.status = status
        self.disallow_all = False
        self.rules = []          # (length, allow?, compiled rule)
        self.own_group = False   # True when a group names this crawler (it then wins over `*`)
        self.delay = None
        if status is None or status == 0 or status >= 500 or status == 429:
            self.disallow_all = True       # not reachable, broken or rate-limited: the standard says to stay away
            return
        if not (200 <= status < 300):
            return                         # 4xx: no robots.txt, no restriction
        groups, agents, rules, delay, in_rules = [], [], [], None, False
        for raw in (body or "").lstrip("\ufeff").splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if in_rules:
                    groups.append((agents, rules, delay))
                    agents, rules, delay, in_rules = [], [], None, False
                # "SiteAuditSkill/1.0" names the product SiteAuditSkill: only the product token counts
                agents.append(v.lower().split("/", 1)[0].split()[0] if v.split() else "")
            elif k in ("allow", "disallow"):
                in_rules = True
                if v and len(rules) < MAX_RULES:   # an empty Disallow allows everything: no rule
                    rules.append((k == "allow", v[:MAX_RULE]))
            elif k == "crawl-delay":
                in_rules = True
                try:
                    delay = float(v)
                except ValueError:
                    pass
        if agents or rules:
            groups.append((agents, rules, delay))
        own = [g for g in groups if self.token in g[0]]
        self.own_group = bool(own)
        chosen = own or [g for g in groups if "*" in g[0]]
        for _, rls, dl in chosen:
            for allow, path in rls:
                self.rules.append((len(path), allow, _compile(path)))
            if dl is not None:
                self.delay = dl if self.delay is None else max(self.delay, dl)

    def allowed(self, url):
        if self.disallow_all:
            return False
        u = urllib.parse.urlparse(url)
        target = _normalize((u.path or "/") + (("?" + u.query) if u.query else ""))[:MAX_URL]
        best = None                                        # (length, allow)
        for length, allow, rx in self.rules:
            if _matches(rx, target) and (best is None or length > best[0] or (length == best[0] and allow and not best[1])):
                best = (length, allow)
        return True if best is None else best[1]

    def crawl_delay(self):
        return self.delay
