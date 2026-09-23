from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class SendResult:
    provider: str
    status: str
    provider_message_id: str


class MockEmailSender:
    provider = "mock"

    def send(self, recipient_email: str, subject: str, body: str) -> SendResult:
        print("MOCK EMAIL SEND")
        print(f"TO: {recipient_email}")
        print(f"SUBJECT: {subject}")
        print(body)
        return SendResult(provider=self.provider, status="sent", provider_message_id=f"mock-{uuid4()}")

