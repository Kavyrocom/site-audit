#!/usr/bin/env python3
"""Check, read-only, that the agent really has the access the person says it gives (stdlib only).

Usage:
    python3 -I access_check.py ssh   --host H --user U [--port 22] [--key ~/.ssh/id_ed25519] [--webroot /var/www/site]
    python3 -I access_check.py wp    --url https://site.example --user-env WP_USER --pass-env WP_APP_PASSWORD
    python3 -I access_check.py ftp   --host H --user-env FTP_USER --pass-env FTP_PASS [--tls] [--port 21]
    python3 -I access_check.py files --path /var/www/site

Prints one JSON object: {"ok": bool, "type": ..., "detail": ..., "capabilities": {...}, "next_step": ...} and exits
0 when the access works, 2 when it does not (next_step says exactly what to ask the person for).
`--out check.json` (on any type) also writes that object to a file: `fix_tracker.py provide --check check.json`
takes it as the proof that the access works.

Rules:
  - A secret is never an argument: --user-env and --pass-env take the NAME of an environment variable. Nothing
    secret is printed or written. Ask the person to put the secret in the environment or the agent's secret
    store and to tell you the name, never to paste it in the chat.
  - It only reads. It runs a fixed command over SSH (no command from the caller), lists nothing on FTP beyond
    the working directory, and reads the plugin list of WordPress. It never writes, uploads or changes anything.
  - SSH uses keys only (BatchMode, no password prompt) and refuses an unknown host key: the person confirms the
    fingerprint, you do not accept it for them.
  - A password sent over plain http or plain FTP is refused (loopback excepted): ask for https, FTPS or SFTP.
  - Credentials never follow a redirect: a 3xx answer is reported with its destination, and the person gives the
    final address. FTPS checks the server certificate and its name.
"""
import argparse
from datetime import datetime, timezone
import base64
import ftplib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402

HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
USER_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._@-]{0,60}$")
PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,200}$")
REMOTE = ("echo ok; id -un; uname -s; "
          "if command -v wp >/dev/null 2>&1; then echo wpcli=yes; else echo wpcli=no; fi; "
          "if command -v php >/dev/null 2>&1; then php -v | head -1; fi")


OUT_PATH = None


