from fastapi.testclient import TestClient

from app.main import app


def test_zero_skill_overlap_blocks_draft_generation():
    with TestClient(app) as client:
        profile = client.post(
            "/candidate-profile",
            json={"name": "Asha Dev", "skills": ["python", "django"]},
        ).json()
        job = client.post(
            "/job-posts",
            json={"raw_text": "Company: Acme\nRole: Backend Engineer\nWe need Java and Spring Boot."},
        ).json()
        application = client.post(
            "/applications",
            json={"candidate_profile_id": profile["id"], "job_post_id": job["id"]},
        ).json()

        analyzed = client.post(f"/applications/{application['id']}/analyze").json()
        assert analyzed["match_result"]["matched_skills"] == []

        draft_response = client.post(f"/applications/{application['id']}/draft-email")

        assert draft_response.status_code == 200
        assert draft_response.json()["status"] == "blocked_zero_skill_overlap"
        assert client.get(f"/applications/{application['id']}/email-draft").status_code == 404


def test_approve_then_mock_send_blocks_duplicate_send():
    with TestClient(app) as client:
        profile = client.post(
            "/candidate-profile",
            json={"name": "Asha Dev", "skills": ["python", "django", "fastapi"]},
        ).json()
        job = client.post(
            "/job-posts",
            json={
                "raw_text": "Company: Acme\nRole: Backend Engineer\nContact jobs@example.com\nWe need Python and FastAPI."
            },
        ).json()
        application = client.post(
            "/applications",
            json={"candidate_profile_id": profile["id"], "job_post_id": job["id"]},
        ).json()
        client.post(f"/applications/{application['id']}/analyze")
        draft = client.post(f"/applications/{application['id']}/draft-email").json()

        pre_approval_send = client.post(f"/email-drafts/{draft['id']}/send")
        assert pre_approval_send.status_code == 409

        approved = client.post(f"/email-drafts/{draft['id']}/approve").json()
        assert approved["approved_snapshot"]["recipient_email"] == "jobs@example.com"

        sent = client.post(f"/email-drafts/{draft['id']}/send")
        assert sent.status_code == 200
        assert sent.json()["status"] == "sent"

        duplicate = client.post(f"/email-drafts/{draft['id']}/send")
        assert duplicate.status_code == 409

