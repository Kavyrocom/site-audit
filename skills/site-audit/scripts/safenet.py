"""Network guard shared by the scripts that fetch pages (stdlib only).

An audited site is untrusted. It can answer a request with a redirect to `file:///etc/passwd`, to
`http://169.254.169.254/` (cloud metadata) or to a service that only listens on the machine running the
audit, and whatever comes back would be written into the report folder. This module decides, before every
hop, whether the next URL may be fetched.

Rules
  - only http and https are ever fetched (never file:, ftp:, data:, gopher: ...);
  - a URL whose host is a private, loopback, link-local, multicast, reserved or unspecified address is
    refused, UNLESS the audit itself started on such a host (testing your own staging or localhost);
  - a public start URL can never lead to a private address, by redirect or by DNS answer;
  - name resolution is checked for every address the name returns.

Limit, said plainly: the check happens before the connection, so a DNS answer that changes between the check
and the connection (rebinding) is not covered. Run audits of sites you do not control on a machine with no
secret and no internal service within reach.
"""
import os
import re
import sys
import ipaddress
import json
import socket
import urllib.parse

ALLOWED_SCHEMES = ("http", "https")


def _resolve(host):
    """All addresses a host name resolves to (a literal address resolves to itself)."""
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except (socket.gaierror, UnicodeError, OSError):
        return []


def _is_public(addr):
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    # is_global is False for private, loopback, link-local, reserved AND shared address space (100.64.0.0/10, used by
    # Tailscale and carrier-grade NAT), which is_private alone treats as public.
    return bool(ip.is_global) and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                                       or ip.is_reserved or ip.is_unspecified)


def host_of(url):
    try:
        return (urllib.parse.urlparse(url).hostname or "").strip("[]")
    except ValueError:
        return ""


ALLOW_PRIVATE_ENV = "SITE_AUDIT_ALLOW_PRIVATE_HOST"


def starts_private(url):
    """True when the audit itself starts on a private or local host: such an audit may stay on that host.

    The answer never comes from the DNS record of an ordinary name: whoever controls a domain controls what it
    resolves to, and a hostile site must not be able to switch the guard off by publishing a private address.
    Private mode is for: a literal private or loopback address (http://127.0.0.1:8080/, http://192.168.1.20/),
    `localhost`, and a host name the person running the audit names on purpose in SITE_AUDIT_ALLOW_PRIVATE_HOST
    (a staging name that only resolves inside the company network).
    """
    host = host_of(url)
    if not host:
        return False
    low = host.lower()
    try:
        ip = ipaddress.ip_address(low.split("%")[0])
    except ValueError:
        ip = None
    if ip is not None:
        return not _is_public(low)
    named = os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower()
    if low == "localhost" or low.endswith(".localhost") or (named and named == low):
        addrs = _resolve(host)
        return bool(addrs) and not all(_is_public(a) for a in addrs)
    return False


_AUDIT = {"allow_private": None, "start_addrs": set()}


def set_audit_start(url):
    """Remember, once, whether the audit itself started on a private or local host.

    Every later request of the same audit (sitemaps declared in robots.txt, probes, links) is judged against THIS
    answer, never against its own address: a hostile site must not be able to turn a private address into an
    "audit that starts on a private host" just by pointing to it.
    """
    _AUDIT["allow_private"] = starts_private(url)
    host = (host_of(url) or "").lower()
    addrs = [a for a in _resolve(host_of(url)) if not _is_public(a)] if _AUDIT["allow_private"] else []
    if host == "localhost" or host.endswith(".localhost"):
        # a `.localhost` name means this machine: whatever else a resolver answers for it is not trusted
        addrs = [a for a in addrs if ipaddress.ip_address(a.split("%")[0]).is_loopback]
        _AUDIT["allow_private"] = bool(addrs)
    _AUDIT["start_addrs"] = set(addrs)
    return _AUDIT["allow_private"]


def private_allowed(addr):
    """For an audit that started on a private or local host: may it reach this private address?

    Only the host it started on (and the rest of loopback when it started on loopback). Link-local addresses, which
    hold the cloud metadata service (169.254.169.254) and similar, are never allowed. When no start address was
    recorded (a one-off call), only loopback is allowed: the guard fails closed.
    """
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    start = _AUDIT["start_addrs"]
    if not start:
        return ip.is_loopback
    if str(ip) in {str(ipaddress.ip_address(a.split("%")[0])) for a in start}:
        return True
    return bool(ip.is_loopback and any(ipaddress.ip_address(a.split("%")[0]).is_loopback for a in start))


def default_allow_private(url):
    """The allowance to use when a caller does not state one: the audit-wide answer, else the URL's own (tests, one-off calls)."""
    return _AUDIT["allow_private"] if _AUDIT["allow_private"] is not None else starts_private(url)


