from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import SlideScoreAPIError
from ..types import JSONValue

if TYPE_CHECKING:
    from ..client import APIClient


def get_studies(client: APIClient) -> JSONValue:
    """Get list of studies this token can access."""
    response = client.perform_request("Studies")
    return client._response_json(response, "Studies")


def get_config(client: APIClient, study_id: int) -> JSONValue:
    """Get the configuration of a particular study."""
    response = client.perform_request("GetConfig", params={"studyId": study_id})
    rjson = client._response_json(response, "GetConfig")
    client._require_api_success(rjson, response, "GetConfig")
    return rjson["config"]


def get_config_files(client: APIClient, study_id: int) -> JSONValue:
    """Get the configuration files of a particular study."""
    response = client.perform_request("GetConfigFiles", params={"studyId": study_id})
    rjson = client._response_json(response, "GetConfigFiles")
    client._require_api_success(rjson, response, "GetConfigFiles")
    return rjson


def get_cases(client: APIClient, study_id: int) -> JSONValue:
    """Get all case names and IDs for a study."""
    response = client.perform_request("Cases", params={"studyId": study_id})
    return client._response_json(response, "Cases")


def get_case_description(client: APIClient, case_id: int) -> str:
    """Get the description of a case."""
    response = client.perform_request(
        "GetCaseDescription", method="GET", params={"caseId": case_id}
    )
    rjson = client._response_json(response, "GetCaseDescription")
    client._require_api_success(rjson, response, "GetCaseDescription")
    return rjson["description"]


def get_images(client: APIClient, study_id: int) -> JSONValue:
    """Get slide metadata for all slides in the study."""
    response = client.perform_request("Images", params={"studyId": study_id})
    return client._response_json(response, "Images")


def reimport(client: APIClient, study_name: str) -> dict[str, JSONValue]:
    """Reimport a study by name."""
    response = client.perform_request(
        "Reimport", method="POST", params={"studyName": study_name}
    )
    if response.text[:1] == '"':
        raise SlideScoreAPIError(
            "Failed reimporting: " + response.text,
            status_code=response.status_code,
            server_message=response.text,
            endpoint=client._api_operation_name("Reimport"),
        )
    rjson = client._response_json(response, "Reimport")
    client._require_api_success(rjson, response, "Reimport")
    return {"id": rjson["id"], "log": rjson["log"]}
