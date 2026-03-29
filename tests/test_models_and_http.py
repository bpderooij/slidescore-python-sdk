"""Offline tests for Phase 2 dataclasses, aliases, and HTTP helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import slidescore


def test_slidescore_error_exception_is_api_error_alias() -> None:
    assert slidescore.SlideScoreErrorException is slidescore.SlideScoreAPIError


def test_slide_score_api_error_fields() -> None:
    err = slidescore.SlideScoreAPIError(
        "msg",
        status_code=400,
        server_message="bad",
        endpoint="Scores",
    )
    assert err.status_code == 400
    assert err.server_message == "bad"
    assert err.endpoint == "Scores"
    assert str(err) == "msg"


def test_slide_score_result_from_api_response_matches_constructor() -> None:
    payload = {
        "id": 1,
        "imageID": 2,
        "imageName": "n",
        "user": "u",
        "question": "q",
        "answer": "plain",
    }
    a = slidescore.SlideScoreResult.from_api_response(payload)
    b = slidescore.SlideScoreResult.from_api_response(payload)
    assert a == b
    assert a.annotations is None
    assert a.points is None


def test_slide_score_result_always_has_annotation_point_attributes() -> None:
    r = slidescore.SlideScoreResult()
    assert r.annotations is None
    assert r.points is None


def test_slide_score_session_from_api_response() -> None:
    payload = {
        "id": 1,
        "imageID": 2,
        "email": "e@ex.com",
        "length": 100,
        "studyID": 3,
        "createdOn": "2024-01-15T10:20:30.1234567",
    }
    s = slidescore.SlideScoreSession.from_api_response(payload)
    assert s.id == 1
    assert s.image_id == 2
    assert s.study_id == 3
    assert s.email == "e@ex.com"
    assert s.created_on is not None


def test_slide_score_session_from_api_response_omitted_email_is_empty_string() -> None:
    payload = {
        "id": 1,
        "imageID": 2,
        "length": 100,
        "studyID": 3,
        "createdOn": "2024-01-15T10:20:30.1234567",
    }
    s = slidescore.SlideScoreSession.from_api_response(payload)
    assert s.email == ""


def test_slide_score_session_event_from_tsv_line() -> None:
    ev = slidescore.SlideScoreSessionEvent.from_tsv_line(
        "1	10	20	100	200	5	6"
    )
    assert ev.timestamp == 1
    assert ev.x == 10
    assert ev.y == 20
    assert ev.width == 100
    assert ev.height == 200
    assert ev.cursor_x == 5
    assert ev.cursor_y == 6


def test_slide_score_session_event_from_tsv_line_too_short() -> None:
    with pytest.raises(ValueError, match="tab-separated"):
        slidescore.SlideScoreSessionEvent.from_tsv_line("a	b")


def test_get_images_uses_study_id_casing() -> None:
    captured: dict = {}

    def fake_get(url, verify=True, headers=None, params=None, stream=True, **kwargs):
        captured["params"] = params
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = []
        r.text = "[]"
        return r

    client = slidescore.APIClient("https://example.com", "token")
    with patch("slidescore.slidescore.requests.get", side_effect=fake_get):
        client.get_images(7)
    assert captured["params"] == {"studyId": 7}


def test_get_results_uses_swagger_query_names() -> None:
    captured: dict = {}

    def fake_get(url, verify=True, headers=None, params=None, stream=True, **kwargs):
        captured["params"] = params
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = []
        r.text = "[]"
        return r

    client = slidescore.APIClient("https://example.com", "token")
    with patch("slidescore.slidescore.requests.get", side_effect=fake_get):
        client.get_results(1, question="Q", email="e", image_id=2, case_id=3)
    assert captured["params"] == {
        "studyId": 1,
        "question": "Q",
        "email": "e",
        "imageId": 2,
        "caseId": 3,
    }


def test_upload_asap_posts_image_id_key() -> None:
    posted: dict = {}

    def fake_post(url, verify=True, headers=None, data=None, **kwargs):
        posted.clear()
        posted.update(data or {})
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"success": True}
        r.text = '{"success":true}'
        return r

    client = slidescore.APIClient("https://example.com", "token")
    with patch("slidescore.slidescore.requests.post", side_effect=fake_post):
        client.upload_ASAP(
            42,
            "user",
            {"#e6194b": "Test anno"},
            "Annotation",
            "<ASAP/>",
        )
    assert posted["imageId"] == 42


def test_require_api_success_raises_with_endpoint() -> None:
    client = slidescore.APIClient("https://example.com", "token")
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"success":false,"log":"nope"}'
    with pytest.raises(slidescore.SlideScoreAPIError) as exc_info:
        client._require_api_success(
            {"success": False, "log": "nope"}, resp, "UploadResults"
        )
    assert exc_info.value.endpoint == "UploadResults"
    assert exc_info.value.server_message == "nope"


def test_slide_score_result_keyword_constructor() -> None:
    r = slidescore.SlideScoreResult(
        image_id=10,
        image_name="slide",
        user="u",
        question="q",
        answer="plain",
    )
    assert r.id == 0
    assert r.image_id == 10
    assert r.user == "u"
    assert r.question == "q"
    assert r.answer == "plain"
    assert r.annotations is None


def test_validate_for_upload_rejects_incomplete_row() -> None:
    with pytest.raises(ValueError, match="image_id"):
        slidescore.SlideScoreResult(
            question="q", user="u", image_name="n"
        ).validate_for_upload()
    with pytest.raises(ValueError, match="question"):
        slidescore.SlideScoreResult(
            image_id=1, user="u", image_name="n"
        ).validate_for_upload()


def test_as_slidescore_results_row_allows_empty_answer() -> None:
    row = slidescore.SlideScoreResult(
        image_id=1,
        image_name="slide",
        user="u@example.com",
        question="q",
        answer=None,
    )
    line = row.as_slidescore_results_row()
    assert line.endswith("\tq\t")


def test_validate_for_upload_rejects_partial_tma() -> None:
    with pytest.raises(ValueError, match="tma_col"):
        slidescore.SlideScoreResult(
            image_id=1,
            image_name="s",
            user="u",
            question="q",
            answer="a",
            tma_row=1,
            tma_col=None,
            tma_sample_id="x",
        ).validate_for_upload()


def test_slide_score_result_as_slidescore_results_row() -> None:
    row = slidescore.SlideScoreResult.from_api_response(
        {
            "id": 1,
            "imageID": 2,
            "imageName": "n",
            "user": "u",
            "question": "q",
            "answer": "a",
        }
    )
    assert row.as_slidescore_results_row() == row.toRow()
    assert not row.as_slidescore_results_row().startswith("\n")


def test_upload_results_posts_form_body_not_leading_newline() -> None:
    posted: dict = {}

    def fake_post(url, verify=True, headers=None, params=None, data=None, **kwargs):
        posted.clear()
        posted["params"] = params
        posted["data"] = dict(data or {})
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"success": True}
        return r

    a = slidescore.SlideScoreResult.from_api_response(
        {
            "id": 1,
            "imageID": 9,
            "imageName": "s",
            "user": "u",
            "question": "q",
            "answer": "x",
        }
    )
    client = slidescore.APIClient("https://example.com", "token")
    with patch("slidescore.slidescore.requests.post", side_effect=fake_post):
        client.upload_results(3, [a])
    assert posted["data"]["studyId"] == 3
    assert not str(posted["data"]["results"]).startswith("\n")
    assert posted["data"]["results"] == a.as_slidescore_results_row()


def test_upload_results_joins_multiple_rows_with_single_newline() -> None:
    posted: dict = {}

    def fake_post(url, verify=True, headers=None, params=None, data=None, **kwargs):
        posted["data"] = dict(data or {})
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"success": True}
        return r

    r1 = slidescore.SlideScoreResult(
        image_id=1,
        image_name="a",
        user="u",
        question="q1",
        answer="x",
    )
    r2 = slidescore.SlideScoreResult(
        image_id=1,
        image_name="a",
        user="u",
        question="q2",
        answer="y",
    )
    client = slidescore.APIClient("https://example.com", "token")
    with patch("slidescore.slidescore.requests.post", side_effect=fake_post):
        client.upload_results(9, [r1, r2])
    body = posted["data"]["results"]
    assert body.count("\n") == 1
    a, b = body.split("\n", 1)
    assert a == r1.as_slidescore_results_row()
    assert b == r2.as_slidescore_results_row()


def test_slide_score_session_keyword_constructor() -> None:
    s = slidescore.SlideScoreSession(id=1, image_id=2, email="a@b.c", length=9)
    assert s.id == 1
    assert s.length == 9
    assert s.study_id is None


def test_slide_score_session_event_keyword_constructor() -> None:
    ev = slidescore.SlideScoreSessionEvent(timestamp=3, x=1, y=2, width=4, height=5, cursor_x=6, cursor_y=7)
    assert ev.timestamp == 3
    assert ev.cursor_y == 7
