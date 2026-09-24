import base64
from email.message import EmailMessage
from pathlib import Path

import httpx
from fastapi import HTTPException


class GmailSender:
    async def send(
        self,
        access_token: str,
        to_email: str,
        cc: list[str],
        bcc: list[str],
        subject: str,
        body: str,
        attachments: list[dict],
    ) -> str:
        message = EmailMessage()
        message["To"] = to_email
        if cc:
            message["Cc"] = ", ".join(cc)
        if bcc:
            message["Bcc"] = ", ".join(bcc)
        message["Subject"] = subject
        message.set_content(body)

        for attachment in attachments:
            path = Path(attachment["path"])
            if not path.exists():
                raise HTTPException(status_code=409, detail=f"Attachment not found: {attachment.get('filename')}")
            maintype, _, subtype = (attachment.get("content_type") or "application/octet-stream").partition("/")
            message.add_attachment(
                path.read_bytes(),
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.get("filename") or path.name,
            )

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=response.json())
        return response.json().get("id", "")

