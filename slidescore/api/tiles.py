from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import requests

from ..types import JSONValue

if TYPE_CHECKING:
    from ..client import APIClient


def get_image_server_url(client: APIClient, image_id: int) -> tuple[str, str]:
    """Return ``(tile_root_url, cookie_part)`` for the image tile server."""
    response = client.perform_request("GetTileServer", params={"imageId": image_id})
    data = client._response_json(response, "GetTileServer")
    origin = client.end_point.removesuffix("/Api/")
    tile_root = f"{origin}/i/{image_id}/{data['urlPart']}/i_files"
    return tile_root, data["cookiePart"]


def get_raw_tile(
    client: APIClient,
    study_id: int,
    image_id: int,
    level: int,
    x: int,
    y: int,
    width: int,
    height: int,
    jpeg_quality: int,
) -> requests.Response:
    """Get a JPEG tile from the slide at the given level and coordinates."""
    return client.perform_request(
        "GetRawTile",
        method="GET",
        params={
            "studyId": study_id,
            "imageId": image_id,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "level": level,
            "jpegQuality": jpeg_quality,
        },
    )


def get_screenshot_whole(
    client: APIClient,
    image_id: int,
    user: str,
    question: str,
    output_file: str | Path,
) -> None:
    """Download a whole-slide screenshot with annotations to a file."""
    response = client.perform_request(
        "GetScreenshot",
        method="GET",
        params={
            "imageId": image_id,
            "withAnnotationForUser": user,
            "question": question,
            "level": 11,
        },
    )
    out = Path(output_file)
    with out.open("wb") as outfile:
        for chunk in response.iter_content(chunk_size=8192):
            outfile.write(chunk)
