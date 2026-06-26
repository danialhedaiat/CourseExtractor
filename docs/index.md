# Course Extractor

A **FastAPI** service that ingests OpenEdX (OLX) course archives from clients and turns
them into structured data and a relational knowledge graph.

## What it does

- Accepts a course `.tar` upload and queues extraction in the background
  (Celery + Redis), returning a task id to poll.
- Parses the OLX course archive and inventories its contents (course name, problems,
  videos, images, audio).
- Exposes the extracted result as a downloadable `.zip`, a downloadable `.json`,
  or inline JSON for viewing in the browser / Swagger UI.

## Architecture at a glance

| Component | Role |
| --- | --- |
| `main.py` | FastAPI app entrypoint; mounts the `extractor` router. |
| `extractor/controller.py` | API routes under `/courses`. |
| `extractor/tasks.py` | Celery task that runs extraction off the request thread. |
| `extractor/celery_app.py` | Celery app wired to Redis. |
| `core/database.py` | SQLAlchemy session / engine. |
| `core/settings.py` | Settings (`UPLOAD_DIR`, `CHUNK_SIZE`, `ALLOWED_EXTENSION`). |

Continue to **[Getting Started](getting-started.md)** to run it locally, or jump to the
**[API Reference](api.md)**.