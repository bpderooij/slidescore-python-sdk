from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tusclient import client as tus_module

from ..errors import SlideScoreAPIError
from ..types import JSONValue

if TYPE_CHECKING:
    from ..client import APIClient


def request_upload(
    client: APIClient,
    destination_folder: str,
    destination_filename: str,
    study_id: int | None,
) -> str:
    """Request an upload token for a TUS upload."""
    response = client.perform_request(
        "RequestUpload",
        method="POST",
        params={
            "filename": destination_filename,
            "folder": destination_folder,
            "studyId": study_id,
        },
    )
    if response.text[:1] == '"':
        raise SlideScoreAPIError(
            f"Failed requesting upload: {response.text}",
            status_code=response.status_code,
            server_message=response.text,
            endpoint=client._api_operation_name("RequestUpload"),
        )
    body = client._response_json(response, "RequestUpload")
    return str(body["token"])


def finish_upload(client: APIClient, upload_token: str, upload_url: str) -> None:
    """Notify SlideScore that a TUS upload has completed."""
    file_id = upload_url.rstrip("/").rsplit("/", 1)[-1]
    response = client.perform_request(
        "FinishUpload",
        method="POST",
        params={"id": file_id, "token": upload_token},
    )
    if response.text != '"OK"':
        raise SlideScoreAPIError(
            f"Failed finishing upload: {response.text}",
            status_code=response.status_code,
            server_message=response.text,
            endpoint=client._api_operation_name("FinishUpload"),
        )


def upload_using_token(
    client: APIClient, source_filename: str, upload_token: str
) -> None:
    """Upload a file via TUS using a pre-obtained upload token."""
    tus_base = client.end_point.replace("/Api/", "/files/")
    tus_client = tus_module.TusClient(tus_base)
    uploader = tus_client.uploader(
        source_filename,
        chunk_size=10 * 1000 * 1000,
        metadata={"uploadtoken": upload_token, "apitoken": client.api_token},
    )
    uploader.upload()
    finish_upload(client, upload_token, uploader.url)


def upload_file(
    client: APIClient,
    source_filename: str | Path,
    destination_path: str,
    destination_filename: str | None = None,
) -> None:
    """Upload a local file to SlideScore storage."""
    source_path = Path(source_filename)
    if destination_filename is None:
        destination_filename = source_path.name
    upload_token = request_upload(client, destination_path, destination_filename, None)
    upload_using_token(client, str(source_path), upload_token)


def upload_attachment(
    client: APIClient,
    study_id: int | None,
    module_id: int | None,
    filename: str | Path,
    label: str,
) -> str:
    """Upload a file as an attachment and return an HTML snippet linking to it."""
    filename_only = Path(filename).name
    response = client.perform_request(
        "RequestUploadAttachment",
        method="POST",
        params={
            "studyId": study_id,
            "moduleId": module_id,
            "filename": filename_only,
        },
    )
    body = client._response_json(response, "RequestUploadAttachment")
    client._require_api_success(body, response, "RequestUploadAttachment")
    base_url = client.end_point.removesuffix("/Api/")
    temp_api_token = body["token"]
    folder = body["folder"]
    new_filename = body["filename"]
    att_id = body["attId"]

    # Import here to avoid circular dependency — client.py imports from api/
    from ..client import APIClient as _APIClient

    attachment_client = _APIClient(base_url, temp_api_token)
    upload_file(attachment_client, str(Path(filename)), folder, new_filename)
    short_guid = new_filename.split("-")[0]
    return (
        f'<div><a href="{base_url}/a/{att_id}/{short_guid}/{filename_only}" '
        'target="_blank" rel="noopener" class="jsSquireAttachment jsSquireLink" '
        'style="display: inline-block;">'
        '<span class="glyphicon glyphicon glyphicon-paperclip"> </span>&nbsp;'
        f"{label}&nbsp;</a><br></div>"
    )
