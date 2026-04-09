from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ..anno2 import encode as anno2_encode
from ..anno2.containers import Heatmap, Points, Polygons
from ..parsers.slidescore_json import read_slidescore_json
from ..types import Anno2ConvertInput, Anno2OptionalId, JSONObject, JSONValue

if TYPE_CHECKING:
    from ..client import APIClient


def upload_ASAP(
    client: APIClient,
    image_id: int,
    user: str,
    questions_map: Mapping[str, str],
    annotation_name: str,
    asap_annotation: str,
) -> bool:
    """Upload an ASAP XML annotation to SlideScore."""
    response = client.perform_request(
        "UploadASAPAnnotations",
        method="POST",
        data={
            "imageId": image_id,
            "questionsMap": "\n".join(
                f"{key};{val}" for key, val in questions_map.items()
            ),
            "user": user,
            "annotationName": annotation_name,
            "asapAnnotation": asap_annotation,
        },
    )
    body = client._response_json(response, "UploadASAPAnnotations")
    client._require_api_success(body, response, "UploadASAPAnnotations")
    return True


def export_ASAP(
    client: APIClient, image_id: int, user: str, question: str
) -> str | None:
    """Export annotations as ASAP XML."""
    response = client.perform_request(
        "ExportASAPAnnotations",
        params={"imageId": image_id, "user": user, "question": question},
    )
    text = response.text
    if text[:1] == "<":
        return text
    body = client._response_json(response, "ExportASAPAnnotations")
    client._require_api_success(body, response, "ExportASAPAnnotations")
    return None


def create_anno2(
    client: APIClient,
    study_id: int,
    case_id: Anno2OptionalId,
    image_id: int,
    tma_core_id: Anno2OptionalId,
    score_id: Anno2OptionalId,
    question: str | None,
    email: str | None,
) -> dict[str, JSONValue]:
    """Create a new Anno2 format record on the server.

    Returns a dict with ``uploadToken`` and ``annoUUID``.
    You must specify one of ``score_id`` or ``question``.
    """
    response = client.perform_request(
        "CreateAnno2",
        method="POST",
        params={
            "studyId": study_id,
            "caseId": case_id,
            "imageId": image_id,
            "tmaCoreId": tma_core_id,
            "scoreId": score_id,
            "question": question,
            "email": email,
        },
    )
    rjson = client._response_json(response, "CreateAnno2")
    client._require_api_success(rjson, response, "CreateAnno2")
    return cast(dict[str, JSONValue], rjson)


def convert_annotation_to_anno2(
    client: APIClient,
    study_id: int,
    case_id: Anno2OptionalId,
    image_id: int,
    tma_core_id: Anno2OptionalId,
    score_id: Anno2OptionalId,
    question: str | None,
    email: str | None,
    metadata: str | JSONObject | None,
) -> str:
    """Convert an existing annotation answer to Anno2 format on the server.

    Returns the ``annoUUID``. You must specify one of ``score_id`` or ``question``.
    """
    response = client.perform_request(
        "ConvertAnnotationToAnno2",
        method="POST",
        params={
            "studyId": study_id,
            "caseId": case_id,
            "imageId": image_id,
            "tmaCoreId": tma_core_id,
            "scoreId": score_id,
            "question": question,
            "email": email,
            "metadata": metadata,
        },
    )
    rjson = client._response_json(response, "ConvertAnnotationToAnno2")
    client._require_api_success(rjson, response, "ConvertAnnotationToAnno2")
    return rjson["annoUUID"]


def convert_to_anno2(
    client: APIClient,
    items: Anno2ConvertInput,
    metadata: JSONValue | None,
    output_path: str | Path,
) -> None:
    """Locally encode a SlideScore annotation object to Anno2 ZIP format.

    Accepts pre-loaded ``Points``, ``Polygons``, or ``Heatmap`` objects, or a
    raw list of SlideScore JSON dicts (brush/polygon/heatmap entries).

    .. note::
        This is a thin wrapper around :func:`slidescore.anno2.encode`.
        The *client* parameter is unused -- encoding is purely local.
    """
    items_encoder: Points | Polygons | Heatmap
    if isinstance(items, (Points, Polygons, Heatmap)):
        items_encoder = items
    else:
        items_encoder = read_slidescore_json(items)

    anno2_encode(items_encoder, output_path, metadata=metadata)
