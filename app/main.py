from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import (
    Application,
    CandidateProfile,
    EmailDraft,
    EmailSendLog,
    JobPost,
    User,
)
from app.schemas import (
    ApplicationIn,
    ApplicationOut,
    CandidateProfileIn,
    CandidateProfileOut,
    ChatMessageOut,
    CurrentUserOut,
    DraftWarning,
    EmailDraftOut,
    EmailDraftStructured,
    EmailDraftUpdate,
    ExtractedJob,
    JobPostIn,
    JobPostOut,
    JobPostUpdate,
    MatchResult,
    SendLogOut,
)
from app.services.files import read_text_from_file, save_upload
from app.services.gmail_sender import GmailSender
from app.services.llm import get_llm_client
from app.services.matching import binary_match
from app.services.oauth import (
    exchange_code,
    google_login_url,
    make_state,
    refresh_access_token,
    verify_state,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MailVeyra")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse("app/static/index.html")


def ensure_sqlite_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    statements = {
        "users": {
            "google_access_token": "ALTER TABLE users ADD COLUMN google_access_token TEXT",
            "google_refresh_token": "ALTER TABLE users ADD COLUMN google_refresh_token TEXT",
            "google_token_expires_at": "ALTER TABLE users ADD COLUMN google_token_expires_at DATETIME",
        },
        "candidate_profiles": {
            "email": "ALTER TABLE candidate_profiles ADD COLUMN email VARCHAR(255)",
            "phone": "ALTER TABLE candidate_profiles ADD COLUMN phone VARCHAR(100)",
            "location": "ALTER TABLE candidate_profiles ADD COLUMN location VARCHAR(255)",
        },
        "email_drafts": {
            "cc": "ALTER TABLE email_drafts ADD COLUMN cc JSON DEFAULT '[]'",
            "bcc": "ALTER TABLE email_drafts ADD COLUMN bcc JSON DEFAULT '[]'",
            "attachments": "ALTER TABLE email_drafts ADD COLUMN attachments JSON DEFAULT '[]'",
            "model_used": "ALTER TABLE email_drafts ADD COLUMN model_used VARCHAR(100)",
        },
    }
    with engine.begin() as conn:
        existing_tables = set(inspect(conn).get_table_names())
        for table, columns in statements.items():
            if table not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspect(conn).get_columns(table)}
            for column_name, ddl in columns.items():
                if column_name not in existing_columns:
                    conn.execute(text(ddl))


ensure_sqlite_columns()


