from pathlib import Path

from core.database import database
from extractor.celery_app import celery_app
from extractor.service import process_tar


@celery_app.task(bind=True)
def extract_course_task(self, tar_path: str) -> dict:
    """Background extraction: unpack tar -> extract -> persist Course, reporting
    per-video progress to the Celery result backend. Deletes the tar when done."""
    tar = Path(tar_path)

    def progress(done: int, total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={
                "current": done,
                "total": total,
                "percent": round(done / total * 100) if total else 0,
                "message": (f"downloading videos ({done}/{total})" if total
                            else "processing"),
            },
        )

    db = database.SessionLocal()
    try:
        course = process_tar(tar, db, progress=progress)
        return {
            "id": course.id,
            "course_name": course.course_name,
            "zip_file_path": course.zip_file_path,
            "extracted_json_path": course.extracted_json_path,
        }
    finally:
        db.close()
        tar.unlink(missing_ok=True)