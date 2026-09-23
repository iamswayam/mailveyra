from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Application, CandidateProfile, EmailDraft, EmailSendLog, JobPost, User
from app.schemas import (
    ApplicationIn,
    ApplicationOut,
    CandidateProfileIn,
    CandidateProfileOut,
    DraftWarning,
    EmailDraftOut,
    EmailDraftUpdate,
    ExtractedJob,
    JobPostIn,
    JobPostOut,
    MatchResult,
    SendLogOut,
)
from app.services.email_sender import MockEmailSender
from app.services.llm import get_llm_client
from app.services.matching import binary_match

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MailVeyra")
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse("app/static/index.html")


def ensure_default_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.id == 1))
    if user:
        return user
    user = User(id=1, email="local@example.com", name="Local User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/candidate-profile", response_model=CandidateProfileOut)
def create_candidate_profile(payload: CandidateProfileIn, db: Annotated[Session, Depends(get_db)]):
    user = ensure_default_user(db)
    profile = CandidateProfile(user_id=user.id, **payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/candidate-profile/me", response_model=CandidateProfileOut)
def get_candidate_profile(db: Annotated[Session, Depends(get_db)]):
    ensure_default_user(db)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == 1).order_by(CandidateProfile.id.desc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    return profile


@app.put("/candidate-profile/me", response_model=CandidateProfileOut)
def update_candidate_profile(payload: CandidateProfileIn, db: Annotated[Session, Depends(get_db)]):
    ensure_default_user(db)
    profile = db.scalar(select(CandidateProfile).where(CandidateProfile.user_id == 1).order_by(CandidateProfile.id.desc()))
    if not profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


@app.post("/job-posts", response_model=JobPostOut)
def create_job_post(payload: JobPostIn, db: Annotated[Session, Depends(get_db)]):
    user = ensure_default_user(db)
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


@app.post("/applications", response_model=ApplicationOut)
def create_application(payload: ApplicationIn, db: Annotated[Session, Depends(get_db)]):
    user = ensure_default_user(db)
    if not db.get(CandidateProfile, payload.candidate_profile_id):
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    if not db.get(JobPost, payload.job_post_id):
        raise HTTPException(status_code=404, detail="Job post not found")
    application = Application(user_id=user.id, **payload.model_dump())
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


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
        subject=generated.subject,
        body=generated.body,
        claim_evidence_map=generated.claim_evidence_map,
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
    application = db.get(Application, draft.application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    approved_at = datetime.now(UTC)
    draft.approved_snapshot = {
        "recipient_email": draft.recipient_email,
        "subject": draft.subject,
        "body": draft.body,
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
def send_email_draft(draft_id: int, db: Annotated[Session, Depends(get_db)]):
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
    result = MockEmailSender().send(
        recipient_email=snapshot["recipient_email"],
        subject=snapshot["subject"],
        body=snapshot["body"],
    )
    log = EmailSendLog(
        application_id=application.id,
        email_draft_id=draft.id,
        provider=result.provider,
        status=result.status,
        provider_message_id=result.provider_message_id,
        idempotency_key=idempotency_key or str(uuid4()),
    )
    application.status = "sent"
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@app.get("/applications/{application_id}/send-log", response_model=list[SendLogOut])
def get_send_log(application_id: int, db: Annotated[Session, Depends(get_db)]):
    return list(db.scalars(select(EmailSendLog).where(EmailSendLog.application_id == application_id).order_by(EmailSendLog.id)))