def ensure_default_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.id == 1))
    if user:
        return user
    user = User(id=1, email="local@example.com", name="Local User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_from_cookie(db: Session, user_id: str | None) -> User | None:
    if not user_id:
        return None
    try:
        return db.get(User, int(user_id))
    except ValueError:
        return None


def current_or_default_user(db: Session, mailveyra_user_id: str | None = None) -> User:
    return get_user_from_cookie(db, mailveyra_user_id) or ensure_default_user(db)


async def access_token_for_user(user: User, db: Session) -> str:
    if not user.google_access_token:
        raise HTTPException(status_code=401, detail="Login with Gmail before sending real email")
    expires_at = user.google_token_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at and expires_at <= datetime.now(UTC):
        if not user.google_refresh_token:
            raise HTTPException(status_code=401, detail="Gmail token expired. Login again.")
        refreshed = await refresh_access_token(user.google_refresh_token)
        user.google_access_token = refreshed["access_token"]
        user.google_token_expires_at = refreshed["expires_at"]
        db.commit()
    return user.google_access_token


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/google/login")
def google_login(response: Response) -> RedirectResponse:
    state = make_state()
    redirect = RedirectResponse(google_login_url(state))
    redirect.set_cookie("mailveyra_oauth_state", state, httponly=True, samesite="lax")
    return redirect


@app.get("/auth/google/callback")
async def google_callback(
    code: str,
    state: str,
    db: Annotated[Session, Depends(get_db)],
    mailveyra_oauth_state: str | None = Cookie(default=None),
):
    if not mailveyra_oauth_state or state != mailveyra_oauth_state or not verify_state(state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    data = await exchange_code(code)
    email = data["user"]["email"]
    name = data["user"].get("name") or email
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, name=name)
        db.add(user)
    user.name = name
    user.google_access_token = data["tokens"]["access_token"]
    user.google_refresh_token = data["tokens"].get("refresh_token") or user.google_refresh_token
    user.google_token_expires_at = data["expires_at"]
    db.commit()
    db.refresh(user)
    redirect = RedirectResponse("/")
    redirect.set_cookie("mailveyra_user_id", str(user.id), httponly=True, samesite="lax")
    redirect.delete_cookie("mailveyra_oauth_state")
    return redirect


@app.post("/auth/logout")
def logout() -> RedirectResponse:
    redirect = RedirectResponse("/", status_code=303)
    redirect.delete_cookie("mailveyra_user_id")
    return redirect


@app.get("/me", response_model=CurrentUserOut)
def me(db: Annotated[Session, Depends(get_db)], mailveyra_user_id: str | None = Cookie(default=None)):
    user = get_user_from_cookie(db, mailveyra_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return CurrentUserOut(id=user.id, email=user.email, name=user.name, gmail_connected=bool(user.google_access_token))


@app.post("/candidate-profile", response_model=CandidateProfileOut)
def create_candidate_profile(
    payload: CandidateProfileIn,
    db: Annotated[Session, Depends(get_db)],
    mailveyra_user_id: str | None = Cookie(default=None),
):
    user = current_or_default_user(db, mailveyra_user_id)
    profile = CandidateProfile(user_id=user.id, **payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/candidate-profile/me", response_model=CandidateProfileOut)
def get_candidate_profile(db: Annotated[Session, Depends(get_db)], mailveyra_user_id: str | None = Cookie(default=None)):
    user = current_or_default_user(db, mailveyra_user_id)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).order_by(CandidateProfile.id.desc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    return profile


@app.put("/candidate-profile/me", response_model=CandidateProfileOut)
def update_candidate_profile(
    payload: CandidateProfileIn,
    db: Annotated[Session, Depends(get_db)],
    mailveyra_user_id: str | None = Cookie(default=None),
):
    user = current_or_default_user(db, mailveyra_user_id)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).order_by(CandidateProfile.id.desc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@app.post("/profile/resume", response_model=CandidateProfileOut)
def upload_resume(
    db: Annotated[Session, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    mailveyra_user_id: str | None = Cookie(default=None),
):
    user = current_or_default_user(db, mailveyra_user_id)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).order_by(CandidateProfile.id.desc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Create candidate profile before uploading resume")
    saved = save_upload(file, "resume")
    profile.resume_file_path = saved["path"]
    extracted_text = read_text_from_file(saved["path"], saved["content_type"])
    if extracted_text:
        profile.resume_text = extracted_text
    db.commit()
    db.refresh(profile)
    return profile


@app.post("/job-posts", response_model=JobPostOut)
def create_job_post(
    payload: JobPostIn,
    db: Annotated[Session, Depends(get_db)],
    mailveyra_user_id: str | None = Cookie(default=None),
):
    user = current_or_default_user(db, mailveyra_user_id)
    job = JobPost(user_id=user.id, raw_text=payload.raw_text, source_type=payload.source_type)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@app.get("/job-posts/{job_post_id}", response_model=JobPostOut)
def get_job_post(job_post_id: int, db: Annotated[Session, Depends(get_db)]):
    job = db.get(JobPost, job_post_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job post not found")
    return job


@app.put("/job-posts/{job_post_id}", response_model=JobPostOut)
def update_job_post(job_post_id: int, payload: JobPostUpdate, db: Annotated[Session, Depends(get_db)]):
    job = db.get(JobPost, job_post_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job post not found")
    extracted = job.extracted or {}
    if payload.company is not None:
        job.company = payload.company
        extracted["company"] = payload.company
    if payload.role_title is not None:
        job.role_title = payload.role_title
        extracted["role_title"] = payload.role_title
    if payload.recipient_email is not None:
        job.recipient_email = str(payload.recipient_email)
        extracted["recipient_email"] = str(payload.recipient_email)
    if payload.required_skills is not None:
        extracted["required_skills"] = payload.required_skills
    job.extracted = extracted
    db.commit()
    db.refresh(job)
    return job


@app.post("/applications", response_model=ApplicationOut)
def create_application(
    payload: ApplicationIn,
    db: Annotated[Session, Depends(get_db)],
    mailveyra_user_id: str | None = Cookie(default=None),
):
    user = current_or_default_user(db, mailveyra_user_id)
    if not db.get(CandidateProfile, payload.candidate_profile_id):
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    if not db.get(JobPost, payload.job_post_id):
        raise HTTPException(status_code=404, detail="Job post not found")
    application = Application(user_id=user.id, **payload.model_dump())
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@app.get("/applications", response_model=list[ApplicationOut])
def list_applications(db: Annotated[Session, Depends(get_db)], mailveyra_user_id: str | None = Cookie(default=None)):
    user = current_or_default_user(db, mailveyra_user_id)
    return list(db.scalars(select(Application).where(Application.user_id == user.id).order_by(Application.id.desc())))


@app.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(application_id: int, db: Annotated[Session, Depends(get_db)]):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.post("/applications/{application_id}/analyze", response_model=ApplicationOut)
def analyze_application(application_id: int, db: Annotated[Session, Depends(get_db)]):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    job = db.get(JobPost, application.job_post_id)
    candidate = db.get(CandidateProfile, application.candidate_profile_id)
    if not job or not candidate:
        raise HTTPException(status_code=404, detail="Application dependencies not found")

    extracted = get_llm_client().extract_job(job.raw_text)
    match_result = binary_match(extracted.required_skills, candidate.skills)

    job.extracted = extracted.model_dump(mode="json")
    job.company = extracted.company
    job.role_title = extracted.role_title
    job.recipient_email = str(extracted.recipient_email) if extracted.recipient_email else None
    application.match_result = match_result
    application.status = "draft_pending"
    db.commit()
    db.refresh(application)
    return application


@app.post("/applications/{application_id}/draft-email", response_model=EmailDraftOut | DraftWarning)
def draft_email(
    application_id: int,
    db: Annotated[Session, Depends(get_db)],
    confirm_zero_overlap: bool = Query(default=False),
):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    job = db.get(JobPost, application.job_post_id)
    candidate = db.get(CandidateProfile, application.candidate_profile_id)
    if not job or not candidate:
        raise HTTPException(status_code=404, detail="Application dependencies not found")
    if not job.extracted or not application.match_result:
        raise HTTPException(status_code=409, detail="Run analysis before drafting email")

    match_result = MatchResult(**application.match_result)
    if not match_result.matched_skills and not confirm_zero_overlap:
        return DraftWarning(
            message="No required job skills matched the candidate profile. Review the gaps before generating an email.",
            matched_skills=[],
            gap_skills=match_result.gap_skills,
        )

    candidate_out = CandidateProfileOut.model_validate(candidate)
    extracted_job = ExtractedJob(**job.extracted)
    generated = get_llm_client().generate_email(job=extracted_job, candidate=candidate_out, match_result=match_result)
    draft = EmailDraft(
        application_id=application.id,
        recipient_email=str(generated.recipient_email) if generated.recipient_email else job.recipient_email,
        cc=[str(email) for email in generated.cc],
        bcc=[str(email) for email in generated.bcc],
        subject=generated.subject,
        body=generated.body,
        attachments=[{"filename": "resume", "path": candidate.resume_file_path, "content_type": "application/pdf"}]
        if candidate.resume_file_path
        else [],
        claim_evidence_map=generated.claim_evidence_map,
        model_used=generated.model_used,
    )
    application.status = "draft_ready"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@app.get("/applications/{application_id}/email-draft", response_model=EmailDraftOut)
def get_email_draft(application_id: int, db: Annotated[Session, Depends(get_db)]):
    draft = db.scalar(select(EmailDraft).where(EmailDraft.application_id == application_id).order_by(EmailDraft.id.desc()))
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    return draft


@app.put("/email-drafts/{draft_id}", response_model=EmailDraftOut)
def update_email_draft(draft_id: int, payload: EmailDraftUpdate, db: Annotated[Session, Depends(get_db)]):
    draft = db.get(EmailDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    if draft.approved_at:
        raise HTTPException(status_code=409, detail="Approved draft cannot be edited")
    if payload.recipient_email is not None:
        draft.recipient_email = str(payload.recipient_email)
    if payload.cc is not None:
        draft.cc = [str(email) for email in payload.cc]
    if payload.bcc is not None:
        draft.bcc = [str(email) for email in payload.bcc]
    if payload.subject is not None:
        draft.subject = payload.subject
    if payload.body is not None:
        draft.body = payload.body
        draft.user_edited_body = payload.body
    db.commit()
    db.refresh(draft)
    return draft


@app.post("/email-drafts/{draft_id}/approve", response_model=EmailDraftOut)
def approve_email_draft(draft_id: int, db: Annotated[Session, Depends(get_db)]):
    draft = db.get(EmailDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    if not draft.recipient_email:
        raise HTTPException(status_code=409, detail="Recipient email is required before approval")
    if not draft.subject.strip():
        raise HTTPException(status_code=409, detail="Subject is required before approval")
    if not draft.body.strip():
        raise HTTPException(status_code=409, detail="Body is required before approval")
    application = db.get(Application, draft.application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    approved_at = datetime.now(UTC)
    draft.approved_snapshot = {
        "recipient_email": draft.recipient_email,
        "cc": draft.cc or [],
        "bcc": draft.bcc or [],
        "subject": draft.subject,
        "body": draft.body,
        "attachments": draft.attachments or [],
        "claim_evidence_map": draft.claim_evidence_map,
        "application_id": draft.application_id,
        "approved_at": approved_at.isoformat(),
    }
    draft.approved_at = approved_at
    application.status = "approved"
    db.commit()
    db.refresh(draft)
    return draft


@app.post("/email-drafts/{draft_id}/send", response_model=SendLogOut)
async def send_email_draft(
    draft_id: int,
    db: Annotated[Session, Depends(get_db)],
    mailveyra_user_id: str | None = Cookie(default=None),
):
    draft = db.get(EmailDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")
    application = db.get(Application, draft.application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if not draft.approved_snapshot or not draft.approved_at:
        raise HTTPException(status_code=409, detail="Draft must be approved before send")
    existing_success = db.scalar(
        select(EmailSendLog).where(EmailSendLog.email_draft_id == draft.id, EmailSendLog.status == "sent")
    )
    if existing_success:
        raise HTTPException(status_code=409, detail="Draft has already been sent")

    snapshot = draft.approved_snapshot
    idempotency_key = f"email-draft:{draft.id}:approved:{draft.approved_at.isoformat()}"
    user = get_user_from_cookie(db, mailveyra_user_id)
    if not user or not user.google_access_token:
        raise HTTPException(status_code=401, detail="Login with Gmail before sending real email")
    try:
        provider_message_id = await GmailSender().send(
            access_token=await access_token_for_user(user, db),
            to_email=snapshot["recipient_email"],
            cc=snapshot.get("cc") or [],
            bcc=snapshot.get("bcc") or [],
            subject=snapshot["subject"],
            body=snapshot["body"],
            attachments=snapshot.get("attachments") or [],
        )
        status = "sent"
        error_message = None
    except HTTPException as exc:
        provider_message_id = None
        status = "failed"
        error_message = str(exc.detail)
    log = EmailSendLog(
        application_id=application.id,
        email_draft_id=draft.id,
        provider="gmail",
        status=status,
        provider_message_id=provider_message_id,
        error_message=error_message,
        idempotency_key=idempotency_key or str(uuid4()),
    )
    application.status = status
    db.add(log)
    db.commit()
    db.refresh(log)
    if status == "failed":
        raise HTTPException(status_code=502, detail=error_message)
    return log


@app.get("/applications/{application_id}/send-log", response_model=list[SendLogOut])
def get_send_log(application_id: int, db: Annotated[Session, Depends(get_db)]):
    return list(db.scalars(select(EmailSendLog).where(EmailSendLog.application_id == application_id).order_by(EmailSendLog.id)))


@app.post("/chat/attachments")
def chat_attachment(file: Annotated[UploadFile, File()]):
    return save_upload(file, "chat")


@app.post("/chat/messages", response_model=ChatMessageOut)
def chat_message(
    db: Annotated[Session, Depends(get_db)],
    message: Annotated[str, Form()] = "",
    draft_id: Annotated[int | None, Form()] = None,
    confirm_zero_overlap: Annotated[bool, Form()] = False,
    files: Annotated[list[UploadFile] | None, File()] = None,
    mailveyra_user_id: str | None = Cookie(default=None),
):
    user = current_or_default_user(db, mailveyra_user_id)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == user.id).order_by(CandidateProfile.id.desc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Create candidate profile before using chat")

    saved_files = [save_upload(file, "chat") for file in files or []]
    for saved in saved_files:
        if "resume" in saved["filename"].lower():
            profile.resume_file_path = saved["path"]
            resume_text = read_text_from_file(saved["path"], saved["content_type"])
            if resume_text:
                profile.resume_text = resume_text

    llm = get_llm_client()
    candidate_out = CandidateProfileOut.model_validate(profile)

    if draft_id:
        draft = db.get(EmailDraft, draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Email draft not found")
        if draft.approved_at:
            raise HTTPException(status_code=409, detail="Approved draft cannot be revised")
        application = db.get(Application, draft.application_id)
        if not application or not application.match_result:
            raise HTTPException(status_code=409, detail="Draft application is missing match result")
        current = EmailDraftStructured(
            recipient_email=draft.recipient_email,
            cc=draft.cc or [],
            bcc=draft.bcc or [],
            subject=draft.subject,
            body=draft.body,
            claim_evidence_map=draft.claim_evidence_map,
            model_used=draft.model_used,
        )
        revised = llm.revise_email(current, message, candidate_out, MatchResult(**application.match_result))
        draft.recipient_email = str(revised.recipient_email) if revised.recipient_email else draft.recipient_email
        draft.cc = [str(email) for email in revised.cc]
        draft.bcc = [str(email) for email in revised.bcc]
        draft.subject = revised.subject
        draft.body = revised.body
        draft.user_edited_body = revised.body
        draft.claim_evidence_map = revised.claim_evidence_map
        draft.model_used = revised.model_used
        db.commit()
        db.refresh(draft)
        return ChatMessageOut(message="Draft revised.", application=application, draft=draft, model_used=revised.model_used)

    text_parts = [message]
    for saved in saved_files:
        extracted_text = read_text_from_file(saved["path"], saved["content_type"])
        if extracted_text:
            text_parts.append(extracted_text)
    raw_text = "\n\n".join(part for part in text_parts if part.strip())
    try:
        extracted = llm.extract_job(raw_text, saved_files)  # type: ignore[misc]
    except TypeError:
        extracted = llm.extract_job(raw_text)
    job = JobPost(
        user_id=user.id,
        raw_text=raw_text or "Job description provided as attachment",
        source_type="chat",
        extracted=extracted.model_dump(mode="json"),
        company=extracted.company,
        role_title=extracted.role_title,
        recipient_email=str(extracted.recipient_email) if extracted.recipient_email else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    application = Application(user_id=user.id, candidate_profile_id=profile.id, job_post_id=job.id)
    application.match_result = binary_match(extracted.required_skills, profile.skills)
    application.status = "draft_pending"
    db.add(application)
    db.commit()
    db.refresh(application)

    if not application.match_result["matched_skills"] and not confirm_zero_overlap:
        return ChatMessageOut(
            message="No skills matched. Confirm if you still want a weak draft.",
            application=application,
            job=job,
            draft=DraftWarning(
                message="No required job skills matched the candidate profile. Review the gaps before generating an email.",
                matched_skills=[],
                gap_skills=application.match_result["gap_skills"],
            ),
            model_used=getattr(llm, "last_model_used", None),
        )

    generated = llm.generate_email(extracted, candidate_out, MatchResult(**application.match_result))
    draft = EmailDraft(
        application_id=application.id,
        recipient_email=str(generated.recipient_email) if generated.recipient_email else job.recipient_email,
        cc=[str(email) for email in generated.cc],
        bcc=[str(email) for email in generated.bcc],
        subject=generated.subject,
        body=generated.body,
        attachments=[{"filename": "resume", "path": profile.resume_file_path, "content_type": "application/pdf"}]
        if profile.resume_file_path
        else [],
        claim_evidence_map=generated.claim_evidence_map,
        model_used=generated.model_used,
    )
    application.status = "draft_ready"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return ChatMessageOut(
        message="Draft generated.",
        application=application,
        job=job,
        draft=draft,
        model_used=generated.model_used,
    )

