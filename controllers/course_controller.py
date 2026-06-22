from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from core.database import database
from core.settings import settings
from extractor.service import process_tar


class CourseController:
    """Class-based API view for course archives.

    Routes are registered against `self.router` in __init__; bound methods hide
    `self` from FastAPI so dependency injection (UploadFile / Depends) works.
    """

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/courses", tags=["courses"])
        self.router.add_api_route("/", self.upload, methods=["POST"], status_code=201)

    async def upload(
        self,
        file: UploadFile = File(...),
        db: Session = Depends(database.get_db),
    ) -> dict:
        """Receive a course .tar, extract it, and store a Course record."""
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

        try:
            course = process_tar(tar_path, db)
        except ValueError as exc:
            tar_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 - surface extraction failures
            raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

        return {
            "id": course.id,
            "course_name": course.course_name,
            "zip_file_path": course.zip_file_path,
            "extracted_json_path": course.extracted_json_path,
        }
