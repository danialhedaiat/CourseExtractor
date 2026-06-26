# Getting Started

## Requirements

- Python 3.11+
- [Redis](https://redis.io/) (broker/result backend for Celery)

## Install

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## Run the API

```bash
.venv/Scripts/python.exe -m uvicorn main:app --reload
```

The interactive API docs are then available at:

- Swagger UI — <http://127.0.0.1:8000/docs>
- ReDoc — <http://127.0.0.1:8000/redoc>

## Run the worker

Extraction runs in a Celery worker, so start one alongside the API (Redis must be
running):

```bash
.venv/Scripts/python.exe -m celery -A extractor.celery_app worker --loglevel=info
```

## Typical flow

1. `POST /courses/upload` with a `.tar` archive → returns a `task_id`.
2. Poll `GET /courses/jobs/{task_id}` until the state is `SUCCESS`.
3. Fetch the result via `GET /courses/{course_id}/zip`, `/json`, or `/show`.

See the **[API Reference](api.md)** for full request/response details.