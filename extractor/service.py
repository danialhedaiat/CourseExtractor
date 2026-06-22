"""Orchestration: take an uploaded .tar, extract the course, persist a Course row."""

import shutil
import tarfile
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from extractor.extract import MEDIA_DIR, extract_course
from extractor.models import Course


def _safe_extract_tar(tar_path: Path, dest: Path) -> None:
    """Extract a tar into dest, rejecting members that escape dest (path traversal)."""
    dest_resolved = dest.resolve()
    with tarfile.open(tar_path, "r:*") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if dest_resolved != target and dest_resolved not in target.parents:
                raise ValueError(f"Unsafe path in tar: {member.name}")
        tar.extractall(dest)


def _course_id_from(tar_path: Path) -> str:
    """A unique, filesystem-safe id for this upload (tar name + short uuid)."""
    stem = tar_path.stem or "course"
    return f"{stem}-{uuid.uuid4().hex[:8]}"


def process_tar(tar_path: Path, db: Session, progress=None) -> Course:
    """Unpack the tar, extract the OLX course, save a Course row, return it.

    `progress` is an optional callback(done, total) reporting video downloads.
    """
    tar_path = Path(tar_path)
    if not tarfile.is_tarfile(tar_path):
        raise ValueError("Uploaded file is not a valid tar archive")

    course_id = _course_id_from(tar_path)
    # Unpack into MEDIA_DIR/_work/<course_id>/ so extract_course routes assets to
    # MEDIA_DIR/<course_id>/assets (it uses course_dir.parent.name == course_id).
    work = MEDIA_DIR / "_work" / course_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    try:
        _safe_extract_tar(tar_path, work)
        result = extract_course(work, course_id, progress=progress)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    course = Course(
        course_name=result["course_name"] or course_id,
        zip_file_path=result["zip_path"],
        extracted_json_path=result["json_path"],
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course