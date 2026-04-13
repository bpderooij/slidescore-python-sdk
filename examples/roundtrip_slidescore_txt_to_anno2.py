"""Round-trip a SlideScore answer-export TSV through the SDK into anno2 uploads.

Given a TSV that SlideScore produces when you export scores/answers
(``ImageID  Image Name  By  Question  Answer`` with ``Answer`` carrying
the wire-format JSON), this script:

1. Parses each non-empty ``Answer`` via :meth:`Annotations.from_slidescore_json`.
2. Writes the layer to a temporary anno2 ZIP via
   :meth:`Annotations.to_anno2`.
3. Uploads that ZIP against a target ``image_id`` under each row's question
   name, using :func:`slidescore.api.annotations.create_anno2` followed by
   :meth:`APIClient.upload_using_token`.

Intended as a visual-inspection tool: point it at a clean image
(e.g. one with no existing annotations) and open the image in SlideScore
afterwards to confirm every geometry type — point, polygon, ellipse,
rectangle, and brush (with / without holes) — rendered as expected.

Configuration is read from environment variables
``SLIDESCORE_HOST`` / ``SLIDESCORE_API_KEY`` / ``SLIDESCORE_EMAIL``.

Usage:

    python roundtrip_slidescore_txt_to_anno2.py ANSWERS.txt \\
        --study-id 3 --image-id 68
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import slidescore
from slidescore.annotations import Annotations


@dataclass(frozen=True, slots=True)
class _AnswerRow:
    image_id: int
    image_name: str
    by: str
    question: str
    answer: str


def _read_answer_rows(path: Path) -> list[_AnswerRow]:
    """Load the SlideScore TSV into typed rows, dropping empty answers."""
    rows: list[_AnswerRow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for raw in reader:
            answer = (raw.get("Answer") or "").strip()
            if not answer or answer == "[]":
                continue
            rows.append(
                _AnswerRow(
                    image_id=int(raw["ImageID"]),
                    image_name=raw["Image Name"],
                    by=raw["By"],
                    question=raw["Question"],
                    answer=answer,
                )
            )
    return rows


def _answer_to_annotations(row: _AnswerRow) -> Annotations | None:
    """Parse one answer payload into an :class:`Annotations` for its question.

    Plain scalar answers (e.g. radio-button values like ``"SSA2"``) are
    not shape data and are skipped.
    """
    try:
        payload = json.loads(row.answer)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    return Annotations.from_slidescore_json(payload, label=row.question)


def _upload_one(
    client: slidescore.APIClient,
    *,
    study_id: int,
    image_id: int,
    email: str,
    question: str,
    zip_path: Path,
) -> str:
    """Create a CreateAnno2 record, upload the ZIP, return the annotation UUID."""
    created = client.create_anno2(
        study_id=study_id,
        case_id=None,
        image_id=image_id,
        tma_core_id=None,
        score_id=None,
        question=question,
        email=email,
    )
    upload_token = str(created["uploadToken"])
    anno_uuid = str(created["annoUUID"])
    client.upload_using_token(str(zip_path), upload_token)
    return anno_uuid


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"missing env var {name}")
    return value


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("txt_path", type=Path, help="SlideScore answers TSV")
    parser.add_argument(
        "--study-id", type=int, required=True, help="target SlideScore study id"
    )
    parser.add_argument(
        "--image-id",
        type=int,
        required=True,
        help="target image id on the study (should have no existing answers)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse + build anno2 ZIPs, skip the upload step",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    rows = _read_answer_rows(args.txt_path)
    if not rows:
        print("no non-empty answer rows found")
        return 0

    host = _require_env("SLIDESCORE_HOST").rstrip("/")
    if "://" not in host:
        host = "https://" + host
    api_key = _require_env("SLIDESCORE_API_KEY")
    email = _require_env("SLIDESCORE_EMAIL")
    as_anno2 = False

    client = (
        None
        if args.dry_run
        else slidescore.APIClient(host, api_key)
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        for index, row in enumerate(rows):
            annotations = _answer_to_annotations(row)
            if annotations is None:
                print(f"  [skip] {row.question}: not shape data")
                continue


            if as_anno2:
                zip_path = tmp / f"{index:03d}_{_slug(row.question)}.zip"
                annotations.to_anno2(zip_path)
                size_kib = zip_path.stat().st_size // 1024
                print(
                    f"  [ok ] {row.question}: {zip_path.name} ({size_kib} kiB)"
                )
                if client is None:
                    continue
                anno_uuid = _upload_one(
                    client,
                    study_id=args.study_id,
                    image_id=args.image_id,
                    email=email,
                    question=row.question,
                    zip_path=zip_path,
                )
                print(f"        -> uploaded as {anno_uuid} for question {row.question}")
            else:
                slidescore_result = slidescore.SlideScoreResult(
                    id=args.study_id,
                    image_id=args.image_id,
                    image_name=row.image_name,
                    user=email,
                    question=row.question,
                    answer=json.dumps(annotations.to_slidescore_json()),
                )
                if client is None:
                    continue
                client.upload_results(args.study_id, [slidescore_result])
                print(f"        -> uploaded as {slidescore_result.id} for question {row.question}")

    if client is not None:
        print(
            f"done — view results at {host}/Image/Details?"
            f"imageId={args.image_id}&studyId={args.study_id}"
        )
    return 0


def _slug(text: str) -> str:
    """Make a filesystem-safe slug out of a question name."""
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
