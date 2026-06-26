# Understanding the JSON Output

When a course archive is extracted, the service writes a single
`extracted_<course_id>.json` file (plus a `<course_id>/assets/` media folder, all
bundled into a `.zip`). This page explains every part of that JSON so you know exactly
what you're reading.

You can fetch it three ways (see the [API Reference](api.md)):

- `GET /courses/{course_id}/show` — inline JSON (easiest to browse)
- `GET /courses/{course_id}/json` — the JSON as a file download
- `GET /courses/{course_id}/zip` — JSON **+** all referenced media

!!! note "About the examples"
    Real courses are often in Persian/Arabic script. The examples below are simplified
    and translated to English to make the **shape** clear — the keys and structure are
    exactly what you'll see.

---

## Top-level shape

The root object always has these seven keys:

```json
{
  "course_id": "course.g_m2rgww-9cbd0a4d",
  "course_name": "Introduction to Measurement",
  "run": "2025",
  "course_meta": { "org": "sarvtlh", "course": "ED01", "url_name": "2025" },
  "about": { "...": "..." },
  "policies": { "...": "..." },
  "course": { "chapters": [ "..." ] }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `course_id` | string | Unique id for this extraction: `<tar-name>-<short-uuid>`. Also the name of the media folder. |
| `course_name` | string | Human-readable course title (from the policy `display_name`, falling back to the run XML, then `course_id`). |
| `run` | string \| null | The course run / `url_name` (e.g. `2025`). Identifies which policy folder and run XML were used. |
| `course_meta` | object | Identity attributes from `course.xml`. See below. |
| `about` | object | The course's marketing/landing fields. See below. |
| `policies` | object | The OLX policy JSON files, cleaned and normalized. See below. |
| `course` | object | The actual content tree: `{ "chapters": [...] }`. **This is the bulk of the data.** |

---

## `course_meta`

The identity triple from `course.xml` — useful for matching the course back to its
OpenEdX origin:

```json
{ "org": "sarvtlh", "course": "ED01", "url_name": "2025" }
```

- `org` — the organization that authored the course
- `course` — the course code
- `url_name` — the run (same value as the top-level `run`)

---

## `about`

Every populated `about/*.html` field, keyed by filename, with HTML stripped to plain
text. Empty fields are omitted. Common keys:

```json
{
  "overview": "This course introduces the fundamentals of measurement…",
  "short_description": "Learn what measurement really means.",
  "entrance_exam_minimum_score_pct": "50"
}
```

Which keys appear depends entirely on what the author filled in — treat this object as
open-ended.

---

## `policies`

Every `policies/**/*.json` file (except `assets.json`), keyed by filename stem. Typically
you'll see `policy` and `grading_policy`:

```json
{
  "policy": {
    "course/2025": {
      "display_name": "Introduction to Measurement",
      "start": "2025-01-01T00:00:00Z"
    }
  },
  "grading_policy": {
    "GRADER": [ { "type": "Final", "weight": 1.0 } ],
    "GRADE_CUTOFFS": { "Pass": 0.5 }
  }
}
```

Two transformations are applied to this object:

- **Persian keys are translated to English** where known (e.g. `عمومی` → `General`).
  Values are left as-is.
- **Course and asset references are expanded.** A `course-v1:org+course+run` string
  becomes a structured `{org, course, url_name}` object, and any `asset-v1:…` reference
  is replaced with a media path (`<course_id>/assets/<file>`) after the file is copied
  into the bundle.

!!! tip "Full breakdown"
    Policies carry the grading rules, certificates, **prerequisite courses**, tabs, and
    key dates. See the dedicated **[Policy Schema](policy.md)** page for a complete,
    field-by-field reference.

---

## The content tree (`course`)

`course.chapters` is an ordered list that mirrors the OpenEdX structure:

```
course
└── chapters[]        (top-level sections)
    └── sequentials[] (subsections)
        └── verticals[]  (units)
            └── content   (the actual components, keyed by position)
