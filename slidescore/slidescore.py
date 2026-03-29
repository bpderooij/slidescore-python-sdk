from __future__ import annotations

import datetime
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import requests
from tusclient import client

from .lib.AnnoClasses import Heatmap, Points, Polygons
from .lib.Encoder import Encoder
from .lib.utils import read_slidescore_json

# JSON values as returned by :meth:`requests.Response.json` / :func:`json.loads`.
type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]

# Typed names for ``answer`` JSON decoded into :attr:`SlideScoreResult.annotations` /
# :attr:`SlideScoreResult.points` (same structure, different semantics).
type SlideScoreAnnotationJson = JSONObject
type SlideScorePointCoordJson = JSONObject

# Query/form parameter values (omitted when ``None``).
type APIParamValue = str | int | float | bool | None

# Optional identifiers passed through to SlideScore anno conversion endpoints.
type Anno2OptionalId = int | str | None

type Anno2ConvertInput = Points | Polygons | Heatmap | list[JSONObject]


class SlideScoreAPIError(Exception):
    """Structured error from the SlideScore HTTP API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        server_message: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.server_message = server_message
        self.endpoint = endpoint


SlideScoreErrorException = SlideScoreAPIError  # deprecated compatibility alias

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
    JSON string in ``answer``—either AnnoShapes-style dicts (each has a
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


class APIClient:
    """SlideScore REST client. Parameter shapes follow the public Swagger spec."""

    def __init__(
        self,
        server: str,
        api_token: str,
        disable_cert_checking: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        server
            Origin with optional trailing slash (e.g. ``https://host.example``).
        api_token
            Bearer token from a site administrator.
        disable_cert_checking
            Disable TLS verification (not recommended).
        """
        base = str(server).rstrip("/")
        self.end_point = f"{base}/Api/"
        self.api_token = api_token
        self.disable_cert_checking = disable_cert_checking

    @staticmethod
    def _api_operation_name(path: str) -> str:
        return path.split("?", 1)[0]

    @staticmethod
    def _api_params(
        mapping: Mapping[str, APIParamValue] | None,
    ) -> dict[str, APIParamValue] | None:
        if not mapping:
            return None
        filtered = {k: v for k, v in mapping.items() if v is not None}
        return filtered or None

    def _response_json(self, response: requests.Response, path: str) -> JSONValue:
        operation = self._api_operation_name(path)
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise SlideScoreAPIError(
                f"Invalid JSON from SlideScore API {operation!r}",
                status_code=response.status_code,
                server_message=response.text,
                endpoint=operation,
            ) from exc

    def _require_api_success(
        self,
        body: object,
        response: requests.Response,
        path: str,
        *,
        log_key: str = "log",
    ) -> None:
        operation = self._api_operation_name(path)
        if isinstance(body, Mapping) and body.get("success") is True:
            return
        msg: str | None = None
        if isinstance(body, Mapping):
            raw = body.get(log_key)
            if raw is None:
                raw = body.get("message")
            if raw is not None:
                msg = str(raw)
        if msg is None:
            msg = response.text[:2000]
        raise SlideScoreAPIError(
            f"SlideScore API reported failure for {operation!r}: {msg}",
            status_code=response.status_code,
            server_message=msg,
            endpoint=operation,
        )

    def perform_request(
        self,
        path: str,
        *,
        params: Mapping[str, APIParamValue] | None = None,
        data: Mapping[str, APIParamValue | str] | None = None,
        method: str = "GET",
        stream: bool = True,
    ) -> requests.Response:
        """
        Call ``/Api/<path>``.

        Swagger documents parameters ``in: query``; the API introduction also
        allows the same keys in the form body. We send:

        * **GET** — query string only (``params``).
        * **POST** — query string (``params``) plus optional form body (``data``).

        Query and form keys follow the usual Swagger **camelCase** names
        (e.g. ``imageId``, ``caseId``, ``studyId``).

        Omit keys whose value is ``None`` so optional filters are not sent as
        the literal string ``"None"``.

        For very large ``UploadResults`` payloads, use ``data=`` so the request
        stays within URL length limits even though Swagger lists ``results`` as
        a query parameter.

        When ``data`` is a plain ``dict``, ``requests`` sends
        ``application/x-www-form-urlencoded`` (no file upload).
        """
        if method not in ("GET", "POST"):
            raise SlideScoreAPIError(
                f"Expected HTTP method GET or POST, got {method!r}",
                endpoint=self._api_operation_name(path),
            )
        if method == "GET" and data:
            raise SlideScoreAPIError(
                "GET requests cannot include a form body (use ``params`` only).",
                endpoint=self._api_operation_name(path),
            )

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }
        url = f"{self.end_point}{self._api_operation_name(path)}"
        verify = not self.disable_cert_checking
        query = self._api_params(params)
        form = self._api_params(data)

        if method == "GET":
            response = requests.get(
                url,
                headers=headers,
                params=query,
                stream=stream,
                verify=verify,
            )
        else:
            response = requests.post(
                url,
                headers=headers,
                params=query,
                data=form,
                stream=stream,
                verify=verify,
            )

        if response.status_code != 200:
            operation = self._api_operation_name(path)
            raise SlideScoreAPIError(
                f"SlideScore API HTTP {response.status_code} for {operation!r}: "
                f"{response.text[:1000]}",
                status_code=response.status_code,
                server_message=response.text,
                endpoint=operation,
            )
        return response

    def get_images(self, study_id: int) -> JSONValue:
        """
        Get slide data (no slides) for all slides in the study.
        Parameters
        ----------
        study_id : int
        Returns
        -------
        dict
            Dictionary containing the images in the study.
        For example to download all slides in a study with id 1 into the current directory you need to do
            client = APIClient(url, token)
            for f in client.get_images(1):
                client.download_slide(1, f["id"], ".")


        """
        response = self.perform_request("Images", params={"studyId": study_id})
        return self._response_json(response, "Images")

    def get_cases(self, study_id: int) -> JSONValue:
        """
        Get all case names and IDs
        Parameters
        ----------
        study_id : int
        Returns
        -------
        dict
            Dictionary containing the cases in the study.
        For example:
            client = APIClient(url, token)
            for c in client.get_cases(1):
                print(str(c["id"])+" - " + c["name"])


        """
        response = self.perform_request("Cases", params={"studyId": study_id})
        return self._response_json(response, "Cases")

    def get_studies(self) -> JSONValue:
        """
        Get list of studies this token can access
        Parameters
        ----------
        None

        Returns
        -------
        dict
            Dictionary containing the studies.
        """
        response = self.perform_request("Studies")
        return self._response_json(response, "Studies")

    def get_results(
        self,
        study_id: int,
        question: str | None = None,
        email: str | None = None,
        image_id: int | None = None,
        case_id: int | None = None,
    ) -> list[SlideScoreResult]:
        """
        Basic functionality to download all answers for a particular study.
        Returns a SlideScoreResult class wrapper containing the information.
        Parameters
        ----------
        study_id : int
            ID of SlideScore study.
        question: string
            Filter for results for this question
        email: string
            Filter for results from this user
        image_id: int
            Filter for results on this image
        case_id: int
            Filter for results on this case
        Returns
        -------
        List[SlideScoreResult]
            List of SlideScore results.
        """
        response = self.perform_request(
            "Scores",
            params={
                "studyId": study_id,
                "question": question,
                "email": email,
                "imageId": image_id,
                "caseId": case_id,
            },
        )
        rjson = self._response_json(response, "Scores")
        return [SlideScoreResult.from_api_response(r) for r in rjson]

    def get_config(self, study_id: int) -> JSONValue:
        """
        Get the configuration of a particular study. Returns a dictionary.
        Parameters
        ----------
        study_id : int
            ID of SlideScore study.
        Returns
        -------
        dict
        """
        response = self.perform_request(
            "GetConfig", params={"studyId": study_id}
        )
        rjson = self._response_json(response, "GetConfig")
        self._require_api_success(rjson, response, "GetConfig")
        return rjson["config"]

    def get_config_files(self, study_id: int) -> JSONValue:
        """
        Get the configuration files of a particular study. Returns a dictionary with file contents for each file.
        Parameters
        ----------
        study_id : int
            ID of SlideScore study.
        Returns
        -------
        dict
        """
        response = self.perform_request(
            "GetConfigFiles", params={"studyId": study_id}
        )
        rjson = self._response_json(response, "GetConfigFiles")
        self._require_api_success(rjson, response, "GetConfigFiles")
        return rjson

    def upload_results(
        self, study_id: int, results: Sequence[SlideScoreResult]
    ) -> bool:
        """
        POST ``/Api/UploadResults``. Swagger lists ``studyId`` and multiline
        ``results`` as query parameters; the server also accepts the same keys
        as form fields, which avoids URL length limits for large imports.

        The first line of ``results`` is **ignored** (header row). This client
        prefixes a ``#header`` line per the SlideScore API documentation so
        every :class:`SlideScoreResult` row is imported.
        """
        payload = _encode_upload_results_payload(results)
        response = self.perform_request(
            "UploadResults",
            method="POST",
            data={"studyId": study_id, "results": payload},
        )
        body = self._response_json(response, "UploadResults")
        self._require_api_success(body, response, "UploadResults")
        return True

    def upload_ASAP(
        self,
        image_id: int,
        user: str,
        questions_map: Mapping[str, str],
        annotation_name: str,
        asap_annotation: str,
    ) -> bool:
        response = self.perform_request(
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
        body = self._response_json(response, "UploadASAPAnnotations")
        self._require_api_success(body, response, "UploadASAPAnnotations")
        return True

    def export_ASAP(
        self, image_id: int, user: str, question: str
    ) -> str | None:
        response = self.perform_request(
            "ExportASAPAnnotations",
            params={"imageId": image_id, "user": user, "question": question},
        )
        text = response.text
        if text[:1] == "<":
            return text
        body = self._response_json(response, "ExportASAPAnnotations")
        self._require_api_success(body, response, "ExportASAPAnnotations")
        return None

    def get_image_server_url(self, image_id: int) -> tuple[str, str]:
        response = self.perform_request(
            "GetTileServer", params={"imageId": image_id}
        )
        data = self._response_json(response, "GetTileServer")
        origin = self.end_point.removesuffix("/Api/")
        tile_root = f"{origin}/i/{image_id}/{data['urlPart']}/i_files"
        return tile_root, data["cookiePart"]

    def _get_filename(self, content_disposition: str) -> str:
        fname = re.findall(
            "filename*?=([^;]+)", content_disposition, flags=re.IGNORECASE
        )
        fname = fname[0].strip().strip('"')

        # Normalize unicode characters (e.g., 'ñ' becomes 'n')
        fname = (
            unicodedata.normalize("NFKD", fname)
            .encode("ascii", "ignore")
            .decode("ascii")
        )

        fname = re.sub(r"[^\w\s.\-,;=]", "_", fname).strip()
        return fname

    def download_slide(
        self,
        study_id: int,
        image_id: int,
        directory: str | Path,
    ) -> None:
        response = self.perform_request(
            "DownloadSlide",
            method="GET",
            params={"studyId": study_id, "imageId": image_id},
        )
        fname = self._get_filename(response.headers["Content-Disposition"])
        out_path = Path(directory) / fname
        with out_path.open("wb") as outfile:
            for chunk in response.iter_content(chunk_size=8192):
                outfile.write(chunk)

    def get_screenshot_whole(
        self,
        image_id: int,
        user: str,
        question: str,
        output_file: str | Path,
    ) -> None:
        response = self.perform_request(
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

    def request_upload(
        self,
        destination_folder: str,
        destination_filename: str,
        study_id: int | None,
    ) -> str:
        response = self.perform_request(
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
                endpoint=self._api_operation_name("RequestUpload"),
            )
        body = self._response_json(response, "RequestUpload")
        return str(body["token"])

    def finish_upload(self, upload_token: str, upload_url: str) -> None:
        file_id = upload_url.rstrip("/").rsplit("/", 1)[-1]
        response = self.perform_request(
            "FinishUpload",
            method="POST",
            params={"id": file_id, "token": upload_token},
        )
        if response.text != '"OK"':
            raise SlideScoreAPIError(
                f"Failed finishing upload: {response.text}",
                status_code=response.status_code,
                server_message=response.text,
                endpoint=self._api_operation_name("FinishUpload"),
            )

    def upload_file(
        self,
        source_filename: str | Path,
        destination_path: str,
        destination_filename: str | None = None,
    ) -> None:
        source_path = Path(source_filename)
        if destination_filename is None:
            destination_filename = source_path.name
        upload_token = self.request_upload(
            destination_path, destination_filename, None
        )
        self.upload_using_token(str(source_path), upload_token)

    def upload_using_token(self, source_filename: str, upload_token: str) -> None:
        tus_base = self.end_point.replace("/Api/", "/files/")
        tus_client = client.TusClient(tus_base)
        uploader = tus_client.uploader(
            source_filename,
            chunk_size=10 * 1000 * 1000,
            metadata={"uploadtoken": upload_token, "apitoken": self.api_token},
        )
        uploader.upload()
        self.finish_upload(upload_token, uploader.url)

    def add_slide(self, study_id: int, destination_filename: str) -> dict[str, JSONValue]:
        response = self.perform_request(
            "AddSlide",
            method="POST",
            params={"studyId": study_id, "path": destination_filename},
        )
        if response.text[:1] == '"':
            raise SlideScoreAPIError(
                "Failed adding slide: " + response.text,
                status_code=response.status_code,
                server_message=response.text,
                endpoint=self._api_operation_name("AddSlide"),
            )
        rjson = self._response_json(response, "AddSlide")
        self._require_api_success(rjson, response, "AddSlide")
        return {"id": rjson["id"], "isOOF": rjson["isOOF"]}

    def reimport(self, study_name: str) -> dict[str, JSONValue]:
        response = self.perform_request(
            "Reimport", method="POST", params={"studyName": study_name}
        )
        if response.text[:1] == '"':
            raise SlideScoreAPIError(
                "Failed reimporting: " + response.text,
                status_code=response.status_code,
                server_message=response.text,
                endpoint=self._api_operation_name("Reimport"),
            )
        rjson = self._response_json(response, "Reimport")
        self._require_api_success(rjson, response, "Reimport")
        return {"id": rjson["id"], "log": rjson["log"]}

    def get_slide_path(self, image_id: int) -> str:
        response = self.perform_request(
            "GetSlidePath", method="GET", params={"imageId": image_id}
        )
        rjson = self._response_json(response, "GetSlidePath")
        self._require_api_success(rjson, response, "GetSlidePath")
        return rjson["path"]

    def get_slide_description(self, image_id: int) -> str:
        response = self.perform_request(
            "GetSlideDescription",
            method="GET",
            params={"imageId": image_id},
        )
        rjson = self._response_json(response, "GetSlideDescription")
        self._require_api_success(rjson, response, "GetSlideDescription")
        return rjson["description"]

    def get_case_description(self, case_id: int) -> str:
        response = self.perform_request(
            "GetCaseDescription", method="GET", params={"caseId": case_id}
        )
        rjson = self._response_json(response, "GetCaseDescription")
        self._require_api_success(rjson, response, "GetCaseDescription")
        return rjson["description"]

    def update_slide_path(self, image_id: int, new_path: str) -> None:
        response = self.perform_request(
            "UpdateSlidePath",
            method="POST",
            params={"imageId": image_id, "newPath": new_path},
        )
        rjson = self._response_json(response, "UpdateSlidePath")
        self._require_api_success(rjson, response, "UpdateSlidePath")

    def update_slide_description(
        self, study_id: int, image_id: int, new_description: str
    ) -> None:
        response = self.perform_request(
            "SetSlideDescription",
            method="POST",
            params={
                "imageId": image_id,
                "studyId": study_id,
                "description": new_description,
            },
        )
        self._response_json(response, "SetSlideDescription")
        if response.text != "{}":
            raise SlideScoreAPIError(
                "Failed updating slide description: " + response.text,
                status_code=response.status_code,
                server_message=response.text,
                endpoint=self._api_operation_name("SetSlideDescription"),
            )

    def update_slide_name(self, image_id: int, new_name: str) -> None:
        response = self.perform_request(
            "UpdateSlideName",
            method="POST",
            params={"imageId": image_id, "newName": new_name},
        )
        rjson = self._response_json(response, "UpdateSlideName")
        self._require_api_success(rjson, response, "UpdateSlideName")

    def add_question(self, study_id: int, question_spec: str) -> JSONValue:
        response = self.perform_request(
            "AddQuestion",
            method="POST",
            params={"studyId": study_id, "questionSpec": question_spec},
        )
        rjson = self._response_json(response, "AddQuestion")
        self._require_api_success(rjson, response, "AddQuestion")
        return rjson["id"]

    def update_question(
        self, study_id: int, score_id: int, order: int, question_spec: str
    ) -> JSONValue:
        response = self.perform_request(
            "UpdateQuestion",
            method="POST",
            params={
                "studyId": study_id,
                "scoreId": score_id,
                "order": order,
                "questionSpec": question_spec,
            },
        )
        rjson = self._response_json(response, "UpdateQuestion")
        self._require_api_success(rjson, response, "UpdateQuestion")
        return rjson["id"]

    def remove_question(self, study_id: int, score_id: int) -> bool:
        response = self.perform_request(
            "RemoveQuestion",
            method="POST",
            params={"studyId": study_id, "scoreId": score_id},
        )
        rjson = self._response_json(response, "RemoveQuestion")
        self._require_api_success(rjson, response, "RemoveQuestion")
        return True

    def set_slide_tma_map(
        self, study_id: int, image_id: int, tma_map_name: str
    ) -> None:
        response = self.perform_request(
            "SetSlideTMAMap",
            method="POST",
            params={
                "studyId": study_id,
                "imageId": image_id,
                "tmaMapName": tma_map_name,
            },
        )
        rjson = self._response_json(response, "SetSlideTMAMap")
        self._require_api_success(rjson, response, "SetSlideTMAMap")

    def create_tma_map(self, study_id: int, tma_map_filename: str) -> str:
        response = self.perform_request(
            "CreateTMAMap",
            method="POST",
            params={"studyId": study_id, "tmaMapFileName": tma_map_filename},
        )
        rjson = self._response_json(response, "CreateTMAMap")
        self._require_api_success(rjson, response, "CreateTMAMap")
        return rjson["mapName"]

    def is_slide_out_of_focus(self, study_id: int, image_id: int) -> bool:
        response = self.perform_request(
            "IsSlideOutOfFocus",
            method="POST",
            params={"studyId": study_id, "imageId": image_id},
        )
        rjson = self._response_json(response, "IsSlideOutOfFocus")
        self._require_api_success(rjson, response, "IsSlideOutOfFocus")
        return rjson["isOOF"]

    def get_raw_tile(
        self,
        study_id: int,
        image_id: int,
        level: int,
        x: int,
        y: int,
        width: int,
        height: int,
        jpeg_quality: int,
    ) -> requests.Response:
        """
        Get slide pixels
        Parameters
        ----------
        study_id : int
        image_id : int
        level: int
            Level in the slide (0-highest detail), based on slide metadata
        x: int
        y: int
            X and Y of the tile
        width: int
        height: int
            Size of the requested region
        jpeg_quality: int

        Returns
        -------
        jpeg file


        """
        return self.perform_request(
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

    def convert_to_anno2(
        self,
        items: Anno2ConvertInput,
        metadata: JSONValue | None,
        output_path: str | Path,
    ) -> None:
        """Converts a SlideScore Annotation Object to the new Anno2 zip based format
        Supports points, polygons/brush, or a :class:`Heatmap` instance (same union as :class:`Encoder`).

        anno1_data: Dictionary containing the annotation like: [{"type": "brush", "positivePolygons": [] ...]
        metadata: Dictionary containing any metadata regarding the annotation, will be included as JSON in output
        output_path: string of the path on disk the anno2.zip will be written to
        """
        # Allow pre-loaded Points, Polygons, and Heatmap objects (match ``Encoder``)
        items_encoder: Points | Polygons | Heatmap
        if isinstance(items, (Points, Polygons, Heatmap)):
            items_encoder = items
        else:
            items_encoder = read_slidescore_json(items)

        encoder = Encoder(items_encoder, big_polygon_size_cutoff=100 * 100)
        encoder.generate_tile_data(256)
        encoder.populate_lookup_tables()

        if metadata:
            encoder.add_metadata(metadata)

        encoder.dump_to_file(str(Path(output_path)))

    def convert_annotation_to_anno2(
        self,
        study_id: int,
        case_id: Anno2OptionalId,
        image_id: int,
        tma_core_id: Anno2OptionalId,
        score_id: Anno2OptionalId,
        question: str | None,
        email: str | None,
        metadata: str | JSONObject | None,
    ) -> str:
        """Converts an existing annotation answer to the new Anno2 zip based format
        case_id, tma_core_id, score_id, and question are optional
        metadata must be a JSON object for example "{}"
        You have to specify one of score_id and question
        """

        response = self.perform_request(
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
        rjson = self._response_json(response, "ConvertAnnotationToAnno2")
        self._require_api_success(rjson, response, "ConvertAnnotationToAnno2")
        return rjson["annoUUID"]

    def create_anno2(
        self,
        study_id: int,
        case_id: Anno2OptionalId,
        image_id: int,
        tma_core_id: Anno2OptionalId,
        score_id: Anno2OptionalId,
        question: str | None,
        email: str | None,
    ) -> dict[str, JSONValue]:
        """Creates a new Anno2 format record
        Returns object with  "uploadToken": "FEU...." and "annoUUID": "8f51008c-9ede-e8b4-cba8-55a2cf6c73bf",

        You have to specify one of score_id and question
        """

        response = self.perform_request(
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
        rjson = self._response_json(response, "CreateAnno2")
        self._require_api_success(rjson, response, "CreateAnno2")
        return cast(dict[str, JSONValue], rjson)

    def generate_login_link(self, username: str, expires_on: str) -> str:
        response = self.perform_request(
            "GenerateLoginLink",
            method="POST",
            params={"username": username, "expiresOn": expires_on},
        )
        rjson = self._response_json(response, "GenerateLoginLink")
        self._require_api_success(rjson, response, "GenerateLoginLink")
        return rjson["link"]

    def generate_student_account(
        self, username: str, email: str, class_id: int
    ) -> str:
        response = self.perform_request(
            "GenerateStudentAccount",
            method="POST",
            params={"username": username, "email": email, "classId": class_id},
        )
        rjson = self._response_json(response, "GenerateStudentAccount")
        self._require_api_success(rjson, response, "GenerateStudentAccount")
        return rjson["password"]

    def get_sessions(
        self,
        study_id: int,
        email: str | None = None,
        image_id: int | None = None,
    ) -> list[SlideScoreSession]:
        response = self.perform_request(
            "Sessions",
            params={"studyId": study_id, "imageId": image_id, "email": email},
        )
        rjson = self._response_json(response, "Sessions")
        self._require_api_success(rjson, response, "Sessions")
        return [SlideScoreSession.from_api_response(r) for r in rjson["sessions"]]

    def get_session_events(
        self, study_id: int, session_id: int
    ) -> list[SlideScoreSessionEvent]:
        response = self.perform_request(
            "SessionEvents",
            params={"studyId": study_id, "sessionId": session_id},
        )
        rjson = self._response_json(response, "SessionEvents")
        self._require_api_success(rjson, response, "SessionEvents")
        return [
            SlideScoreSessionEvent.from_tsv_line(r) for r in rjson["events"]
        ]

    def upload_attachment(
        self,
        study_id: int | None,
        module_id: int | None,
        filename: str | Path,
        label: str,
    ) -> str:
        """Upload a file and return an HTML snippet linking to it on SlideScore."""
        filename_only = Path(filename).name
        response = self.perform_request(
            "RequestUploadAttachment",
            method="POST",
            params={
                "studyId": study_id,
                "moduleId": module_id,
                "filename": filename_only,
            },
        )
        body = self._response_json(response, "RequestUploadAttachment")
        self._require_api_success(body, response, "RequestUploadAttachment")
        base_url = self.end_point.removesuffix("/Api/")
        temp_api_token = body["token"]
        folder = body["folder"]
        new_filename = body["filename"]
        att_id = body["attId"]
        attachment_client = APIClient(base_url, temp_api_token)
        attachment_client.upload_file(str(Path(filename)), folder, new_filename)
        short_guid = new_filename.split("-")[0]
        return (
            f'<div><a href="{base_url}/a/{att_id}/{short_guid}/{filename_only}" '
            'target="_blank" rel="noopener" class="jsSquireAttachment jsSquireLink" '
            'style="display: inline-block;">'
            '<span class="glyphicon glyphicon glyphicon-paperclip"> </span>&nbsp;'
            f"{label}&nbsp;</a><br></div>"
        )
