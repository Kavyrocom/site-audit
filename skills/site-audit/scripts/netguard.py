"""A local filtering proxy for the audit's Chrome (stdlib only).

Chrome is started with `--proxy-server` pointing here, so EVERY connection it makes goes through this file: the
page itself, scripts, images, frames of another site, service workers, WebSocket, preconnections. A site under audit
cannot make the machine read a private address, a local service or cloud metadata, whatever trick it uses to get
Chrome to ask for it.

How
  - the proxy resolves the host name ITSELF, judges every address it returns with safenet, and connects to the address
    it judged: a DNS answer that changes between the check and the connection (rebinding) gets nothing;
  - HTTPS goes through a CONNECT tunnel: the proxy sees the host and the port, never the content, and does not
    decrypt anything;
  - plain HTTP requests are forwarded one per connection: the proxy answers `Connection: close` and relays nothing
    more from the client after the first request, so a second request can never reach a host that was not judged,
    even when the server keeps its side open;
  - an audit that itself starts on a private host (testing your own localhost or staging) is allowed to stay on THAT
    host (and on the rest of loopback when it started on loopback), never on another private address, and never on a
    link-local address (the cloud metadata service lives there).

Chrome normally skips proxies for loopback addresses; `--proxy-bypass-list=<-loopback>` removes that exception.
"""
import os
import select
import socket
import shutil
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safenet  # noqa: E402

MAX_RESPONSE_SECONDS = 300                  # a whole response, however slowly it comes
MAX_HEAD = 65536
IDLE = 60


def dial(host, port, allow_private, timeout=20):
    """(connected socket, None) or (None, reason). Connects to the very address that was judged."""
    host = host.strip("[]")
    addrs = safenet._resolve(host)
    if not addrs:
        return None, f"{host} does not resolve"
    if allow_private:
        bad = [a for a in addrs if not safenet._is_public(a) and not safenet.private_allowed(a)]
        if bad:
            return None, f"refused: {host} resolves to a private address that is not the host this audit started on"
    else:
        bad = [a for a in addrs if not safenet._is_public(a)]
        if bad:
            return None, f"refused: {host} resolves to a private or local address; a public site must not lead there"
    last = None
    for a in addrs:
        try:
            return socket.create_connection((a, port), timeout=timeout), None
        except OSError as e:
            last = e
    return None, f"cannot connect ({type(last).__name__})"


def _pipe(a, b):
    socks = [a, b]
    try:
        while True:
            ready, _, _ = select.select(socks, [], [], IDLE)
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return
    finally:
        for s in socks:
            try:
                s.close()
            except OSError:
                pass


def _relay_one_response(up, c, method="GET"):
    """Send the upstream answer to the client with `Connection: close`, and nothing else flows from the client to the
    upstream any more: a server that keeps its side open cannot be handed a second request meant for another host."""
    up.settimeout(IDLE)
    head = b""
    try:
        while b"\r\n\r\n" not in head and len(head) < MAX_HEAD:
            chunk = up.recv(8192)
            if not chunk:
                break
            head += chunk
        if b"\r\n\r\n" not in head:
            c.sendall(head)
            return
        raw, rest = head.split(b"\r\n\r\n", 1)
        lines = raw.split(b"\r\n")
        kept = [x for x in lines[1:] if x.split(b":", 1)[0].strip().lower() not in (b"connection", b"keep-alive", b"proxy-connection")]
        c.sendall(lines[0] + b"\r\n" + b"\r\n".join(kept + [b"Connection: close"]) + b"\r\n\r\n" + rest)
        # the response is framed when it can be: stop after the announced length, and never past a total deadline,
        # so a server that keeps its side open or sends a byte a minute cannot hold the connection
        announced = None
        for x in kept:
            name, _, value = x.partition(b":")
            if name.strip().lower() == b"content-length" and value.strip().isdigit():
                announced = int(value.strip())
        status = lines[0].split(b" ")[1] if len(lines[0].split(b" ")) > 1 else b""
        if method.upper() == "HEAD" or status.startswith((b"1", b"204", b"304")):
            announced = 0
        sent = len(rest)
        deadline = time.monotonic() + MAX_RESPONSE_SECONDS
        while announced is None or sent < announced:
            if time.monotonic() > deadline:
                return
            data = up.recv(65536)
            if not data:
                return
            c.sendall(data)
            sent += len(data)
    except OSError:
        return
    finally:
        for s in (up, c):
            try:
                s.close()
            except OSError:
                pass