```

```json
{
  "course": {
    "chapters": [
      {
        "name": "Section 1: Measuring the World",
        "sequentials": [
          {
            "name": "Lesson 1",
            "verticals": [
              {
                "name": "Unit",
                "content": {
                  "1": { "paragraph": [ "…" ], "list": [ "…" ] },
                  "2": { "problem": [ "…" ] }
                }
              }
            ]
          }
        ]
      }
    ]
  }
}
```

- **chapter / sequential / vertical** each have a `name` (the display name, falling back
  to the internal `url_name`).
- A vertical's **`content`** is an object keyed by **position** (`"1"`, `"2"`, …),
  preserving authoring order. Each value is a single component, described next.

---

## Component types

Each entry in a vertical's `content` is one of the following. The **key** tells you the
component type (except for `html`, which is flattened into content keys like `paragraph`).

### HTML / text content

An `html` component is **not** wrapped under an `"html"` key — its blocks are grouped by
role directly into the content entry. Possible keys:

| Key | Type | Notes |
| --- | --- | --- |
| `paragraph` | list of strings | Body text. Newlines (from `<br>`) are preserved. |
| `header` | list of strings | Text from elements whose class contains `header`. |
| `list` | list | Either a list of strings, or `{paragraph, list}` when a paragraph introduces the list. |
| `table` | list of tables | Each table is `{header?, body}` (see below). |
| `image` | string or list | Media path(s) for inline `<img>` and CSS `url(...)` images. A single image is a string; multiple become a list. |
| `question` | list | Free-response items grouped as `{number?, question, answer}`. |

```json
{
  "header": [ "Part A: Properties you can measure" ],
  "paragraph": [
    "We measure things every day…",
    "Thought question:\nCan you measure 'beauty'? Why or why not?"
  ],
  "list": [
    {
      "paragraph": "Key concepts:",
      "list": [ "No measurement is perfectly exact.", "Sometimes an estimate is enough." ]
    }
  ]
}
```

**Tables** carry an optional header and a body of rows:

```json
{
  "table": [
    {
      "header": [ "Item", "Measurable properties", "Suggested unit" ],
      "body": [
        [ "Desk", "length, width, height", "cm or m" ],
        [ "Water bottle", "volume", "ml or l" ]
      ]
    }
  ]
}
```

### `problem` — graded questions

A list of question objects. Each question has a consistent schema:

```json
{
  "problem": [
    {
      "question": "Which unit is best for the length of a book?",
      "type": "multiplechoiceresponse",
      "kind": "single",
      "options": [
        { "text": "centimeters", "correct": true },
        { "text": "kilometers", "correct": false }
      ],
      "answer": [ "centimeters" ]
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `question` | The prompt text. |
| `type` | The raw OLX response tag. |
| `kind` | A friendlier label derived from `type` (see table). |
| `options` | Present for choice-style questions: `{text, correct}` per option. |
| `answer` | List of correct answers (option text, or the expected string/number). |

`type` → `kind` mapping:

| `type` (OLX tag) | `kind` | Question style |
| --- | --- | --- |
| `multiplechoiceresponse` | `single` | Pick one |
| `choiceresponse` | `multi` | Pick many (checkboxes) |
| `optionresponse` | `dropdown` | Dropdown select |
| `stringresponse` | `text` | Free text answer |
| `numericalresponse` | `numeric` | Numeric answer |

### `video`

```json
{
  "video": {
    "title": "What is measurement?",
    "video_url": "https://cdn.example.com/intro.mp4",
    "video_file": "course.g_m2rgww-9cbd0a4d/assets/intro.mp4",
    "youtube_id": "dQw4w9WgXcQ",
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "edx_video_id": "abc-123",
    "transcripts": { "en": "course.g_m2rgww-9cbd0a4d/assets/intro.en.srt" }
  }
}
```

- `video_file` is the **downloaded** copy inside the bundle (from the direct URL, or
  YouTube via `yt-dlp` when there's no direct source). It may be absent if the download
  failed.
- `transcripts` maps language code → media path; transcript files are renamed to pair
  with the video.
- Optional fields (`youtube_id`, `edx_video_id`, `transcripts`, …) appear only when present.

### `pdf`

```json
{
  "pdf": {
    "title": "Reference sheet",
    "url": "course.g_m2rgww-9cbd0a4d/assets/reference.pdf",
    "allow_download": true
  }
}
```

`url` is rewritten to the media path when the PDF is found under `static/`; otherwise the
original URL is kept.

### `drag-and-drop-v2`

The full decoded drag-and-drop definition: the element's prompt and limits merged with the
component's `data` JSON (`feedback`, `items`, `zones`, `targetImg`). The `targetImg` is
copied into the bundle and its path rewritten:

```json
{
  "drag-and-drop-v2": {
    "question_text": "Drag each tool to what it measures.",
    "mode": "standard",
    "max_attempts": "3",
    "targetImg": "course.g_m2rgww-9cbd0a4d/assets/board.png",
    "items": [ "…" ],
    "zones": [ "…" ]
  }
}
```

### `openassessment` (ORA)

An open-response/peer-graded assessment: the essay prompt(s), response settings, grading
steps, and rubric:

```json
{
  "openassessment": {
    "title": "Reflection essay",
    "question": "Describe a measurement you made and how you ensured accuracy.",
    "response": { "text": "required", "file_upload": "optional", "allowed_files": "pdf" },
    "graded_by": [ "peer-assessment", "self-assessment" ],
    "rubric": [
      {
        "criterion": "Clarity",
        "options": [
          { "points": 0, "explanation": "Unclear" },
          { "points": 2, "explanation": "Clear and complete" }
        ]
      }
    ]
  }
}
```

### `poll`

```json
{
  "poll": {
    "question": "How confident do you feel about units?",
    "options": [ "Not at all", "Somewhat", "Very" ],
    "feedback": "Thanks for sharing!"
  }
}
```

### `library_content`

Randomized library blocks aren't fully parsed yet. The value is a **review note**
pointing at the source file for a human to inspect — not real content.

### Anything else (fallback)

Unrecognized component tags are emitted as `{ "<tag>": "<display name>" }` so nothing is
silently dropped:

```json
{ "discussion": "Week 1 discussion" }
```

---

## Media & asset paths

Any value that points at a file uses a **relative media path** of the form:

```
<course_id>/assets/<filename>
```

These are relative to the service's media root (the same files are inside the `.zip` under
that path). Images, PDFs, downloaded videos, transcripts, and drag-and-drop target images
all follow this convention. References that couldn't be resolved to a real file are left as
their original string.

---

## Text normalization

All extracted text is cleaned so it's safe to display and compare:

- **Invisible junk removed** — zero-width spaces, joiners, BOM, and directional marks are
  stripped.
- **ZWNJ → space** — the zero-width non-joiner (common in Persian) becomes a normal space
  (e.g. `پیش‌دبستان` → `پیش دبستان`).
- **Whitespace collapsed** — runs of spaces/tabs collapse to one; in body text, `<br>`
  becomes a real newline and blank-line runs are trimmed.
- **Unicode preserved** — non-Latin text is kept as-is (the JSON is written with
  `ensure_ascii=False`), so Persian/Arabic content stays readable rather than escaped.