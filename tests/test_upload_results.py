"""
This test checks the ability to create a study by uploading results to a newly created study
verifying they are saved and making sure invalid results raise an error.
"""

import os
import sys
from datetime import datetime

import pytest

import pytest
import slidescore
from common_lib import create_study


def create_answers(image_id: int, image_name: str, email: str):
    i = 1
    freetext_answer = slidescore.SlideScoreResult.from_api_response(
        {
            "id": -1,
            "imageID": image_id,
            "imageName": image_name,
            "user": email,
            "question": "Test question",
            "answer": f"test answer {i}",
        }
    )

    option_answer = slidescore.SlideScoreResult.from_api_response(
        {
            "id": -1,
            "imageID": image_id,
            "imageName": image_name,
            "user": email,
            "question": "Options question",
            "answer": f"Option{(i % 3) + 1}",
        }
    )
    return [freetext_answer, option_answer]


@pytest.mark.skipif(
    not (os.getenv("SLIDESCORE_HOST") and os.getenv("SLIDESCORE_API_KEY")),
    reason="SLIDESCORE_HOST and SLIDESCORE_API_KEY required",
)
def test_upload_study_results():
    SLIDESCORE_API_KEY = os.getenv("SLIDESCORE_API_KEY")
    SLIDESCORE_HOST = os.getenv("SLIDESCORE_HOST")
    USER_EMAIL = os.getenv("SLIDESCORE_EMAIL") or "pytest@example.com"

    assert SLIDESCORE_HOST and SLIDESCORE_API_KEY and USER_EMAIL
    SLIDESCORE_HOST = (
        SLIDESCORE_HOST[:-1] if SLIDESCORE_HOST.endswith("/") else SLIDESCORE_HOST
    )

    client = slidescore.APIClient(SLIDESCORE_HOST, SLIDESCORE_API_KEY)

    datetime_str = datetime.today().strftime("%Y-%m-%d_%H-%M-%S")
    study_name = f"test-study-upload-questions-{datetime_str}"

    question_str = "Test question	FreeText\nOptions question	ClickFriendlyPollOnly	Option1;;Option2;;Option3"
    study_id, image_id, image_name = create_study(
        client, study_name, USER_EMAIL, question_str
    )
    answers = create_answers(image_id, image_name, USER_EMAIL)

    assert client.upload_results(study_id, answers)

    retrieved_results = client.get_results(study_id)

    answers.sort(key=lambda r: r.as_slidescore_results_row())
    retrieved_results.sort(key=lambda r: r.as_slidescore_results_row())
    for answer_local, answer_remote in zip(answers, retrieved_results, strict=True):
        assert answer_local.as_slidescore_results_row() == answer_remote.as_slidescore_results_row()

    assert client.upload_results(study_id, answers)

    invalid_answer = slidescore.SlideScoreResult.from_api_response(
        {
            "imageID": image_id,
            "imageName": image_name,
            "user": USER_EMAIL,
            "question": "Non-existant question",
            "answer": "answer",
        }
    )
    with pytest.raises(slidescore.SlideScoreAPIError):
        client.upload_results(study_id, [invalid_answer])


def test_slidescore_result_typed_json_answer_sets_annotations():
    r = slidescore.SlideScoreResult.from_api_response(
        {
            "id": 1,
            "imageID": 10,
            "imageName": "slide",
            "user": "u",
            "question": "q",
            "answer": '[{"type":"polygon","points":[{"x":1,"y":2}]}]',
        }
    )
    assert r.annotations is not None
    assert r.annotations[0]["type"] == "polygon"


def test_slidescore_result_plain_xy_json_answer_sets_points():
    r = slidescore.SlideScoreResult.from_api_response(
        {
            "id": 1,
            "imageID": 10,
            "imageName": "slide",
            "user": "u",
            "question": "q",
            "answer": '[{"x": 10, "y": 20}]',
        }
    )
    assert r.points is not None
    assert r.points[0]["x"] == 10


def test_slidescore_result_malformed_json_answer_raises():
    with pytest.raises(ValueError, match="not valid JSON"):
        slidescore.SlideScoreResult({
            "id": 1,
            "imageID": 10,
            "imageName": "slide",
            "user": "u",
            "question": "q",
            "answer": '[{not valid json',
        })


if __name__ == "__main__":
    sys.exit("This file is meant to be ran by PyTest")
