<div align="center">
  <h1>MailVeyra</h1>
  <p><strong>AI Gmail assistant for truthful, evidence-backed job application emails.</strong></p>
  <p>
    <a href="#features">Features</a>
    ·
    <a href="#setup">Setup</a>
    ·
    <a href="#workflow">Workflow</a>
    ·
    <a href="#safety-rules">Safety</a>
  </p>
  <p>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white">
    <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-Backend-009688?style=for-the-badge&logo=fastapi&logoColor=white">
    <img alt="Gemini" src="https://img.shields.io/badge/Gemini-AI-6F42C1?style=for-the-badge">
    <img alt="Gmail" src="https://img.shields.io/badge/Gmail-Send-EA4335?style=for-the-badge&logo=gmail&logoColor=white">
  </p>
</div>

---

## Overview

MailVeyra helps a user create a personalized job application email from a candidate profile, resume, and job description. It drafts the email with Gemini, keeps candidate claims grounded in stored profile/resume evidence, requires human approval, then sends from the logged-in Gmail account.

```text
Gmail login -> profile/resume -> chat with JD -> draft -> revise -> approve -> send with Gmail
```

## Features

| Area | What MailVeyra does |
| --- | --- |
| Gmail auth | Google OAuth login and Gmail API sending |
| AI drafting | Gemini model fallback for extraction, drafting, and revision |
| Candidate profile | Name, email, phone, location, summary, skills, experience, projects, education |
| Resume | Upload resume and attach it to approved emails |
| Job input | Paste text or upload PDF/text/image job descriptions |
| Chat workflow | Generate a draft, then ask for revisions in chat |
| Draft UI | Gmail-style compose panel with To, Cc, Bcc, Subject, Body, and Attachments |
| Approval | Approved drafts are frozen before sending |
| Safety | Duplicate sends are blocked and send logs are stored |

## UI Flow

```text
Logged out
  -> Gmail login
  -> Profile setup
  -> Resume upload
  -> Chat with job description
  -> Review generated draft
  -> Revise if needed
  -> Approve
  -> Confirm send
  -> Gmail send result
```

## Safety Rules

- The app must not claim candidate skills or experience that are not in the profile or resume.
- Skill matching is deterministic and binary:
  - `matched_skills`
  - `gap_skills`
- Zero skill overlap blocks draft generation until the user explicitly confirms.
- Gmail sending requires login, required draft fields, and approval.
- `To`, `Subject`, and `Body` are required before approval/send.
- Approved drafts are frozen.
- Duplicate successful sends are blocked.

## Gemini Fallback

MailVeyra tries Gemini models in this order:

```text
gemini-3.1-flash-lite
gemini-2.5-flash-lite
gemini-3-flash-preview
```

If a model fails or returns invalid structured output, the backend falls back to the next model.

## Tech Stack

| Layer | Stack |
| --- | --- |
| Backend | FastAPI, SQLAlchemy, Pydantic |
| Database | SQLite for local development |
| AI | Gemini API |
| Email | Gmail API |
| Frontend | Plain HTML, CSS, JavaScript |
| Tests | Pytest |

## Setup

Use the project virtual environment only.

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

Generate `APP_SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Google OAuth redirect URI:

```text
http://127.0.0.1:8000/auth/google/callback
```

Required Gmail scope:

```text
https://www.googleapis.com/auth/gmail.send
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

Tests use the local fallback client and do not call Gemini or Gmail.

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
- History can show send logs, but reopening historical drafts needs more backend work.
- No hosted deployment configuration yet.
