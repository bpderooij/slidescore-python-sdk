from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from .types import JSONObject, SlideScoreAnnotationJson, SlideScorePointCoordJson

_ROW_TAB = "\t"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _to_upload_cell(value: object) -> str:
    return "" if value is None else str(value)


# SlideScore discards the first line of ``results`` (treated as a TSV header). The
# API docs show ``"#header\\n" + row`` as a minimal placeholder; using a real header
# line (e.g. from Scores export) is also fine. See UploadResults in the SlideScore API docs.
_UPLOAD_RESULTS_DISCARDED_HEADER_LINE = "#header"


def _encode_upload_results_payload(results: Sequence[SlideScoreResult]) -> str:
    """Build the multiline ``results`` form field for ``POST /Api/UploadResults``.

    Prepends a placeholder header line so the server does not treat the first
    real scoring row as the header (which would drop that row).
    """
    rows = "\n".join(row.as_slidescore_results_row() for row in results)
    if not rows:
        return _UPLOAD_RESULTS_DISCARDED_HEADER_LINE
    return f"{_UPLOAD_RESULTS_DISCARDED_HEADER_LINE}\n{rows}"


@dataclass(init=False)
class SlideScoreResult:
    """One scoring row from SlideScore (answers / annotations).

    Construct with keyword arguments, or use :meth:`from_api_response` for JSON
    objects returned by the Scores API (camelCase keys: ``imageID``, ``imageName``, …).

    Before :meth:`as_slidescore_results_row`, :meth:`validate_for_upload` checks that
    ``image_id``, ``image_name``, ``user``, and ``question`` are set the way
    ``POST /Api/UploadResults`` expects (non-empty strings and a positive image id).
    ``answer`` may be empty or omitted; TMA fields must be complete if any is set.

    **Parsed ``answer`` (optional):** SlideScore stores shape answers as a single
    JSON string in ``answer`` -- either AnnoShapes-style dicts (each has a
    ``type`` key) or a flat list of ``{x,y}`` objects for AnnoPoints. When
    ``parse_answer_json`` is true, that string is copied into :attr:`annotations`
    or :attr:`points` so callers can branch without re-parsing. Upload and TSV
    serialization use only the raw ``answer`` string; these lists are not sent
    to the API.     They are not used on the SlideForge inference path (which uses dlup
    ``SlideAnnotations`` instead).
    """

    id: int
    image_id: int
    image_name: str | None
    case_name: str | None
    user: str | None
    tma_row: int | None
    tma_col: int | None
    tma_sample_id: str | None
    question: str | None
    answer: str | None
    annotations: list[SlideScoreAnnotationJson] | None
    points: list[SlideScorePointCoordJson] | None

    def __init__(
        self,
        *,
        id: int = 0,
        image_id: int = 0,
        image_name: str | None = None,
        case_name: str | None = None,
        user: str | None = None,
        tma_row: int | None = None,
        tma_col: int | None = None,
        tma_sample_id: str | None = None,
        question: str | None = None,
        answer: str | None = None,
        annotations: list[SlideScoreAnnotationJson] | None = None,
        points: list[SlideScorePointCoordJson] | None = None,
        parse_answer_json: bool = True,
    ) -> None:
        self.id = id
        self.image_id = image_id
        self.image_name = image_name
        self.case_name = case_name
        self.user = user
        self.tma_row = tma_row
        self.tma_col = tma_col
        self.tma_sample_id = tma_sample_id
        self.question = question
        self.answer = answer
        self.annotations = annotations
        self.points = points
        if parse_answer_json and annotations is None and points is None:
            self._try_parse_answer_json()

    def _try_parse_answer_json(self) -> None:
        ans = self.answer
        if ans and len(ans) >= 2 and ans.startswith("[{"):
            try:
                loaded = json.loads(ans)
                if not isinstance(loaded, list) or not loaded:
                    return
                first = loaded[0]
                if not isinstance(first, Mapping):
                    return
                annos = cast(list[JSONObject], loaded)
                if first.get("type") is not None:
                    self.annotations = annos
                else:
                    self.points = annos
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"SlideScoreResult answer looks like JSON (starts with '[{{') but is not valid "
                    f"JSON (result id={self.id}, image_id={self.image_id})"
                ) from exc

    @classmethod
    def from_api_response(
        cls, data: Mapping[str, object] | None
    ) -> SlideScoreResult:
        """Build from a JSON object returned by the Scores API."""
        if data is None:
            return cls()
        raw_image_id = data.get("imageID")
        image_id = int(raw_image_id) if raw_image_id is not None else 0
        tma_sample_id: str | None
        if "tmaSampleID" in data:
            tma_sample_id = _optional_str(data.get("tmaSampleID"))
        else:
            tma_sample_id = None
        return cls(
            id=int(data.get("id", 0)),
            image_id=image_id,
            image_name=_optional_str(data.get("imageName")),
            case_name=_optional_str(data.get("caseName")),
            user=_optional_str(data.get("user")),
            tma_row=int(data["tmaRow"]) if data.get("tmaRow") is not None else None,
            tma_col=int(data["tmaCol"]) if data.get("tmaCol") is not None else None,
            tma_sample_id=tma_sample_id,
            question=_optional_str(data.get("question")),
            answer=_optional_str(data.get("answer")),
        )

    def validate_for_upload(self) -> None:
        """Ensure fields required by ``UploadResults`` are present and consistent.

        SlideScore rejects rows with a missing image, question label, scorer, or
        slide name. TMA columns must appear as a full triple (row, column, sample
        id) when any TMA value is set.

        Raises
        ------
        ValueError
            If the row cannot be uploaded as-is.
        """
        msgs: list[str] = []
        if self.image_id <= 0:
            msgs.append("image_id must be a positive integer")
        if self.question is None or not str(self.question).strip():
            msgs.append("question must be a non-empty string")
        if self.user is None or not str(self.user).strip():
            msgs.append("user must be a non-empty string (scorer email)")
        if self.image_name is None or not str(self.image_name).strip():
            msgs.append("image_name must be a non-empty string")
        tma_any = (
            self.tma_row is not None
            or self.tma_col is not None
            or self.tma_sample_id is not None
        )
        if tma_any:
            if self.tma_row is None:
                msgs.append("tma_row is required when any TMA field is set")
            if self.tma_col is None:
                msgs.append("tma_col is required when any TMA field is set")
        if msgs:
            raise ValueError("; ".join(msgs))

    def as_slidescore_results_row(self) -> str:
        """
        One tab-separated line for ``POST /Api/UploadResults`` (Swagger).

        Calls :meth:`validate_for_upload` first. ``answer`` and TMA sample id
        may be empty; other required columns must be populated.
        """
        self.validate_for_upload()
        segments: list[str] = []

        case = self.case_name
        if case is not None and str(case).strip():
            segments.append(str(case).strip())

        segments.extend(
            [
                _to_upload_cell(self.image_id),
                _to_upload_cell(self.image_name),
                _to_upload_cell(self.user),
            ]
        )
        if self.tma_row is not None:
            segments.extend(
                [
                    _to_upload_cell(self.tma_row),
                    _to_upload_cell(self.tma_col),
                    _to_upload_cell(self.tma_sample_id),
                ]
            )
        segments.extend(
            [_to_upload_cell(self.question), _to_upload_cell(self.answer)]
        )
        return "\t".join(segments)

    def toRow(self) -> str:
        """Backward-compatible alias for :meth:`as_slidescore_results_row`."""
        return self.as_slidescore_results_row()

    def __repr__(self) -> str:
        alen = len(self.answer) if self.answer is not None else 0
        return (
            f"SlideScoreResult(case_name={self.case_name!r}, "
            f"image_id={self.image_id!r}, "
            f"image_name={self.image_name!r}, "
            f"user={self.user!r}, "
            f"tma_row={self.tma_row!r}, "
            f"tma_col={self.tma_col!r}, "
            f"tma_sample_id={self.tma_sample_id!r}, "
            f"question={self.question!r}, "
            f"answer_length={alen})"
        )


