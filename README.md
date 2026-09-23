# MailVeyra

MailVeyra is a truth-preserving AI email assistant. The first workflow helps generate evidence-backed job application emails from a candidate profile and job description.

The V1 pipeline is:

```text
extract -> binary match -> draft -> approve -> mock send
```

Important constraints:

- Matching is deterministic and binary: `matched_skills` / `gap_skills`.
- Zero skill overlap blocks draft generation unless explicitly confirmed.
- Email sending is mock/console only in this phase.
- Sending requires approval and uses an immutable `approved_snapshot`.
- LangChain is only used optionally for structured-output LLM calls.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

By default the app uses local SQLite at `./mailveyra.db` so the core flow works without Postgres or Gemini.

Open the frontend:

```text
http://127.0.0.1:8000/
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

To use Gemini structured-output calls later:

```powershell
pip install -e ".[llm,dev]"
$env:GEMINI_API_KEY="..."
```

## Test

```powershell
pytest
```

