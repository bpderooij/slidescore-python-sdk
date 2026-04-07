from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SlideScoreSession, SlideScoreSessionEvent

if TYPE_CHECKING:
    from ..client import APIClient


def get_sessions(
    client: APIClient,
    study_id: int,
    email: str | None = None,
    image_id: int | None = None,
) -> list[SlideScoreSession]:
    """Get tracking sessions for a study."""
    response = client.perform_request(
        "Sessions",
        params={"studyId": study_id, "imageId": image_id, "email": email},
    )
    rjson = client._response_json(response, "Sessions")
    client._require_api_success(rjson, response, "Sessions")
    return [SlideScoreSession.from_api_response(r) for r in rjson["sessions"]]


def get_session_events(
    client: APIClient, study_id: int, session_id: int
) -> list[SlideScoreSessionEvent]:
    """Get events for a tracking session."""
    response = client.perform_request(
        "SessionEvents",
        params={"studyId": study_id, "sessionId": session_id},
    )
    rjson = client._response_json(response, "SessionEvents")
    client._require_api_success(rjson, response, "SessionEvents")
    return [SlideScoreSessionEvent.from_tsv_line(r) for r in rjson["events"]]


def generate_login_link(client: APIClient, username: str, expires_on: str) -> str:
    """Generate a one-time login link for a user."""
    response = client.perform_request(
        "GenerateLoginLink",
        method="POST",
        params={"username": username, "expiresOn": expires_on},
    )
    rjson = client._response_json(response, "GenerateLoginLink")
    client._require_api_success(rjson, response, "GenerateLoginLink")
    return rjson["link"]


def generate_student_account(
    client: APIClient, username: str, email: str, class_id: int
) -> str:
    """Create a student account and return the generated password."""
    response = client.perform_request(
        "GenerateStudentAccount",
        method="POST",
        params={"username": username, "email": email, "classId": class_id},
    )
    rjson = client._response_json(response, "GenerateStudentAccount")
    client._require_api_success(rjson, response, "GenerateStudentAccount")
    return rjson["password"]