@dataclass(init=False)
class SlideScoreSession:
    """One tracking session from the Sessions API."""

    id: int
    image_id: int
    email: str
    length: int
    study_id: int | None
    created_on: datetime.datetime | None

    def __init__(
        self,
        *,
        id: int = 0,
        image_id: int = 0,
        email: str | None = None,
        length: int = 0,
        study_id: int | None = None,
        created_on: datetime.datetime | None = None,
    ) -> None:
        self.id = id
        self.image_id = image_id
        self.email = "" if email is None else str(email)
        self.length = length
        self.study_id = study_id
        self.created_on = created_on

    @classmethod
    def from_api_response(
        cls, data: Mapping[str, object] | None
    ) -> SlideScoreSession:
        """Build from a JSON object returned by the Sessions API."""
        if data is None:
            return cls()
        raw_study = data.get("studyID")
        study_id = int(raw_study) if raw_study is not None else None
        created_raw = data.get("createdOn")
        created_on = None
        if created_raw is not None:
            created_on = datetime.datetime.strptime(
                str(created_raw)[:19], "%Y-%m-%dT%H:%M:%S"
            )
        return cls(
            id=int(data["id"]),
            image_id=int(data["imageID"]),
            email=(_optional_str(data.get("email")) or "").strip(),
            length=int(data["length"]),
            study_id=study_id,
            created_on=created_on,
        )


@dataclass(init=False)
class SlideScoreSessionEvent:
    """One tracking session event (tab-separated line from SessionEvents)."""

    timestamp: int
    x: int
    y: int
    width: int
    height: int
    cursor_x: int
    cursor_y: int

    def __init__(
        self,
        *,
        timestamp: int = 0,
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
        cursor_x: int = 0,
        cursor_y: int = 0,
    ) -> None:
        self.timestamp = timestamp
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.cursor_x = cursor_x
        self.cursor_y = cursor_y

    @classmethod
    def from_tsv_line(cls, line: str) -> SlideScoreSessionEvent:
        """Parse a single tab-separated event line from the SessionEvents API."""
        terms = line.split("\t")
        if len(terms) < 7:
            raise ValueError(
                "Expected at least 7 tab-separated fields in session event, "
                f"got {len(terms)}"
            )
        return cls(
            timestamp=int(terms[0]),
            x=int(terms[1]),
            y=int(terms[2]),
            width=int(terms[3]),
            height=int(terms[4]),
            cursor_x=int(terms[5]),
            cursor_y=int(terms[6]),
        )
