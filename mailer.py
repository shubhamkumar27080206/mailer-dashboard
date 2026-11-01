"""Message building and Gmail SMTP sending (one connection per request, serverless-friendly)."""
from __future__ import annotations

import base64
import json
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import escape

from company import make_greeting, resolve_company


def make_ssl_context() -> ssl.SSLContext:
    """TLS context using the certifi CA bundle (falls back to Python's default)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class FatalSendError(Exception):
    """Sending must stop (bad login, Gmail quota reached...)."""


# --------------------------------------------------------------------------- templates
class _Safe(dict):
    """Unknown {placeholders} are left as-is instead of crashing."""

    def __missing__(self, key):
        return "{" + key + "}"


def compose(profile: dict, subject_tpl: str, body_tpl: str, context: str, contact: dict,
            overrides: dict | None = None) -> tuple[str, str, str]:
    """Fill the templates for one contact -> (subject, body, company).

    An empty {context} paragraph is removed completely (no blank gap).
    Raises ValueError if a template has broken braces.
    """
    company, known = resolve_company(contact["email"], contact.get("company", ""), overrides)
    name = contact.get("name", "")
    ctx = _Safe({k: v for k, v in profile.items() if k != "name"})
    ctx.update(
        my_name=profile["name"],
        name=name,
        company=company if known else "your company",
        at_company=f" at {company}" if known else "",
        greeting=make_greeting(name, company, known),
        context=(context or "").strip(),
    )
    subject = " ".join(subject_tpl.format_map(ctx).split())
    body = "\n".join(line.rstrip() for line in body_tpl.format_map(ctx).splitlines())
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return subject, body, company if known else ""


def text_to_html(text: str) -> str:
    """Tiny plain-text -> HTML: paragraphs, line breaks and '- ' bullet lists."""
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        buf: list[str] = []
        bullets: list[str] = []

        def flush_text():
            if buf:
                out.append("<p>" + "<br>".join(escape(l) for l in buf) + "</p>")
                buf.clear()

        def flush_bullets():
            if bullets:
                out.append("<ul>" + "".join(f"<li>{escape(b)}</li>" for b in bullets) + "</ul>")
                bullets.clear()

        for line in para.splitlines():
            if line.lstrip().startswith("- "):
                flush_text()
                bullets.append(line.lstrip()[2:])
            else:
                flush_bullets()
                buf.append(line)
        flush_text()
        flush_bullets()
    return '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">' + "".join(out) + "</div>"


def build_message(profile: dict, subject_tpl: str, body_tpl: str, context: str,
                  resume_bytes: bytes, attach_name: str, contact: dict, sender: str,
                  overrides: dict | None = None) -> tuple[EmailMessage, str]:
    subject, body, company = compose(profile, subject_tpl, body_tpl, context, contact, overrides)
    msg = EmailMessage()
    msg["From"] = formataddr((profile["name"], sender))
    msg["To"] = contact["email"]  # exactly ONE recipient: never CC / BCC
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="gmail.com")
    msg["Reply-To"] = profile.get("email") or sender
    msg.set_content(body)
    msg.add_alternative(text_to_html(body), subtype="html")
    if resume_bytes:
        msg.add_attachment(resume_bytes, maintype="application", subtype="pdf", filename=attach_name)
    return msg, company


# --------------------------------------------------------------------------- Gmail
class GmailSender:
    def __init__(self, address: str, app_password: str, host: str = "smtp.gmail.com", port: int = 465):
        self.address, self.password = address, app_password.replace(" ", "")
        self.host, self.port, self.server = host, port, None

    def _open(self, port: int):
        """Open + log in on one port. 465 = implicit SSL, 587 = STARTTLS."""
        ctx = make_ssl_context()
        if port == 465:
            server = smtplib.SMTP_SSL(self.host, 465, context=ctx, timeout=20)
        else:
            server = smtplib.SMTP(self.host, port, timeout=20)
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
        try:
            server.login(self.address, self.password)
        except Exception:
            try:
                server.close()
            except Exception:
                pass
            raise
        return server

    def connect(self) -> None:
        """Try port 465 (SSL) first, then 587 (STARTTLS) if the network drops/blocks the first."""
        self.close()
        ports = [self.port] + [p for p in (465, 587) if p != self.port]
        errors = []
        for port in ports:
            try:
                self.server = self._open(port)
                self.port = port
                return
            except smtplib.SMTPAuthenticationError as e:
                self.server = None
                raise FatalSendError(
                    "Gmail login failed. Use a 16-character App Password (not your normal "
                    "password) and make sure 2-Step Verification is ON."
                ) from e
            except ssl.SSLCertVerificationError as e:
                self.server = None
                raise FatalSendError(f"SSL certificate problem while contacting Gmail: {e}") from e
            except (OSError, smtplib.SMTPException) as e:
                self.server = None
                errors.append(f"port {port}: {e}")
        raise FatalSendError(
            "Could not connect to Gmail on port 465 or 587 (" + "; ".join(errors) + "). "
            "Check the address / App Password and try again."
        )

    def send(self, msg: EmailMessage) -> None:
        if self.server is None:
            self.connect()
        try:
            self.server.send_message(msg)
        except (smtplib.SMTPServerDisconnected, ConnectionError, TimeoutError):
            self.connect()  # one reconnect, then retry
            self.server.send_message(msg)
        except smtplib.SMTPResponseException as e:
            text = f"{e.smtp_code} {e.smtp_error!r}".lower()
            if e.smtp_code in (421, 450, 452, 454) or "5.4.5" in text or "limit" in text:
                raise FatalSendError(f"Gmail sending limit reached ({e.smtp_code}). Try again tomorrow.") from e
            raise

    def close(self) -> None:
        try:
            if self.server:
                self.server.quit()
        except Exception:
            pass
        self.server = None


def test_login(address: str, app_password: str) -> tuple[bool, str]:
    """Used by the 'Test login' button."""
    s = GmailSender(address, app_password)
    try:
        s.connect()
        return True, "Login successful. Gmail accepted your App Password."
    except FatalSendError as e:
        return False, str(e)
    finally:
        s.close()


# --------------------------------------------------------------------------- Gmail API (HTTPS, port 443)
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _https(url: str, data: bytes, headers: dict, timeout: int = 20) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=make_ssl_context()) as r:
            body = r.read().decode() or "{}"
            return r.status, json.loads(body)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": raw[:300]}


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    status, j = _https(TOKEN_URL, urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"})
    if status != 200 or "access_token" not in j:
        raise FatalSendError("Google authorization failed or expired "
                             f"({j.get('error_description') or j.get('error')}). Click 'Authorize with Google' again.")
    return j["access_token"]


class GmailApiSender:
    """Same interface as GmailSender, but talks HTTPS to the Gmail API (works when SMTP is blocked)."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.cid, self.secret, self.refresh = client_id, client_secret, refresh_token
        self.token = ""

    def connect(self) -> None:
        self.token = refresh_access_token(self.cid, self.secret, self.refresh)

    def send(self, msg: EmailMessage) -> None:
        if not self.token:
            self.connect()
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        status, j = _https(SEND_URL, json.dumps({"raw": raw}).encode(),
                           {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        if status == 200:
            return
        err = j.get("error")
        text = (json.dumps(err) if isinstance(err, dict) else str(err)).lower()
        if status == 401:
            raise FatalSendError("Google authorization expired. Click 'Authorize with Google' again.")
        if status == 403 and ("insufficient" in text or "scope" in text):
            raise FatalSendError("Google did not grant permission to send mail. Authorize again and tick the Gmail send permission.")
        if status == 429 or "ratelimit" in text or "quota" in text or "limit exceeded" in text:
            raise FatalSendError("Gmail sending limit reached. Try again tomorrow.")
        raise RuntimeError(f"Gmail API {status}: {text[:250]}")

    def close(self) -> None:
        pass