def _split_hostport(target, default_port):
    if target.startswith("["):
        host, _, rest = target[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port = target.rpartition(":") if target.count(":") == 1 else (target, "", "")
    try:
        return host, int(port) if port else default_port
    except ValueError:
        return host, default_port


class _Handler(socketserver.BaseRequestHandler):
    def reply(self, code, text):
        body = text.encode("utf-8", "replace")
        try:
            self.request.sendall(f"HTTP/1.1 {code} {text[:60]}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("latin-1", "replace") + body)
        except OSError:
            pass
        finally:
            try:
                self.request.close()
            except OSError:
                pass

    def handle(self):
        c = self.request
        c.settimeout(30)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < MAX_HEAD:
                chunk = c.recv(8192)
                if not chunk:
                    return
                head += chunk
        except OSError:
            return
        if b"\r\n\r\n" not in head:
            return self.reply(431, "request head too large")
        raw, rest = head.split(b"\r\n\r\n", 1)
        lines = raw.split(b"\r\n")
        try:
            method, target, version = lines[0].decode("latin-1").split(" ", 2)
        except ValueError:
            return self.reply(400, "bad request")
        srv = self.server
        srv.count()
        if method.upper() == "CONNECT":
            host, port = _split_hostport(target, 443)
            up, why = dial(host, port, srv.allow_private)
            if why:
                srv.note(host, port, why)
                return self.reply(403, why)
            c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                up.sendall(rest)
            c.settimeout(None)
            return _pipe(c, up)
        u = urllib.parse.urlparse(target)
        if u.scheme.lower() != "http" or not u.hostname:
            return self.reply(400, "only absolute http:// requests and CONNECT are served")
        port = u.port or 80
        up, why = dial(u.hostname, port, srv.allow_private)
        if why:
            srv.note(u.hostname, port, why)
            return self.reply(403, why)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        hdrs, upgrade, length, chunked = [], False, 0, False
        for line in lines[1:]:
            k, _, v = line.partition(b":")
            k = k.strip().lower()
            if k in (b"proxy-connection", b"keep-alive", b"connection"):
                continue
            if k == b"upgrade":
                upgrade = True
            if k == b"content-length" and v.strip().isdigit():
                length = int(v.strip())
            if k == b"transfer-encoding" and b"chunked" in v.lower():
                chunked = True
            hdrs.append(line)
        hdrs.append(b"Connection: Upgrade" if upgrade else b"Connection: close")
        if chunked and not upgrade:
            up.close()
            return self.reply(411, "chunked request bodies are not relayed")
        if upgrade:
            up.sendall(f"{method} {path} {version}\r\n".encode("latin-1", "replace") + b"\r\n".join(hdrs) + b"\r\n\r\n" + rest)
            c.settimeout(None)
            return _pipe(c, up)
        body = rest[:length]                              # the body the request announced, never what was pipelined behind it
        up.sendall(f"{method} {path} {version}\r\n".encode("latin-1", "replace") + b"\r\n".join(hdrs) + b"\r\n\r\n" + body)
        try:
            missing = max(0, length - len(body))       # the rest of the request body, nothing more
            while missing > 0:
                chunk = c.recv(min(65536, missing))
                if not chunk:
                    break
                up.sendall(chunk)
                missing -= len(chunk)
        except OSError:
            return
        _relay_one_response(up, c, method)


def short_tempdir(prefix="sa-"):
    """A private folder with a SHORT path. Chrome and the tools that start it open unix sockets under TMPDIR and fail
    with an unreadable error when that path is long (agents and CI often have deep ones)."""
    base = tempfile.gettempdir()
    if len(base) > 40 and os.access("/tmp", os.W_OK):
        base = "/tmp"
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def kill_marked(marker):
    """Kill every process whose command line contains `marker` (a path of a folder only we created). Lighthouse and
    Unlighthouse start Chrome in a process group of its own, which killing the tool's group does not reach."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    n = 0
    for line in out.splitlines():
        pid, _, args = line.strip().partition(" ")
        if marker in args and pid.isdigit() and int(pid) != os.getpid():
            try:
                os.kill(int(pid), signal.SIGKILL)
                n += 1
            except OSError:
                pass
    return n


def cleanup_tempdir(path):
    kill_marked(path)
    shutil.rmtree(path, ignore_errors=True)


class GuardProxy:
    """Start once per audit, pass `flags()` to Chrome, call `stop()` at the end. `refused` lists what was refused."""

    def __init__(self, allow_private=None):
        if allow_private is None:
            allow_private = bool(safenet._AUDIT.get("allow_private"))
        outer = self

        class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
            daemon_threads = True
            allow_reuse_address = True

            def count(self):
                with outer._lock:
                    outer.served += 1

            def note(self, host, port, why):
                with outer._lock:
                    if len(outer.refused) < 200:
                        outer.refused.append({"host": host, "port": port, "why": why})

        self._lock = threading.Lock()
        self.refused = []
        self.served = 0              # connections that went through (a way to prove Chrome really used the proxy)
        self.server = Server(("127.0.0.1", 0), _Handler)
        self.server.allow_private = allow_private
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def flags(self):
        # WebRTC could open UDP sockets that no HTTP proxy sees: it is told to use only proxied connections
        return [f"--proxy-server=http://127.0.0.1:{self.port}", "--proxy-bypass-list=<-loopback>",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--webrtc-ip-handling-policy=disable_non_proxied_udp"]

    def stop(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass
