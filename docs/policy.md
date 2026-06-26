# Policy Schema

The `policies` object in the [JSON output](json-output.md) is the most information-dense
part of a course: it holds the grading rules, the certificate definition, prerequisites,
visibility, tabs, discussion settings, and the course's key dates. This page documents it
**completely**.

`policies` is keyed by the **filename stem** of each `policies/**/*.json` file (with
`assets.json` excluded, since that's only used internally to resolve assets). In practice
you'll always see two keys:

```json
{
  "policies": {
    "grading_policy": { "...": "..." },
    "policy": { "...": "..." }
  }
}
```

!!! info "Two transformations are applied to everything under `policies`"
    1. **Persian keys → English** where a mapping is known (e.g. `عمومی` → `General`).
       Values are never translated.
    2. **References are expanded.** Any `course-v1:org+course+run` string becomes a
       `{org, course, url_name}` object (this is what powers **prerequisite courses** —
       see below), and any `asset-v1:…` reference is replaced with a local media path
       after the file is copied into the bundle.

---

## `grading_policy`

Defines how the course is scored. Two keys: `GRADER` (the assignment buckets) and
`GRADE_CUTOFFS` (the pass thresholds).

```json
{
  "grading_policy": {
    "GRADER": [
      { "type": "تمرین",       "short_label": "تمرین",  "weight": 0.2, "min_count": 2, "drop_count": 0 },
      { "type": "آزمون پایانی", "short_label": "پایانی", "weight": 0.8, "min_count": 1, "drop_count": 0 }
    ],
    "GRADE_CUTOFFS": { "Pass": 0.6 }
  }
}
```

### `GRADER` — assignment buckets

Each object is one **assignment type** that contributes to the final grade. In the example
above the course is 20% homework (`تمرین`) + 80% final exam (`آزمون پایانی`).

| Field | Type | Meaning |
| --- | --- | --- |
| `type` | string | The assignment-type name. Problems are tied to a type via their subsection's `format`. |
| `short_label` | string | Abbreviated label shown next to grades in the UI. |
| `weight` | number | Fraction of the final grade this bucket is worth. **Weights across all buckets sum to `1.0`.** |
| `min_count` | integer | How many assignments of this type the grade is computed over (the expected total). |
| `drop_count` | integer | How many of the lowest scores in this bucket are dropped before averaging. |

### `GRADE_CUTOFFS` — pass thresholds

Maps a grade band to the **minimum fraction** (0–1) required to earn it. `{ "Pass": 0.6 }`
means a learner needs ≥ 60% overall to pass. Courses with letter grades may have several
bands (e.g. `{ "A": 0.9, "B": 0.8, "Pass": 0.6 }`).

---

## `policy`

The course's main configuration, keyed by `course/<run>` (e.g. `course/2025`). Everything
about how the course behaves lives in this one object.

```json
{
  "policy": {
    "course/2025": {
      "display_name": "Old Course",
      "start": "2025-01-01T00:00:00Z",
      "self_paced": false,
      "language": "en",
      "course_image": "Untitled.png",
      "catalog_visibility": "non",
      "advanced_modules": [ "survey" ],
      "minimum_grade_credit": 0.8,
      "enable_subsection_gating": true,
      "graceperiod": "",
      "cert_html_view_enabled": true,
      "certificates": { "...": "..." },
      "discussion_topics": { "General": { "id": "course" } },
      "discussions_settings": { "...": "..." },
      "instructor_info": { "instructors": [] },
      "learning_info": [],
      "tabs": [ "..." ]
    }
  }
}
```

### Core identity & scheduling

| Field | Meaning |
| --- | --- |
| `display_name` | The course title shown to learners. |
| `start` | Course start date (ISO 8601, UTC). Content/dates are computed relative to this. |
| `end`, `enrollment_start`, `enrollment_end` | Optional date bounds when present. |
| `self_paced` | `true` = learners progress at their own pace; `false` = instructor-paced with fixed dates. |
| `language` | Course language code (e.g. `en`, `fa`). |
| `course_image` | Filename of the course card image (resolved from `static/`). |

### Prerequisites — `pre_requisite_courses` ⭐

The **"pre course"** field. It lists other courses a learner must complete **before**
enrolling in this one. In the raw OLX it's a list of `course-v1:` course keys; the
extractor **expands each one** into the same structured shape as `course_meta`, so you can
match prerequisites to their origin without parsing strings yourself.

**Raw OLX:**

```json
"pre_requisite_courses": [ "course-v1:sarvtlh+ED00+2024" ]
```

**Extracted output:**

```json
"pre_requisite_courses": [
  { "org": "sarvtlh", "course": "ED00", "url_name": "2024" }
]
```

!!! tip "How to use it"
    Each entry's `{org, course, url_name}` matches the `course_meta` of the prerequisite
    course. To build a prerequisite graph across courses, link this course's
    `course_meta` to every object in its `pre_requisite_courses`.

This field is **optional** — it only appears when the author configured prerequisites, so
it isn't present in every course (including the bundled samples).

### Grading & gating

| Field | Meaning |
| --- | --- |
| `minimum_grade_credit` | Minimum overall grade (0–1) required to earn course **credit** (distinct from the `Pass` cutoff). |
| `enable_subsection_gating` | If `true`, some subsections are locked until prerequisite subsections are completed (prerequisite content *within* the course). |
| `graceperiod` | Extra time allowed after a due date before work counts as late. Empty string = none. |

### Certificates

`certificates.certificates` is a list of certificate templates. `cert_html_view_enabled`
toggles the web-based certificate view.

```json
"certificates": {
  "certificates": [
    {
      "id": 1737422897,
      "name": "Name of the certificate",
      "description": "Description of the certificate",
      "course_title": "",
      "is_active": true,
      "version": 1,
      "signatories": [
        {
          "id": 177403673,
          "name": "Ms. Pandi",
          "title": "Director",
          "organization": "Sarv",
          "signature_image_path": ""
        }
      ]
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `name` / `description` | Certificate title and description. |
| `course_title` | Overrides the course title on the certificate when set. |
| `is_active` | Whether this certificate is currently issued. |
| `signatories` | The people who "sign" the certificate — each with `name`, `title`, `organization`, and an optional `signature_image_path`. |

### Discussions

| Field | Meaning |
| --- | --- |
| `discussion_topics` | Named discussion topics, each with an `id` (e.g. a default `General` topic). |
| `discussions_settings.provider_type` | The discussion backend (e.g. `openedx`). |
| `discussions_settings.enable_in_context` | Whether in-context (unit-level) discussions are on. |
| `discussions_settings.enable_graded_units` | Whether discussions on graded units are enabled. |
| `discussions_settings.unit_level_visibility` | Whether discussions are shown per unit. |

### Visibility, modules & instructors

| Field | Meaning |
| --- | --- |
| `catalog_visibility` | Whether the course appears in the catalog/search (`both`, `about`, or `non`/none). |
| `advanced_modules` | Extra XBlock types enabled for the course (e.g. `survey`, `poll`). |
| `instructor_info.instructors` | Listed instructors (name, title, bio, image) — often empty. |
| `learning_info` | "What you'll learn" bullet points — often empty. |

### `tabs`

The ordered top navigation tabs of the course. Each entry:

```json
{ "name": "Progress", "type": "progress", "course_staff_only": false, "is_hidden": false }
```

| Field | Meaning |
| --- | --- |
| `name` | The tab label. |
| `type` | The tab kind: `courseware`, `progress`, `dates`, `discussion`, `wiki`, `textbooks`, … |
| `course_staff_only` | If `true`, only staff see the tab. |
| `is_hidden` | If `true`, the tab is hidden from the nav (present in the sample on the `wiki` tab). |

---

## Field availability

The `policy` object is **open-ended** — OpenEdX defines many optional settings and authors
only set what they need. Treat unknown keys gracefully and don't assume any optional field
(like `pre_requisite_courses`, `end`, or extra `GRADE_CUTOFFS` bands) is always present.
The fields documented above are the ones you'll encounter most often, with the bundled
samples confirming the common core.