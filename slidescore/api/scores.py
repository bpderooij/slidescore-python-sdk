from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..models import SlideScoreResult, _encode_upload_results_payload
from ..types import JSONValue

if TYPE_CHECKING:
    from ..client import APIClient


def get_results(
    client: APIClient,
    study_id: int,
    question: str | None = None,
    email: str | None = None,
    image_id: int | None = None,
    case_id: int | None = None,
) -> list[SlideScoreResult]:
    """Download all answers for a study, with optional filters."""
    response = client.perform_request(
        "Scores",
        params={
            "studyId": study_id,
            "question": question,
            "email": email,
            "imageId": image_id,
            "caseId": case_id,
        },
    )
    rjson = client._response_json(response, "Scores")
    return [SlideScoreResult.from_api_response(r) for r in rjson]


def upload_results(
    client: APIClient, study_id: int, results: Sequence[SlideScoreResult]
) -> bool:
    """POST /Api/UploadResults with a prefixed header line."""
    payload = _encode_upload_results_payload(results)
    response = client.perform_request(
        "UploadResults",
        method="POST",
        data={"studyId": study_id, "results": payload},
    )
    body = client._response_json(response, "UploadResults")
    client._require_api_success(body, response, "UploadResults")
    return True


def add_question(client: APIClient, study_id: int, question_spec: str) -> JSONValue:
    """Add a scoring question to a study."""
    response = client.perform_request(
        "AddQuestion",
        method="POST",
        params={"studyId": study_id, "questionSpec": question_spec},
    )
    rjson = client._response_json(response, "AddQuestion")
    client._require_api_success(rjson, response, "AddQuestion")
    return rjson["id"]


def update_question(
    client: APIClient,
    study_id: int,
    score_id: int,
    order: int,
    question_spec: str,
) -> JSONValue:
    """Update an existing scoring question."""
    response = client.perform_request(
        "UpdateQuestion",
        method="POST",
        params={
            "studyId": study_id,
            "scoreId": score_id,
            "order": order,
            "questionSpec": question_spec,
        },
    )
    rjson = client._response_json(response, "UpdateQuestion")
    client._require_api_success(rjson, response, "UpdateQuestion")
    return rjson["id"]


def remove_question(client: APIClient, study_id: int, score_id: int) -> bool:
    """Remove a scoring question from a study."""
    response = client.perform_request(
        "RemoveQuestion",
        method="POST",
        params={"studyId": study_id, "scoreId": score_id},
    )
    rjson = client._response_json(response, "RemoveQuestion")
    client._require_api_success(rjson, response, "RemoveQuestion")
    return True
