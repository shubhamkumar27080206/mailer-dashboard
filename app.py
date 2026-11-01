"""Resume Mailer - Flask API for Vercel.  Static UI lives in public/index.html.

Vercel serverless functions are stateless and short-lived, so:
  * the browser drives the send loop (one POST /api/send per email, with the delay in JS)
  * the sent log + settings live in the browser (localStorage)
  * the Gmail App Password is only used for the request and never stored or logged
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import urllib.parse
from pathlib import Path

from flask import Flask, jsonify, make_response, redirect, request

import ai_polish
import contacts as ct
from defaults import DEFAULT_BODY, DEFAULT_OVERRIDES, DEFAULT_PROFILE, DEFAULT_SUBJECT
from mailer import (FatalSendError, GmailApiSender, GmailSender, _https, build_message, compose,
                    refresh_access_token, test_login, TOKEN_URL)

BASE = Path(__file__).resolve().parent
DEFAULT_RESUME = BASE / "Shubham-Resume.pdf"
MAX_RESUME_BYTES = 3 * 1024 * 1024  # Vercel request bodies are capped at ~4.5 MB

app = Flask(__name__, static_folder="public", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024


@app.before_request
def check_access():
    """Optional shared secret: set APP_ACCESS_KEY in Vercel to lock the API."""
    key = os.environ.get("APP_ACCESS_KEY")
    if not key or request.path == "/api/config" or request.path.startswith("/api/oauth/"):
        return None
    if not hmac.compare_digest(request.headers.get("X-Access-Key", ""), key):
        return jsonify(ok=False, error="Wrong or missing access key."), 401


@app.get("/")
def index():  # local dev only; on Vercel public/ is served by the CDN
    return app.send_static_file("index.html")


def _google() -> tuple[str, str]:
    return os.environ.get("GOOGLE_CLIENT_ID", ""), os.environ.get("GOOGLE_CLIENT_SECRET", "")


def _redirect_uri() -> str:
    if os.environ.get("OAUTH_REDIRECT_URI"):
        return os.environ["OAUTH_REDIRECT_URI"]
    proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0]
    host = request.headers.get("X-Forwarded-Host", request.host).split(",")[0]
    return f"{proto}://{host}/api/oauth/callback"


@app.get("/api/oauth/start")
def oauth_start():
    cid, secret = _google()
    if not (cid and secret):
        return "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set on this deployment.", 500
    state = secrets.token_urlsafe(24)
    q = urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": _redirect_uri(), "response_type": "code",
        "scope": "openid email https://www.googleapis.com/auth/gmail.send",
        "access_type": "offline", "prompt": "consent", "state": state})
    resp = make_response(redirect("https://accounts.google.com/o/oauth2/v2/auth?" + q))
    resp.set_cookie("rm_state", state, max_age=600, httponly=True, secure=request.scheme == "https" or
                    request.headers.get("X-Forwarded-Proto") == "https", samesite="Lax")
    return resp


@app.get("/api/oauth/callback")
def oauth_callback():
    cid, secret = _google()
    if request.args.get("error"):
        return f"Google sign-in was cancelled: {request.args['error']}", 400
    if not request.args.get("state") or request.args.get("state") != request.cookies.get("rm_state"):
        return "Invalid sign-in state. Close this tab and click Authorize again.", 400
    status, j = _https(TOKEN_URL, urllib.parse.urlencode({
        "code": request.args.get("code", ""), "client_id": cid, "client_secret": secret,
        "redirect_uri": _redirect_uri(), "grant_type": "authorization_code"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200 or not j.get("refresh_token"):
        return f"Google did not return a refresh token ({j.get('error_description') or j.get('error') or status}). " \
               "Remove the app at myaccount.google.com/permissions and try again.", 400
    email = ""
    try:  # id_token came straight from Google over TLS; we only read the email claim
        payload = j["id_token"].split(".")[1]
        email = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("email", "")
    except Exception:
        pass
    data = json.dumps({"refresh_token": j["refresh_token"], "email": email, "at": __import__("time").time()})
    # The token is handed to YOUR browser only (localStorage); the server never stores it.
    html = ("<!doctype html><meta charset=utf-8><title>Authorized</title><p>Authorized. Returning to the dashboard...</p>"
            "<script>try{localStorage.setItem('rm_token'," + json.dumps(data) + ")}catch(e){}"
            "location.replace('/?auth=ok')</script>")
    resp = make_response(html)
    resp.delete_cookie("rm_state")
    return resp


@app.get("/api/config")
def config():
    return jsonify(profile=DEFAULT_PROFILE, subject=DEFAULT_SUBJECT, body=DEFAULT_BODY,
                   polish=ai_polish.available(), locked=bool(os.environ.get("APP_ACCESS_KEY")),
                   has_default_resume=DEFAULT_RESUME.exists(), oauth=bool(_google()[0] and _google()[1]),
                   redirect_uri=_redirect_uri())


@app.post("/api/parse")
def parse():
    f = request.files.get("file")
    if f is None:
        return jsonify(ok=False, error="No file uploaded."), 400
    try:
        cols, rows = ct.read_table(f.read(), f.filename or "")
    except Exception as e:
        return jsonify(ok=False, error=f"Could not read the file: {e}"), 400
    if not rows:
        return jsonify(ok=False, error="The file has no rows."), 400
    return jsonify(ok=True, columns=cols, rows=rows,
                   email_col=ct.detect_email_column(cols, rows),
                   name_col=ct.detect_name_column(cols),
                   company_col=ct.detect_company_column(cols))


@app.post("/api/contacts")
def contacts_():
    d = request.get_json(force=True)
    table = ct.build_contacts(d["rows"], d["email_col"], d.get("name_col") or None,
                              d.get("company_col") or None, set(d.get("sent", [])), DEFAULT_OVERRIDES)
    return jsonify(ok=True, contacts=table)


@app.post("/api/preview")
def preview():
    d = request.get_json(force=True)
    try:
        subject, body, company = compose(d["profile"], d["subject"], d["body"], d.get("context", ""),
                                         d["contact"], DEFAULT_OVERRIDES)
    except (ValueError, IndexError, KeyError) as e:
        return jsonify(ok=False, error=f"Template problem (check your {{ }} braces): {e}")
    return jsonify(ok=True, subject=subject, body=body, company=company)


@app.post("/api/test-login")
def test_login_():
    d = request.get_json(force=True)
    if not d.get("gmail") or not d.get("app_password"):
        return jsonify(ok=False, error="Enter your Gmail address and App Password first.")
    ok, msg = test_login(d["gmail"].strip(), d["app_password"])
    return jsonify(ok=ok, message=msg)


@app.post("/api/test-api")
def test_api_():
    d = request.get_json(force=True)
    cid, secret = _google()
    if not (cid and secret):
        return jsonify(ok=False, message="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set on the server.")
    if not d.get("refresh_token"):
        return jsonify(ok=False, message="Not authorized yet. Click 'Authorize with Google'.")
    try:
        refresh_access_token(cid, secret, d["refresh_token"])
        return jsonify(ok=True, message="Google authorization is valid. Emails will be sent over HTTPS (port 443).")
    except FatalSendError as e:
        return jsonify(ok=False, message=str(e))


@app.post("/api/polish")
def polish():
    d = request.get_json(force=True)
    if not ai_polish.available():
        return jsonify(ok=False, error="AI polish is not enabled on this deployment.")
    try:
        return jsonify(ok=True, text=ai_polish.polish_context(d.get("text", "")))
    except Exception as e:
        return jsonify(ok=False, error=str(e))


@app.post("/api/send")
def send():
    """Send (or dry-run) exactly ONE email. The browser loops over contacts."""
    d = request.get_json(force=True)
    gmail, contact, profile = (d.get("gmail") or "").strip(), d["contact"], d["profile"]
    dry_run = bool(d.get("dry_run", True))

    resume = b""
    if d.get("resume_b64"):
        resume = base64.b64decode(d["resume_b64"])
        if len(resume) > MAX_RESUME_BYTES:
            return jsonify(ok=False, fatal=True, error="Resume PDF is too large (max 3 MB).")
    elif DEFAULT_RESUME.exists():
        resume = DEFAULT_RESUME.read_bytes()
    if not resume:
        return jsonify(ok=False, fatal=True, error="No resume PDF available. Upload one.")

    sender_addr = gmail or profile.get("email", "")
    attach = f"{(profile.get('name') or 'My').strip().replace(' ', '_')}_Resume.pdf"
    try:
        msg, company = build_message(profile, d["subject"], d["body"], d.get("context", ""),
                                     resume, attach, contact, sender_addr, DEFAULT_OVERRIDES)
    except (ValueError, IndexError, KeyError) as e:
        return jsonify(ok=False, fatal=True, error=f"Template problem (check your {{ }} braces): {e}")

    if dry_run:
        return jsonify(ok=True, dry_run=True, company=company, subject=msg["Subject"])

    if d.get("method") == "api":
        cid, secret = _google()
        if not (cid and secret and d.get("refresh_token")):
            return jsonify(ok=False, fatal=True, error="Not authorized with Google yet. Click 'Authorize with Google' in Step 1.")
        sender = GmailApiSender(cid, secret, d["refresh_token"])
    else:
        if not gmail or not d.get("app_password"):
            return jsonify(ok=False, fatal=True, error="Enter your Gmail address and App Password.")
        sender = GmailSender(gmail, d["app_password"])
    try:
        sender.send(msg)
        return jsonify(ok=True, company=company)
    except FatalSendError as e:
        return jsonify(ok=False, fatal=True, error=str(e))
    except Exception as e:  # one bad address must never stop the batch
        return jsonify(ok=False, fatal=False, error=str(e)[:300])
    finally:
        sender.close()


if __name__ == "__main__":  # local dev:  python app.py
    app.run(debug=True, port=3000)
