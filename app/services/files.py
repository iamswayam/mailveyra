import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import settings


def save_upload(file: UploadFile, prefix: str) -> dict:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload").name
    stored_name = f"{prefix}-{uuid4()}-{safe_name}"
    path = upload_dir / stored_name
    with path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {
        "filename": safe_name,
        "path": str(path),
        "content_type": file.content_type or "application/octet-stream",
    }


def read_text_from_file(path: str, content_type: str | None = None) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".pdf" or content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if suffix in {".txt", ".md", ".csv"} or (content_type or "").startswith("text/"):
        return file_path.read_text(encoding="utf-8", errors="ignore")
    return ""

