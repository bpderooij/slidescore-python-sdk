from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import requests
from tusclient import client

from .errors import SlideScoreAPIError, SlideScoreErrorException
from .lib.AnnoClasses import Heatmap, Points, Polygons
from .lib.Encoder import Encoder
from .lib.utils import read_slidescore_json
from .models import (
    SlideScoreResult,
    SlideScoreSession,
    SlideScoreSessionEvent,
    _encode_upload_results_payload,
)
from .types import (
    Anno2ConvertInput,
    Anno2OptionalId,
    APIParamValue,
    JSONObject,
    JSONValue,
    SlideScoreAnnotationJson,
    SlideScorePointCoordJson,
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
        except Exception as exc:
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

        # Normalize unicode characters (e.g., 'ñ' becomes 'n')
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
