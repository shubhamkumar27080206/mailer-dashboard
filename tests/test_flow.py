import base64
import io
import unittest
from unittest import mock

import tests.conftest  # noqa: F401

import app as app_module
import contacts as ct
import mailer
from defaults import DEFAULT_BODY, DEFAULT_PROFILE, DEFAULT_SUBJECT


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k): pass
    def login(self, u, p): FakeSMTP.login_args = (u, p)
    def send_message(self, m): FakeSMTP.sent.append(m)
    def quit(self): pass
    def close(self): pass


class TestCompose(unittest.TestCase):
    def c(self, ctx):
        return mailer.compose(DEFAULT_PROFILE, DEFAULT_SUBJECT, DEFAULT_BODY, ctx,
                              {"email": "hr@acme-cloud.com", "name": "", "company": ""})

    def test_context_inserted(self):
        _, body, company = self.c("Immediately available, open to Remote.")
        self.assertIn("Immediately available, open to Remote.", body)
        self.assertEqual(company, "Acme Cloud")

    def test_empty_context_leaves_no_gap(self):
        _, body, _ = self.c("   ")
        self.assertNotIn("\n\n\n", body)
        self.assertNotIn("{context}", body)


class TestContacts(unittest.TestCase):
    def test_csv_and_statuses(self):
        data = b"HR Name,Email ID\nAsha,asha@infosys.com\nBob,bad-email\nAsha2,ASHA@infosys.com\nC,c@x.io\n"
        cols, rows = ct.read_table(data, "list.csv")
        self.assertEqual(ct.detect_email_column(cols, rows), "Email ID")
        out = ct.build_contacts(rows, "Email ID", "HR Name", None, sent={"c@x.io"})
        self.assertEqual([c["status"] for c in out], ["valid", "invalid", "duplicate", "already sent"])

    def test_xlsx_sample(self):
        with open("public/hr_contacts.xlsx", "rb") as f:
            cols, rows = ct.read_table(f.read(), "hr_contacts.xlsx")
        self.assertTrue(rows)
        self.assertIsNotNone(ct.detect_email_column(cols, rows))


class TestApi(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        FakeSMTP.sent = []

    def payload(self, **kw):
        d = {"gmail": "me@gmail.com", "app_password": "abcd efgh ijkl mnop", "profile": DEFAULT_PROFILE,
             "subject": DEFAULT_SUBJECT, "body": DEFAULT_BODY, "context": "Open to remote",
             "contact": {"email": "hr@globex.co.in", "name": "", "company": ""}, "dry_run": False}
        d.update(kw)
        return d

    def test_config_and_parse(self):
        self.assertIn("subject", self.client.get("/api/config").get_json())
        r = self.client.post("/api/parse", data={"file": (io.BytesIO(b"email\na@b.com\n"), "x.csv")})
        self.assertTrue(r.get_json()["ok"])

    def test_dry_run_sends_nothing(self):
        with mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            j = self.client.post("/api/send", json=self.payload(dry_run=True)).get_json()
        self.assertTrue(j["ok"]); self.assertEqual(FakeSMTP.sent, [])

    def test_real_send_one_recipient_with_pdf(self):
        with mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            j = self.client.post("/api/send", json=self.payload()).get_json()
        self.assertTrue(j["ok"]); self.assertEqual(j["company"], "Globex")
        m = FakeSMTP.sent[0]
        self.assertEqual(m["To"], "hr@globex.co.in")
        self.assertIsNone(m["Cc"]); self.assertIsNone(m["Bcc"])
        self.assertEqual(FakeSMTP.login_args[1], "abcdefghijklmnop")  # spaces stripped
        self.assertTrue(any(p.get_content_type() == "application/pdf" for p in m.iter_attachments()))

    def test_bad_template_is_fatal_not_crash(self):
        j = self.client.post("/api/send", json=self.payload(body="Hi {oops")).get_json()
        self.assertFalse(j["ok"]); self.assertTrue(j["fatal"])

    def test_gmail_api_send(self):
        calls = []

        def fake_https(url, data, headers, timeout=20):
            calls.append(url)
            if url == mailer.TOKEN_URL:
                return 200, {"access_token": "tok"}
            self.assertEqual(headers["Authorization"], "Bearer tok")
            return 200, {"id": "1"}

        env = {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "sec"}
        with mock.patch.dict("os.environ", env), mock.patch("mailer._https", fake_https):
            j = self.client.post("/api/send", json=self.payload(method="api", refresh_token="r", app_password="")).get_json()
            bad = self.client.post("/api/send", json=self.payload(method="api", app_password="")).get_json()
            st = self.client.get("/api/oauth/start")
        self.assertTrue(j["ok"], j); self.assertEqual(calls, [mailer.TOKEN_URL, mailer.SEND_URL])
        self.assertTrue(bad["fatal"])
        self.assertEqual(st.status_code, 302); self.assertIn("accounts.google.com", st.location)
        self.assertIn("gmail.send", st.location)

    def test_access_key(self):
        with mock.patch.dict("os.environ", {"APP_ACCESS_KEY": "s3cret"}):
            self.assertEqual(self.client.post("/api/preview", json={}).status_code, 401)
            ok = self.client.post("/api/preview", json={"profile": DEFAULT_PROFILE, "subject": "x", "body": "y",
                                  "contact": {"email": "a@b.com"}}, headers={"X-Access-Key": "s3cret"})
            self.assertEqual(ok.status_code, 200)


if __name__ == "__main__":
    unittest.main()
