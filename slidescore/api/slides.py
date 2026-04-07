from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from ..errors import SlideScoreAPIError
from ..types import JSONValue

if TYPE_CHECKING:
    from ..client import APIClient


def _get_filename(content_disposition: str) -> str:
    fname = re.findall(
        "filename*?=([^;]+)", content_disposition, flags=re.IGNORECASE
    )
    fname = fname[0].strip().strip('"')
    fname = (
        unicodedata.normalize("NFKD", fname)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    fname = re.sub(r"[^\w\s.\-,;=]", "_", fname).strip()
    return fname


def download_slide(
    client: APIClient,
    study_id: int,
    image_id: int,
    directory: str | Path,
) -> None:
    """Download a slide file to a local directory."""
    response = client.perform_request(
        "DownloadSlide",
        method="GET",
        params={"studyId": study_id, "imageId": image_id},
    )
    fname = _get_filename(response.headers["Content-Disposition"])
    out_path = Path(directory) / fname
    with out_path.open("wb") as outfile:
        for chunk in response.iter_content(chunk_size=8192):
            outfile.write(chunk)


def get_slide_path(client: APIClient, image_id: int) -> str:
    """Get the server-side filesystem path of a slide."""
    response = client.perform_request(
        "GetSlidePath", method="GET", params={"imageId": image_id}
    )
    rjson = client._response_json(response, "GetSlidePath")
    client._require_api_success(rjson, response, "GetSlidePath")
    return rjson["path"]


def update_slide_path(client: APIClient, image_id: int, new_path: str) -> None:
    """Update the server-side path of a slide."""
    response = client.perform_request(
        "UpdateSlidePath",
        method="POST",
        params={"imageId": image_id, "newPath": new_path},
    )
    rjson = client._response_json(response, "UpdateSlidePath")
    client._require_api_success(rjson, response, "UpdateSlidePath")


def update_slide_name(client: APIClient, image_id: int, new_name: str) -> None:
    """Update the display name of a slide."""
    response = client.perform_request(
        "UpdateSlideName",
        method="POST",
        params={"imageId": image_id, "newName": new_name},
    )
    rjson = client._response_json(response, "UpdateSlideName")
    client._require_api_success(rjson, response, "UpdateSlideName")


def update_slide_description(
    client: APIClient, study_id: int, image_id: int, new_description: str
) -> None:
    """Update the description of a slide."""
    response = client.perform_request(
        "SetSlideDescription",
        method="POST",
        params={
            "imageId": image_id,
            "studyId": study_id,
            "description": new_description,
        },
    )
    client._response_json(response, "SetSlideDescription")
    if response.text != "{}":
        raise SlideScoreAPIError(
            "Failed updating slide description: " + response.text,
            status_code=response.status_code,
            server_message=response.text,
            endpoint=client._api_operation_name("SetSlideDescription"),
        )


def add_slide(
    client: APIClient, study_id: int, destination_filename: str
) -> dict[str, JSONValue]:
    """Register a slide file path in a study."""
    response = client.perform_request(
        "AddSlide",
        method="POST",
        params={"studyId": study_id, "path": destination_filename},
    )
    if response.text[:1] == '"':
        raise SlideScoreAPIError(
            "Failed adding slide: " + response.text,
            status_code=response.status_code,
            server_message=response.text,
            endpoint=client._api_operation_name("AddSlide"),
        )
    rjson = client._response_json(response, "AddSlide")
    client._require_api_success(rjson, response, "AddSlide")
    return {"id": rjson["id"], "isOOF": rjson["isOOF"]}


def get_slide_description(client: APIClient, image_id: int) -> str:
    """Get the description of a slide."""
    response = client.perform_request(
        "GetSlideDescription",
        method="GET",
        params={"imageId": image_id},
    )
    rjson = client._response_json(response, "GetSlideDescription")
    client._require_api_success(rjson, response, "GetSlideDescription")
    return rjson["description"]


def is_slide_out_of_focus(client: APIClient, study_id: int, image_id: int) -> bool:
    """Check whether a slide has been flagged as out of focus."""
    response = client.perform_request(
        "IsSlideOutOfFocus",
        method="POST",
        params={"studyId": study_id, "imageId": image_id},
    )
    rjson = client._response_json(response, "IsSlideOutOfFocus")
    client._require_api_success(rjson, response, "IsSlideOutOfFocus")
    return rjson["isOOF"]


def set_slide_tma_map(
    client: APIClient, study_id: int, image_id: int, tma_map_name: str
) -> None:
    """Assign a TMA map to a slide."""
    response = client.perform_request(
        "SetSlideTMAMap",
        method="POST",
        params={
            "studyId": study_id,
            "imageId": image_id,
            "tmaMapName": tma_map_name,
        },
    )
    rjson = client._response_json(response, "SetSlideTMAMap")
    client._require_api_success(rjson, response, "SetSlideTMAMap")


def create_tma_map(client: APIClient, study_id: int, tma_map_filename: str) -> str:
    """Create a TMA map from a file."""
    response = client.perform_request(
        "CreateTMAMap",
        method="POST",
        params={"studyId": study_id, "tmaMapFileName": tma_map_filename},
    )
    rjson = client._response_json(response, "CreateTMAMap")
    client._require_api_success(rjson, response, "CreateTMAMap")
    return rjson["mapName"]
