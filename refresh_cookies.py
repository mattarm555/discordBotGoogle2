#!/usr/bin/env python3
# refresh_cookies.py
import os
import sys
import time
from http.cookiejar import MozillaCookieJar, Cookie
from pathlib import Path

try:
    from curl_cffi import Session
except Exception as e:
    print("ERROR: curl_cffi import failed. Did you pip install curl_cffi in the right venv?")
    raise

BASE_DIR = Path(__file__).resolve().parent
COOKIE_FILE = BASE_DIR / "runtime" / "cookies.txt"
IMP_PERSONATE = os.environ.get("IMP_PERSONATE", "chrome124")
TIMEOUT = 15  # seconds

def cookie_to_mozilla_cookie(c):
    # c is expected to be cookie-like (name, value, domain, path, expires, secure)
    # Build a http.cookiejar.Cookie
    return Cookie(
        version=0,
        name=getattr(c, "name", getattr(c, "key", "")),
        value=getattr(c, "value", ""),
        port=None,
        port_specified=False,
        domain=getattr(c, "domain", ""),
        domain_specified=bool(getattr(c, "domain", "")),
        domain_initial_dot=str(getattr(c, "domain", "")).startswith("."),
        path=getattr(c, "path", "/"),
        path_specified=True,
        secure=bool(getattr(c, "secure", False)),
        expires=getattr(c, "expires", None),
        discard=False,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False
    )

def save_cookies_netscape(cookiejar, dest: Path):
    mc = MozillaCookieJar(str(dest))
    # cookiejar is iterable; copy cookies
    for c in cookiejar:
        try:
            mc.set_cookie(cookie_to_mozilla_cookie(c))
        except Exception:
            # best-effort: ignore cookies we can't convert
            continue
    mc.save(ignore_discard=True, ignore_expires=True)
    print(f"[ok] saved cookies to: {dest}")

def refresh_visitor_cookies(dest_path=COOKIE_FILE, impersonate=IMP_PERSONATE):
    print(f"[start] requesting youtube with impersonate={impersonate}")
    s = Session()
    try:
        r = s.get("https://www.youtube.com/", impersonate=impersonate, timeout=TIMEOUT)
        code = getattr(r, "status_code", None)
        print(f"[got] status={code}")
        # optionally detect challenge: naive check
        text_snippet = getattr(r, "text", "")[:200].lower() if hasattr(r, "text") else ""
        if "captcha" in text_snippet or "challenge" in text_snippet or code in (403, 429):
            print("[warn] server may have returned a challenge/captcha or anti-bot page. Not attempting to bypass.")
            # still attempt to save whatever cookies we got
        save_cookies_netscape(s.cookies, Path(dest_path))
    finally:
        try:
            s.close()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        refresh_visitor_cookies()
    except Exception as e:
        print("Exception during refresh:", e)
        sys.exit(2)