def out(ok, typ, detail, caps=None, next_step=None):
    text = json.dumps(safenet.seal({"ok": ok, "type": typ, "detail": detail, "capabilities": caps or {}, "next_step": next_step,
                                    "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}), ensure_ascii=False)
    print(text)
    if OUT_PATH:
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        safenet.private_output(OUT_PATH)
    return 0 if ok else 2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: an Authorization header must never be sent to a host the person did not name."""
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(NoRedirect)


def env_secret(name):
    v = os.environ.get(name or "")
    return v if v else None


def check_ssh(a):
    if not HOST_RE.match(a.host or "") or not USER_RE.match(a.user or ""):
        return out(False, "ssh", "invalid host or user", next_step="Give a plain host name and user name.")
    if a.webroot and not PATH_RE.match(a.webroot):
        return out(False, "ssh", "invalid webroot path", next_step="Give an absolute path with letters, digits, . _ - /")
    if not shutil.which("ssh"):
        return out(False, "ssh", "the ssh client is not installed on this machine", next_step="Install an OpenSSH client, or choose another access type.")
    cmd = REMOTE + (f"; test -r {a.webroot} && echo webroot_readable=yes || echo webroot_readable=no; test -w {a.webroot} && echo webroot_writable=yes || echo webroot_writable=no" if a.webroot else "")
    key = []
    if a.key:
        kp = os.path.abspath(os.path.expanduser(a.key))
        if not os.path.isfile(kp):
            return out(False, "ssh", f"key file not found: {a.key}", next_step="Give the path of the private key file this agent may use (the file, never its content).")
        key = ["-i", kp, "-o", "IdentitiesOnly=yes"]
    known = ["-o", f"UserKnownHostsFile={os.path.abspath(os.path.expanduser(a.known_hosts))}"] if a.known_hosts else []
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes", "-o", "LogLevel=ERROR", *key, *known,
                            "-p", str(a.port), f"{a.user}@{a.host}", cmd], capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired:
        return out(False, "ssh", "the server did not answer within 40 seconds", next_step="Check the host, the port and any firewall or VPN that must be on, then try again.")
    err = (r.stderr or "").strip()
    if r.returncode != 0:
        if "Host key verification failed" in err or "No ED25519 host key is known" in err or "No RSA host key is known" in err:
            return out(False, "ssh", "host key not known on this machine", next_step="Ask the owner for the server's key fingerprint, check it with ssh-keyscan, then add it to known_hosts. Do not accept it blindly.")
        if "Permission denied" in err:
            return out(False, "ssh", "key refused (permission denied)", next_step="Ask the person to add this agent's public key to the server for this user, or to give the name of the right key or ssh config alias.")
        if "timed out" in err or "No route" in err or "refused" in err:
            return out(False, "ssh", "cannot reach the server (" + err.splitlines()[-1][:80] + ")", next_step="Check the host, the port and any firewall or VPN that must be on.")
        return out(False, "ssh", "ssh failed: " + (err.splitlines()[-1][:100] if err else f"exit {r.returncode}"), next_step="Ask the person to test the same ssh command from their own machine.")
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    caps = {"whoami": lines[1] if len(lines) > 1 else None, "os": lines[2] if len(lines) > 2 else None, "wp_cli": "wpcli=yes" in lines,
            "php": next((x for x in lines if x.startswith("PHP ")), None)}
    for k in ("webroot_readable", "webroot_writable"):
        v = next((x for x in lines if x.startswith(k + "=")), None)
        if v:
            caps[k] = v.endswith("yes")
    return out(lines[:1] == ["ok"], "ssh", f"connected as {caps['whoami']} (read-only test, nothing was changed)", caps)


def check_wp(a):
    u = urllib.parse.urlparse(a.url)
    host = u.hostname or ""
    loop = host in ("localhost", "127.0.0.1", "::1")
    if u.scheme not in ("https", "http") or not host:
        return out(False, "wp", "invalid url", next_step="Give the site address, for example https://example.com")
    user, pw = env_secret(a.user_env), env_secret(a.pass_env)
    if not user or not pw:
        return out(False, "wp", f"environment variable {a.user_env if not user else a.pass_env} is empty or missing",
                   next_step="Ask the person to create a WordPress application password (Users > Profile > Application Passwords), put the user name and the password in the environment, and tell you the two variable names. Never paste the password in the chat.")
    if u.scheme != "https" and not loop:
        return out(False, "wp", "refusing to send a password over plain http", next_step="Ask for the https address of the site.")
    base = f"{u.scheme}://{u.netloc}".rstrip("/")

    def get(path, auth):
        h = {"Accept": "application/json", "User-Agent": "site-audit-access-check"}
        if auth:
            h["Authorization"] = "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()
        try:
            with _opener.open(urllib.request.Request(base + path, headers=h), timeout=25) as r:
                return r.status, json.loads(r.read(2_000_000).decode("utf-8", "replace") or "null")
        except urllib.error.HTTPError as e:
            if 300 <= e.code < 400:
                where = urllib.parse.urlparse(e.headers.get("Location") or "")
                return e.code, {"redirect_to_host": where.netloc or "(relative)"}
            try:
                return e.code, json.loads(e.read(2_000_000).decode("utf-8", "replace"))
            except Exception:
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return 0, {"message": type(e).__name__}
    st, j = get("/wp-json/", False)
    if 300 <= st < 400:
        return out(False, "wp", f"the site redirects (HTTP {st}) to {j.get('redirect_to_host')}: credentials are never sent along a redirect",
                   next_step=f"Ask for the final address of the site (it answers from {j.get('redirect_to_host')}), including https and www or not, and run the check again with it.")
    if st != 200 or not isinstance(j, dict) or "namespaces" not in j:
        return out(False, "wp", f"the WordPress REST API does not answer (HTTP {st})", next_step="Check the address; a security plugin or firewall may block /wp-json/. Ask the person to allow it for this agent.")
    st, me = get("/wp-json/wp/v2/users/me?context=edit", True)
    if 300 <= st < 400:
        return out(False, "wp", f"an authenticated call was redirected (HTTP {st}) to {me.get('redirect_to_host')}: refused, credentials are never sent along a redirect",
                   next_step="Ask for the final address of the site and run the check again with it.")
    if st == 401:
        return out(False, "wp", "credentials rejected (HTTP 401)", next_step="Ask the person to check the user name and to create a new application password (a normal login password does not work).")
    if st == 403 or st == 404:
        return out(False, "wp", f"authenticated calls are blocked (HTTP {st})", next_step="Application passwords may be disabled, or a firewall blocks authenticated REST calls. Ask the person to enable them or to allow this agent.")
    if st != 200 or not isinstance(me, dict):
        return out(False, "wp", f"unexpected answer (HTTP {st})", next_step="Ask the person to try the same login in their browser.")
    caps = me.get("capabilities") or {}
    info = {"site_name": j.get("name"), "roles": me.get("roles"), "can_edit_pages": bool(caps.get("edit_pages")), "can_edit_published_pages": bool(caps.get("edit_published_pages")),
            "can_manage_plugins": bool(caps.get("activate_plugins")), "can_manage_options": bool(caps.get("manage_options"))}
    if info["can_manage_plugins"]:
        st, pl = get("/wp-json/wp/v2/plugins?per_page=100", True)
        if st == 200 and isinstance(pl, list):
            info["plugins_total"] = len(pl)
            info["plugins_active"] = sum(1 for p in pl if p.get("status") == "active")
    return out(True, "wp", f"authenticated as role(s) {me.get('roles')} (read-only test, nothing was changed)", info)


def check_ftp(a):
    if not HOST_RE.match(a.host or ""):
        return out(False, "ftp", "invalid host", next_step="Give a plain host name.")
    user, pw = env_secret(a.user_env), env_secret(a.pass_env)
    if not user or not pw:
        return out(False, "ftp", "user or password variable is empty or missing", next_step="Ask the person to put the FTP user and password in the environment and to tell you the two variable names. Never paste them in the chat.")
    if not a.tls and a.host not in ("localhost", "127.0.0.1"):
        return out(False, "ftp", "refusing to send a password over plain FTP", next_step="Ask for FTPS (add --tls) or SFTP (use the ssh type).")
    try:
        f = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=20) if a.tls else ftplib.FTP(timeout=20)
        f.connect(a.host, a.port)
        f.login(user, pw)
        if a.tls:
            f.prot_p()
        cwd = f.pwd()
        f.quit()
    except ftplib.error_perm:
        return out(False, "ftp", "login refused", next_step="Ask the person to check the FTP user and password.")
    except ssl.SSLError as e:
        return out(False, "ftp", f"the server certificate was not accepted ({type(e).__name__})",
                   next_step="Ask the owner for a valid certificate for that host name, or use SFTP (the ssh type). Certificates are never skipped.")
    except (OSError, ftplib.Error) as e:
        return out(False, "ftp", f"cannot connect ({type(e).__name__})", next_step="Check host, port, and that FTPS is enabled if --tls was used.")
    return out(True, "ftp", f"logged in, working directory {cwd} (read-only test, nothing was changed)", {"cwd": cwd})


def check_files(a):
    p = os.path.realpath(a.path)
    if not os.path.isdir(p):
        return out(False, "files", f"{a.path} is not a folder", next_step="Give the path of the site's folder on this machine.")
    names = os.listdir(p)
    caps = {"readable": os.access(p, os.R_OK), "writable": os.access(p, os.W_OK), "entries": len(names),
            "wordpress": "wp-config.php" in names or "wp-content" in names, "git": ".git" in names,
            "static_html": any(n.endswith(".html") for n in names), "package_json": "package.json" in names}
    return out(caps["readable"], "files", "folder found (read-only test, nothing was changed)", caps,
               None if caps["readable"] else "This agent cannot read that folder: ask the person to change its permissions.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="type", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help="also write the JSON result to this file (for fix_tracker.py provide --check)")
    s = sub.add_parser("ssh", parents=[common])
    s.add_argument("--host", required=True)
    s.add_argument("--user", required=True)
    s.add_argument("--port", type=int, default=22)
    s.add_argument("--webroot")
    s.add_argument("--key", help="path of the private key file to use (the file path, never its content)")
    s.add_argument("--known-hosts", help="known_hosts file that holds the server's confirmed key")
    s.set_defaults(fn=check_ssh)
    w = sub.add_parser("wp", parents=[common])
    w.add_argument("--url", required=True)
    w.add_argument("--user-env", required=True)
    w.add_argument("--pass-env", required=True)
    w.set_defaults(fn=check_wp)
    f = sub.add_parser("ftp", parents=[common])
    f.add_argument("--host", required=True)
    f.add_argument("--user-env", required=True)
    f.add_argument("--pass-env", required=True)
    f.add_argument("--port", type=int, default=21)
    f.add_argument("--tls", action="store_true")
    f.set_defaults(fn=check_ftp)
    d = sub.add_parser("files", parents=[common])
    d.add_argument("--path", required=True)
    d.set_defaults(fn=check_files)
    a = ap.parse_args()
    global OUT_PATH
    OUT_PATH = a.out
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
