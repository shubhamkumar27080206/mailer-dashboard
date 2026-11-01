# Resume Mailer Dashboard (Vercel edition)

Upload an Excel/CSV of HR emails, add a short context note, and send your resume **one-to-one**
(never CC/BCC) from your Gmail. The company name is added automatically from each email domain.

> The original Streamlit version cannot run on Vercel (Streamlit needs a long-lived server with
> WebSockets; Vercel runs short, stateless serverless functions). This version is a Flask API
> plus a static HTML page, which is what Vercel is built for.

## Structure
```
public/index.html   the whole UI (static, served by Vercel's CDN)
public/hr_contacts.xlsx  sample HR list
app.py              Flask API: /api/config, parse, contacts, preview, test-login, send, polish
mailer.py           message builder + Gmail SMTP sender (one email per request)
contacts.py         xlsx/xls/csv reader, column detection, validation, de-duplication
company.py          company-name extractor + greeting logic
defaults.py         your profile + default template
ai_polish.py        optional AI polish of the context box
Shubham-Resume.pdf  bundled resume
vercel.json         function config (60 s max, bundles the PDF)
tests/              python -m unittest discover -s tests -t .
```

## How it works on Vercel
- The **browser drives the batch**: it calls `/api/send` once per contact and waits the random delay
  (30-90 s by default) in JavaScript. Each function call is only a few seconds long. **Keep the tab open** while sending; press Stop any time.
- The **sent log, profile and template** are stored in your browser (localStorage), because Vercel's filesystem is read-only/ephemeral.
  "Already sent" protection and the daily limit therefore apply per browser. Use *Download sent_log.csv* for a backup.
- The **App Password** is typed into the page, sent over HTTPS with each request, and never stored or logged.

## Gmail API setup (use this if SMTP is blocked: "Connection unexpectedly closed")
Mail then goes over HTTPS (port 443), so no App Password is needed.
1. [Google Cloud Console](https://console.cloud.google.com/) > create a project > *APIs & Services* > enable **Gmail API**.
2. *OAuth consent screen* > External > add **your Gmail as a Test user**.
3. *Credentials* > *Create credentials* > *OAuth client ID* > type **Web application**. Under *Authorised redirect URIs* add
   `https://YOUR-DOMAIN.vercel.app/api/oauth/callback` (and `http://localhost:3000/api/oauth/callback` for local runs).
4. In Vercel add env vars `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then redeploy.
   Use your **production domain** (preview URLs change, so Google would reject them), or set `OAUTH_REDIRECT_URI` explicitly.
5. Open the dashboard > Step 1 > **Gmail API** > *Authorize with Google* > Allow.
The refresh token is saved only in your browser. Apps in Google's "Testing" mode expire the authorization after ~7 days: just click Authorize again.

## Deploy
**Option A - Git:** push this folder to GitHub, then Vercel > *Add New Project* > import it. No build settings needed (framework is auto-detected as Flask).

**Option B - CLI:**
```
npm i -g vercel
cd resume-mailer-dashboard
vercel          # preview
vercel --prod   # production
```

### Environment variables (Vercel > Project > Settings > Environment Variables)
| Name | Purpose |
|------|---------|
| `APP_ACCESS_KEY` | **Recommended.** If set, the API requires this key (the page asks for it). Stops strangers using your deployment. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Needed for Gmail API mode (see above). |
| `OAUTH_REDIRECT_URI` | Optional: force the redirect URI if auto-detection is wrong. |
| `ANTHROPIC_API_KEY` | Optional. Enables the "Polish my context with AI" button (also uncomment `anthropic` in requirements.txt). |
| `ANTHROPIC_MODEL` | Optional model override. |

## Local run
```
pip install -r requirements.txt
python app.py        # http://localhost:3000
# or: vercel dev
```

## Gmail notes
- Create an App Password: Google Account > Security > 2-Step Verification ON > App passwords.
- Gmail may show a "new sign-in" alert (the login comes from a Vercel data centre). Approve it; if Gmail blocks it, send a few from a different network first or keep batches small.
- Two send methods: **Gmail API** (HTTPS, recommended, works when SMTP is blocked) and **SMTP** with an App Password.
- Keep volume low (20-30/day at first) to avoid spam filtering. Gmail's hard cap is about 500/day.
- Resume upload limit: 3 MB (Vercel request body limit is ~4.5 MB).