def browser_refusal(url, allow_private):
    """For a browser request (Chrome): None when it may go out. Inline schemes that fetch nothing are fine."""
    scheme = (urllib.parse.urlparse(url).scheme or "").lower()
    if scheme in ("data", "blob", "about"):
        return None
    return check(url, allow_private)


def check(url, allow_private):
    """None when `url` may be fetched, else a short reason."""
    try:
        u = urllib.parse.urlparse(url)
    except ValueError:
        return "malformed URL"
    if u.scheme.lower() not in ALLOWED_SCHEMES:
        return f"refused scheme '{u.scheme or '?'}': only http and https are fetched"
    host = host_of(url)
    if not host:
        return "URL without a host"
    addrs = _resolve(host)
    if not addrs:
        return None  # the connection will fail with its own, clearer error
    if allow_private:
        bad = [a for a in addrs if not _is_public(a) and not private_allowed(a)]
        if bad:
            return f"refused: {host} resolves to a private address that is not the host this audit started on"
        return None
    bad = [a for a in addrs if not _is_public(a)]
    if bad:
        return f"refused: {host} resolves to a private or local address ({bad[0]}); a public site must not lead there"
    return None


_SEAL_LABEL = "site-audit access check v1"


def seal(obj):
    """Add a `digest` to an access-check result. It catches a file written or edited by hand (the field is not
    something you type by accident); it does not stop someone who reads this code on purpose: the proof is
    declarative, and the log with the name of the person who said GO is the trail."""
    import hashlib
    body = {k: v for k, v in obj.items() if k != "digest"}
    obj["digest"] = hashlib.sha256((_SEAL_LABEL + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()
    return obj


def sealed(obj):
    import hashlib
    if not isinstance(obj, dict) or not isinstance(obj.get("digest"), str):
        return False
    body = {k: v for k, v in obj.items() if k != "digest"}
    return hashlib.sha256((_SEAL_LABEL + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest() == obj["digest"]


AUDIT_FOLDER = re.compile(r"^site-audit-.+-\d{4}-\d{2}-\d{2}(?:-\d+)?$")   # the folder name SKILL.md gives: site-audit-<host>-<date>


def private_output(path):
    """Keep an audit folder out of git. Reports hold evidence about a site (and, with inside access, bits of its
    configuration): they must not be committed or published by accident. For any path inside a folder named
    `site-audit-<host>-<date>` (the folder SKILL.md has you create) this writes `.gitignore` containing `*` at the top
    of that folder, once. A folder with any other name is never touched: it may be somebody's own repository."""
    try:
        d = os.path.abspath(path)
        if not os.path.isdir(d):
            d = os.path.dirname(d)
        parts = d.split(os.sep)
        for i, part in enumerate(parts):
            if AUDIT_FOLDER.match(part):
                top = os.sep.join(parts[:i + 1]) or os.sep
                gi = os.path.join(top, ".gitignore")
                if os.path.isdir(top) and not os.path.exists(gi):
                    with open(gi, "w", encoding="utf-8") as fh:
                        fh.write("*\n")
                return None
    except OSError:
        return None
    return _unprotected_in_git(d)


def _unprotected_in_git(folder):
    """A warning when `folder` sits inside a git repository and git would not ignore it, else None. Never raises."""
    import subprocess
    try:
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}
        inside = subprocess.run(["git", "-C", folder, "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=10, env=env)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return None
        ignored = subprocess.run(["git", "-C", folder, "check-ignore", "-q", "--no-index", "."], capture_output=True, text=True, timeout=10, env=env)
        if ignored.returncode == 0:
            return None
        return (f"warning: {folder} is inside a git repository and is not ignored by it. This folder holds evidence about a site "
                "(and, with inside access, bits of its configuration): add it to .gitignore before any commit, or write it outside the repository.")
    except (OSError, subprocess.SubprocessError):
        return None


def usage_error(message):
    """Wrong input from the person: say it and exit 2 (1 is kept for a site that cannot be reached)."""
    print(f"usage error: {message}", file=sys.stderr)
    sys.exit(2)


def start_url(arg):
    """The URL to audit from what the person typed: `example.com` becomes https, `ftp://` or `file://` is a usage error (exit 2)."""
    arg = (arg or "").strip()
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://", arg)
    if m and m.group(1).lower() not in ("http", "https"):
        usage_error(f"only http and https addresses can be audited, not {m.group(1).lower()}://")
    other = re.match(r"^(javascript|data|file|mailto|tel|about|blob|view-source|chrome|ws|wss|ftp|sftp|ssh):", arg, re.I)
    if other:
        usage_error(f"only http and https addresses can be audited, not {other.group(1).lower()}:")
    url = arg if m else "https://" + arg
    if not urllib.parse.urlparse(url).hostname:
        usage_error(f"no host in {arg!r}")
    set_audit_start(url)
    return url
