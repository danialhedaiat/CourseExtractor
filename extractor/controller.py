from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from core.database import database
from core.settings import settings
from extractor.celery_app import celery_app
from extractor.models import Course
from extractor.tasks import extract_course_task

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("/upload", status_code=202)
async def upload_course(file: UploadFile = File(...)) -> dict:
    """Receive a course .tar and queue extraction; returns a task id to poll."""
    if not file.filename or not file.filename.endswith(settings.ALLOWED_EXTENSION):
        raise HTTPException(
            status_code=400,
            detail=f"A {settings.ALLOWED_EXTENSION} file is required",
        )

    upload_dir = Path(settings.UPLOAD_DIR) / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tar_path = upload_dir / Path(file.filename).name

    try:
        with tar_path.open("wb") as out:
            while chunk := await file.read(settings.CHUNK_SIZE):
                out.write(chunk)
    finally:
        await file.close()

    task = extract_course_task.delay(str(tar_path))
    return {
        "task_id": task.id,
        "status": "processing",
        "status_url": f"/courses/jobs/{task.id}",
    }


@router.get("/jobs/{task_id}")
async def job_status(task_id: str) -> dict:
    """Progress/status of an extraction task (poll this to drive a progress bar)."""
    res = AsyncResult(task_id, app=celery_app)
    body: dict = {"task_id": task_id, "state": res.state}
    if res.state == "PROGRESS":
        body.update(res.info or {})
    elif res.state == "SUCCESS":
        body["result"] = res.result
    elif res.state == "FAILURE":
        body["error"] = str(res.info)
    return body


@router.get("/{course_id}/zip")
async def download_zip(course_id: int, db: Session = Depends(database.get_db)):
    """Download the extracted course bundle (.zip)."""
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    path = Path(course.zip_file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Zip file not found")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.get("/{course_id}/json")
async def download_json(course_id: int, db: Session = Depends(database.get_db)):
    """Download the extracted course JSON."""
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    path = Path(course.extracted_json_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="JSON file not found")
    return FileResponse(path, filename=path.name, media_type="application/json")