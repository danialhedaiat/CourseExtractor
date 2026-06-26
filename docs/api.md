# API Reference

All course endpoints are grouped under the `/courses` prefix.

!!! tip
    A live, always-current version of this reference is served by FastAPI itself at
    `/docs` (Swagger UI) and `/redoc` when the app is running.

## `GET /`

Health/root check.

**Response `200`**

```json
{ "message": "Course Extractor API" }
```

---

## `POST /courses/upload`

Receive a course `.tar` and queue extraction. Returns a task id to poll.

**Request** — `multipart/form-data` with a single `file` field (must end in the
configured allowed extension, e.g. `.tar`).

**Response `202`**

```json
{
  "task_id": "8f1c…",
  "status": "processing",
  "status_url": "/courses/jobs/8f1c…"
}
```

**Errors** — `400` if the filename is missing or has the wrong extension.

---

## `GET /courses/jobs/{task_id}`

Progress/status of an extraction task. Poll this to drive a progress bar.

**Response `200`** — shape depends on Celery state:

```json
{ "task_id": "8f1c…", "state": "PROGRESS", "current": 3, "total": 10 }
```

| State | Extra fields |
| --- | --- |
| `PROGRESS` | task-reported progress info |
| `SUCCESS` | `result` |
| `FAILURE` | `error` |

---

## `GET /courses/{course_id}/zip`

Download the extracted course bundle as a `.zip` file.

**Response `200`** — `application/zip` file download.
**Errors** — `404` if the course or its zip file is not found.

---

## `GET /courses/{course_id}/json`

Download the extracted course JSON as a file.

**Response `200`** — `application/json` file download.
**Errors** — `404` if the course or its JSON file is not found.

---

## `GET /courses/{course_id}/show`

Return the extracted course JSON inline (viewable in Swagger / the browser).

**Response `200`** — the parsed course JSON object.
**Errors** — `404` if the course or its JSON file is not found.