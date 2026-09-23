from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class CandidateProfileIn(BaseModel):
    name: str
    headline: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    resume_text: str | None = None
    resume_file_path: str | None = None


class CandidateProfileOut(CandidateProfileIn):
    id: int
    user_id: int

    model_config = {"from_attributes": True}


class JobPostIn(BaseModel):
    raw_text: str
    source_type: str = "text"


class ExtractedJob(BaseModel):
    company: str | None = None
    role_title: str | None = None
    recipient_email: EmailStr | None = None
    required_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class JobPostOut(BaseModel):
    id: int
    source_type: str
    raw_text: str
    extracted: dict[str, Any] | None
    company: str | None
    role_title: str | None
    recipient_email: str | None

    model_config = {"from_attributes": True}


class ApplicationIn(BaseModel):
    candidate_profile_id: int
    job_post_id: int


class MatchResult(BaseModel):
    matched_skills: list[str]
    gap_skills: list[str]


class ApplicationOut(BaseModel):
    id: int
    candidate_profile_id: int
    job_post_id: int
    match_result: dict[str, Any] | None
    status: str

    model_config = {"from_attributes": True}


class EmailDraftStructured(BaseModel):
    recipient_email: EmailStr | None = None
    subject: str
    body: str
    claim_evidence_map: dict[str, str] = Field(default_factory=dict)


class DraftWarning(BaseModel):
    status: str = "blocked_zero_skill_overlap"
    message: str
    matched_skills: list[str]
    gap_skills: list[str]


class EmailDraftOut(BaseModel):
    id: int
    application_id: int
    recipient_email: str | None
    subject: str
    body: str
    claim_evidence_map: dict[str, Any]
    user_edited_body: str | None
    approved_snapshot: dict[str, Any] | None
    approved_at: datetime | None

    model_config = {"from_attributes": True}


class EmailDraftUpdate(BaseModel):
    recipient_email: EmailStr | None = None
    subject: str | None = None
    body: str | None = None


class SendLogOut(BaseModel):
    id: int
    application_id: int
    email_draft_id: int
    provider: str
    status: str
    provider_message_id: str | None
    error_message: str | None
    idempotency_key: str

    model_config = {"from_attributes": True}

