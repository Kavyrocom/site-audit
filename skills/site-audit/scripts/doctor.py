#!/usr/bin/env python3
"""Can this machine run the audit, and which parts? One read-only check before the first audit (stdlib only).

    python3 -I doctor.py            # human-readable list
    python3 -I doctor.py --json     # the same, for a script

It looks at: Python, Chrome or Chromium, Lighthouse, Unlighthouse, a Google API key (the NAME of the variable is
reported, never its value), the operating system, whether it runs as root, and whether the current folder sits in a git
repository (the audit folder must not). It changes nothing and sends nothing over the network.

Exit code 0: the core of the audit can run (Python is recent enough). Missing optional pieces are listed with what is lost
without them and how to install them: the audit then marks those parts "not measured" instead of guessing.
Exit code 1: Python is too old, nothing can run.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render  # noqa: E402  (find_chrome)

KEY_NAMES = ("PAGESPEED_API_KEY", "PSI_API_KEY", "GOOGLE_API_KEY")


def _version(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        out = (p.stdout or p.stderr or "").strip().splitlines()
        return out[0][:80] if out and p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def check():
    items = []

    def add(name, status, detail, lost=None, fix=None):
        items.append({"name": name, "status": status, "detail": detail, "without_it": lost, "how_to_fix": fix})

    v = sys.version_info
    ok_py = v >= (3, 9)
    add("python", "ok" if ok_py else "missing", f"Python {v.major}.{v.minor}.{v.micro}",
        None if ok_py else "nothing runs (the scripts need Python 3.9 or newer)", None if ok_py else "Install Python 3.9 or newer from python.org")

    chrome = render.find_chrome()
    add("chrome", "ok" if chrome else "missing", chrome or "Chrome, Chromium or Edge not found",
        None if chrome else "screens, rendered text, the browser network view (render.py, devtools.py) and Lighthouse: performance, UX, conversion and copy are then judged on the raw HTML only, or not measured",
        None if chrome else "Install Google Chrome or Chromium, or set CHROME_PATH to the program")

    lh = shutil.which("lighthouse")
    lh_version = _version([lh, "--version"]) if lh else None
    add("lighthouse", "ok" if lh_version else "missing", f"Lighthouse {lh_version}" if lh_version else "lighthouse not found on the PATH",
        None if lh_version else "lab speed, accessibility and SEO scores (lh_median.py): the performance domain goes to 'not measured' unless a Google key gives a lab run",
        None if lh_version else "npm install -g lighthouse (needs Node.js)")

    ul = shutil.which("unlighthouse-ci")
    add("unlighthouse", "ok" if ul else "optional", "unlighthouse-ci found" if ul else "unlighthouse-ci not found",
        None if ul else "screening many pages at once (lh_site.py); lh_median.py on the 3 key pages is used instead",
        None if ul else "npm install -g unlighthouse")

    key = next((k for k in KEY_NAMES if os.environ.get(k)), None)
    add("google_api_key", "ok" if key else "optional", f"found in ${key}" if key else "none of " + ", ".join(KEY_NAMES) + " is set",
        None if key else "real-visitor data (Core Web Vitals over 28 days) and Google's own lab run (psi.py): 'Google data not measured'",
        None if key else "Create a free key (APIs: PageSpeed Insights and Chrome UX Report) and put it in the environment")

    system = platform.system()
    if system == "Windows":
        add("system", "warning", "Windows", "the scripts are tested on Linux only: on Windows, a timeout in a browser step may not stop the browser cleanly",
            "Run the audit in WSL (Windows Subsystem for Linux), or tell the author what you see")
    elif system == "Linux":
        add("system", "ok", f"Linux {platform.machine()}")
    else:
        add("system", "ok", f"{system} {platform.machine()} (the scripts are tested on Linux; this system is expected to work but is not verified)")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        add("user", "warning", "running as root", "Chrome starts without its sandbox, which makes a hostile page more dangerous",
            "Run the audit as a normal user, on a machine without secrets")
    else:
        add("user", "ok", "normal user")

    inside_git = None
    if shutil.which("git"):
        try:
            p = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, timeout=10)
            inside_git = p.returncode == 0 and p.stdout.strip() == "true"
        except (OSError, subprocess.SubprocessError):
            inside_git = None
    if inside_git:
        add("work_folder", "warning", "the current folder is inside a git repository", "the audit folder (evidence, screens) could be committed and published by mistake",
            "Create the audit folder outside any repository, for example in your home folder")
    else:
        add("work_folder", "ok", "the current folder is not in a git repository" if inside_git is False else "git not installed: nothing to commit by mistake")
    return items


def ready_for(items):
    by = {i["name"]: i["status"] == "ok" for i in items}
    parts = {
        "facts, crawl, consistency, report (HTML only)": by["python"],
        "rendered screens and text, browser network view": by["python"] and by["chrome"],
        "lab speed and accessibility scores": by["python"] and by["chrome"] and by["lighthouse"],
        "real-visitor data (Google)": by["python"] and by["google_api_key"],
        "many pages at once": by["python"] and by["chrome"] and by["unlighthouse"],
    }
    return parts


def main():
    ap = argparse.ArgumentParser(description="Check what this machine can run (read-only).")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    items = check()
    parts = ready_for(items)
    python_ok = items[0]["status"] == "ok"
    if a.json:
        print(json.dumps({"ok": python_ok, "checks": items, "can_run": parts}, ensure_ascii=False, indent=2))
        return 0 if python_ok else 1
    sign = {"ok": "ok      ", "missing": "MISSING ", "optional": "optional", "warning": "WARNING "}
    for i in items:
        print(f"{sign[i['status']]} {i['name']}: {i['detail']}")
        if i["status"] != "ok":
            if i["without_it"]:
                print(f"           {'risk' if i['status'] == 'warning' else 'without it'}: {i['without_it']}")
            if i["how_to_fix"]:
                print(f"           to fix: {i['how_to_fix']}")
    print()
    for part, can in parts.items():
        print(f"{'can run' if can else 'cannot':<8} {part}")
    return 0 if python_ok else 1


if __name__ == "__main__":
    sys.exit(main())
