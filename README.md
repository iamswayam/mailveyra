# MailVeyra

MailVeyra is an AI Gmail assistant for truthful job application emails.

It lets a user log in with Gmail, save a profile/resume, paste or attach a job description, generate a draft, revise it in chat, approve it, and send it from the logged-in Gmail account.

## Workflow

```text
Gmail login -> profile/resume -> chat with JD -> draft -> revise -> approve -> send with Gmail
```

## Features

- Google OAuth login
- Send email from the logged-in Gmail account
- Gemini model fallback:
  - `gemini-3.1-flash-lite`
  - `gemini-2.5-flash-lite`
  - `gemini-3-flash-preview`
- Candidate profile with name, email, phone, location, summary, skills, experience, projects, education
- Resume upload and attachment support
- Job description input by text, PDF/text file, or image
- Chat-based draft creation and revision
- Gmail-style draft UI:
  - `To*`
  - `Cc/Bcc`
  - `Subject*`
  - `Body*`
  - attachments
- Approval required before send
- Approved drafts are frozen
- Duplicate successful sends are blocked
- Send logs are stored
- Dark UI with optional light mode

## Safety Rules

- The app must not claim candidate skills or experience that are not in the profile/resume.
- Skill matching remains deterministic and binary:
  - `matched_skills`
  - `gap_skills`
- Zero skill overlap blocks draft generation until the user explicitly confirms.
- Real Gmail sending requires login and approval.
- `To`, `Subject`, and `Body` are required before approval/send.

## Tech Stack

- Python
- FastAPI
- SQLAlchemy
- SQLite for local development
- Pydantic
- Gemini API
- Gmail API
- Plain HTML/CSS/JavaScript frontend
- Pytest

## Setup

Use the project virtual environment.

```powershell
cd D:\Projects\Email-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Environment

Create `.env`:

```env
GEMINI_API_KEY=your_gemini_key
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
APP_SECRET_KEY=your_random_secret
```

Google OAuth redirect URI:

```text
http://127.0.0.1:8000/auth/google/callback
```

Required Gmail scope:

```text
https://www.googleapis.com/auth/gmail.send
```

Generate an app secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Run

```powershell
cd D:\Projects\Email-agent
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

Frontend:

```text
http://127.0.0.1:8000/
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## Test

```powershell
cd D:\Projects\Email-agent
.\.venv\Scripts\Activate.ps1
python -m pytest
```

Tests use the local fallback client and do not call Gemini.

## Local Data

Ignored local files:

- `.env`
- `.venv/`
- `mailveyra.db`
- uploaded files under `data/uploads/`

## Current Limits

- SQLite is used for local development.
- OAuth tokens are stored locally in SQLite for development.
- Gmail send is implemented for local single-user use, not production multi-user deployment.
- No hosted deployment configuration yet.

