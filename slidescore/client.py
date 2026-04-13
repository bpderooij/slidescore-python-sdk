from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import requests

from .annotations import Annotations
from .api import annotations, scores, sessions, slides, studies, tiles, uploads
from .errors import SlideScoreAPIError
from .models import SlideScoreResult, SlideScoreSession, SlideScoreSessionEvent
from .types import (
    Anno2Items,
    Anno2OptionalId,
    APIParamValue,
    JSONObject,
    JSONValue,
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

        * **GET** -- query string only (``params``).
        * **POST** -- query string (``params``) plus optional form body (``data``).

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

    # ------------------------------------------------------------------ #
    # Forwarding methods -- logic lives in api/ modules                     #
    # ------------------------------------------------------------------ #

    def get_studies(self) -> JSONValue:
        return studies.get_studies(self)

    def get_config(self, study_id: int) -> JSONValue:
        return studies.get_config(self, study_id)

    def get_config_files(self, study_id: int) -> JSONValue:
        return studies.get_config_files(self, study_id)

    def reimport(self, study_name: str) -> dict[str, JSONValue]:
        return studies.reimport(self, study_name)

    def get_images(self, study_id: int) -> JSONValue:
        return studies.get_images(self, study_id)

    def download_slide(
        self, study_id: int, image_id: int, directory: str | Path
    ) -> None:
        return slides.download_slide(self, study_id, image_id, directory)

    def get_slide_path(self, image_id: int) -> str:
        return slides.get_slide_path(self, image_id)

    def update_slide_path(self, image_id: int, new_path: str) -> None:
        return slides.update_slide_path(self, image_id, new_path)

    def update_slide_name(self, image_id: int, new_name: str) -> None:
        return slides.update_slide_name(self, image_id, new_name)

    def update_slide_description(
        self, study_id: int, image_id: int, new_description: str
    ) -> None:
        return slides.update_slide_description(self, study_id, image_id, new_description)

    def add_slide(self, study_id: int, destination_filename: str) -> dict[str, JSONValue]:
        return slides.add_slide(self, study_id, destination_filename)

    def get_slide_description(self, image_id: int) -> str:
        return slides.get_slide_description(self, image_id)

    def get_case_description(self, case_id: int) -> str:
        return studies.get_case_description(self, case_id)

    def is_slide_out_of_focus(self, study_id: int, image_id: int) -> bool:
        return slides.is_slide_out_of_focus(self, study_id, image_id)

    def set_slide_tma_map(
        self, study_id: int, image_id: int, tma_map_name: str
    ) -> None:
        return slides.set_slide_tma_map(self, study_id, image_id, tma_map_name)

    def create_tma_map(self, study_id: int, tma_map_filename: str) -> str:
        return slides.create_tma_map(self, study_id, tma_map_filename)

    def get_results(
        self,
        study_id: int,
        question: str | None = None,
        email: str | None = None,
        image_id: int | None = None,
        case_id: int | None = None,
    ) -> list[SlideScoreResult]:
        return scores.get_results(self, study_id, question, email, image_id, case_id)

    def upload_results(
        self, study_id: int, results: Sequence[SlideScoreResult]
    ) -> bool:
        return scores.upload_results(self, study_id, results)

    def get_cases(self, study_id: int) -> JSONValue:
        return studies.get_cases(self, study_id)

    def add_question(self, study_id: int, question_spec: str) -> JSONValue:
        return scores.add_question(self, study_id, question_spec)

    def update_question(
        self, study_id: int, score_id: int, order: int, question_spec: str
    ) -> JSONValue:
        return scores.update_question(self, study_id, score_id, order, question_spec)

    def remove_question(self, study_id: int, score_id: int) -> bool:
        return scores.remove_question(self, study_id, score_id)

    def upload_ASAP(
        self,
        image_id: int,
        user: str,
        questions_map: Mapping[str, str],
        annotation_name: str,
        asap_annotation: str,
    ) -> bool:
        return annotations.upload_ASAP(
            self, image_id, user, questions_map, annotation_name, asap_annotation
        )

    def export_ASAP(self, image_id: int, user: str, question: str) -> str | None:
        return annotations.export_ASAP(self, image_id, user, question)

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
        return annotations.create_anno2(
            self, study_id, case_id, image_id, tma_core_id, score_id, question, email
        )

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
        return annotations.convert_annotation_to_anno2(
            self,
            study_id,
            case_id,
            image_id,
            tma_core_id,
            score_id,
            question,
            email,
            metadata,
        )

    def convert_to_anno2(
        self,
        items: Annotations | Anno2Items | list[JSONObject],
        metadata: JSONValue | None,
        output_path: str | Path,
    ) -> None:
        return annotations.convert_to_anno2(self, items, metadata, output_path)

    def request_upload(
        self,
        destination_folder: str,
        destination_filename: str,
        study_id: int | None,
    ) -> str:
        return uploads.request_upload(self, destination_folder, destination_filename, study_id)

    def finish_upload(self, upload_token: str, upload_url: str) -> None:
        return uploads.finish_upload(self, upload_token, upload_url)

    def upload_using_token(self, source_filename: str, upload_token: str) -> None:
        return uploads.upload_using_token(self, source_filename, upload_token)

    def upload_file(
        self,
        source_filename: str | Path,
        destination_path: str,
        destination_filename: str | None = None,
    ) -> None:
        return uploads.upload_file(self, source_filename, destination_path, destination_filename)

    def upload_attachment(
        self,
        study_id: int | None,
        module_id: int | None,
        filename: str | Path,
        label: str,
    ) -> str:
        return uploads.upload_attachment(self, study_id, module_id, filename, label)

    def get_image_server_url(self, image_id: int) -> tuple[str, str]:
        return tiles.get_image_server_url(self, image_id)

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
        return tiles.get_raw_tile(
            self, study_id, image_id, level, x, y, width, height, jpeg_quality
        )

    def get_screenshot_whole(
        self,
        image_id: int,
        user: str,
        question: str,
        output_file: str | Path,
    ) -> None:
        return tiles.get_screenshot_whole(self, image_id, user, question, output_file)

    def get_sessions(
        self,
        study_id: int,
        email: str | None = None,
        image_id: int | None = None,
    ) -> list[SlideScoreSession]:
        return sessions.get_sessions(self, study_id, email, image_id)

    def get_session_events(
        self, study_id: int, session_id: int
    ) -> list[SlideScoreSessionEvent]:
        return sessions.get_session_events(self, study_id, session_id)

    def generate_login_link(self, username: str, expires_on: str) -> str:
        return sessions.generate_login_link(self, username, expires_on)

    def generate_student_account(
        self, username: str, email: str, class_id: int
    ) -> str:
        return sessions.generate_student_account(self, username, email, class_id)
