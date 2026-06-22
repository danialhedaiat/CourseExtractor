"""Extract a single OLX course into a structured JSON + per-course media bundle.

Builds: course_name, about/, policies/ (assets.json excluded), the chapter ->
sequential -> vertical -> component tree, copies referenced assets (images, pdfs,
videos), and zips the result. Configured via core.settings.

Public entry point: extract_course(extracted_root, course_id) -> dict.
"""

import html
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from core.settings import settings

# Output root for per-course media bundles (== UPLOAD_DIR, default "media").
MEDIA_DIR = Path(settings.UPLOAD_DIR)


def youtube_quality() -> str:
    return settings.YOUTUBE_VIDEO_QUALITY


# Per-extraction progress reporting. Set by extract_course; extract_video bumps it
# after each video so a Celery task can stream "video i/N" to the result backend.
_progress: dict = {"cb": None, "total": 0, "done": 0}


def _init_progress(callback, total_videos: int) -> None:
    _progress.update({"cb": callback, "total": total_videos, "done": 0})


def _bump_video() -> None:
    _progress["done"] += 1
    if _progress["cb"]:
        _progress["cb"](_progress["done"], _progress["total"])


def count_videos(course_dir: Path) -> int:
    """Count <video> components across the course's verticals (for progress total)."""
    total = 0
    vdir = course_dir / "vertical"
    if vdir.is_dir():
        for f in vdir.glob("*.xml"):
            try:
                root = ET.parse(f).getroot()
            except ET.ParseError:
                continue
            total += sum(1 for c in root if isinstance(c.tag, str) and c.tag == "video")
    return total

# Invisible characters that are genuinely junk and safe to drop everywhere.
ZWNJ = "‌"  # U+200C zero-width non-joiner — replaced with a normal space (پیش‌دبستان -> پیش دبستان)
INVISIBLE_JUNK = "​‍‎‏﻿"  # ZWSP, ZWJ, LRM, RLM, BOM


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = text.translate({ord(c): None for c in INVISIBLE_JUNK})
    text = text.replace(ZWNJ, " ")  # ZWNJ -> space, per request
    text = re.sub(r"[ \t\r\n\f\v]+", " ", text)  # collapse whitespace
    return text.strip()


def strip_html(text: str) -> str:
    return clean(re.sub(r"<[^>]+>", " ", text or ""))


def get_course_name(course_dir: Path, run: str | None) -> str:
    if run:
        policy = course_dir / "policies" / run / "policy.json"
        if policy.exists():
            data = json.loads(policy.read_text(encoding="utf-8"))
            dn = clean(data.get(f"course/{run}", {}).get("display_name"))
            if dn:
                return dn
        run_xml = course_dir / f"{run}.xml"
        if run_xml.exists():
            dn = clean(ET.parse(run_xml).getroot().get("display_name"))
            if dn:
                return dn
    return ""


def get_course_meta(course_dir: Path) -> dict:
    """course.xml identity attributes: org, course (code), url_name (run)."""
    root_xml = course_dir / "course.xml"
    if not root_xml.exists():
        return {}
    try:
        attrib = ET.parse(root_xml).getroot().attrib
    except ET.ParseError:
        return {}
    return {
        "org": attrib.get("org"),
        "course": attrib.get("course"),
        "url_name": attrib.get("url_name"),
    }


def get_run(course_dir: Path) -> str | None:
    root_xml = course_dir / "course.xml"
    if root_xml.exists():
        try:
            return ET.parse(root_xml).getroot().get("url_name")
        except ET.ParseError:
            return None
    return None


# Persian keys found inside policy files -> English. Extend as new ones appear.
PERSIAN_KEY_MAP = {
    "عمومی": "General",
}


def translate_keys(obj):
    """Recursively rename any Persian dict keys to their English equivalent.

    Values are left untouched (names like حمیدرضا عبدالمحمدی stay Persian); only
    keys are translated. json.load already decoded \\uXXXX escapes to real Persian
    characters, and we write the result with ensure_ascii=False.
    """
    if isinstance(obj, dict):
        return {PERSIAN_KEY_MAP.get(k, k): translate_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [translate_keys(x) for x in obj]
    return obj


def extract_policies(course_dir: Path) -> dict:
    """Every policies/*.json except assets.json, keyed by filename (run folder flattened)."""
    policies: dict = {}
    pol_dir = course_dir / "policies"
    if not pol_dir.is_dir():
        return policies
    for f in sorted(pol_dir.rglob("*.json")):
        if f.name == "assets.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        policies[f.stem] = translate_keys(data)
    return policies


def load_assets(course_dir: Path) -> dict:
    """assets.json maps asset block-name -> metadata (incl. real displayname filename)."""
    f = course_dir / "policies" / "assets.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def asset_block_name(ref: str) -> str:
    """Pull the assets.json key out of an asset reference path.

    Handles both encodings seen in policies:
      '/asset-v1:org+course+run+type@asset+block@EMZA__1_.png'  -> 'EMZA__1_.png'
      'asset-v1_org_course_run_type_asset_block_Untitled.png'   -> 'Untitled.png'
    """
    if "block@" in ref:
        return ref.split("block@")[-1]
    if "_block_" in ref:
        return ref.split("_block_")[-1]
    return ref.lstrip("/").split("/")[-1]


def resolve_physical_name(ref: str, assets: dict) -> str | None:
    """Resolve an asset reference to the physical filename stored under static/.

    Tries, in order: the full ref as a direct assets.json key (course_image style),
    the parsed block-name as a key (signature style), then a match on the entry's
    filename field. Returns the entry's displayname (the actual static/ filename).
    """
    for cand in (ref.lstrip("/"), ref, asset_block_name(ref)):
        entry = assets.get(cand)
        if isinstance(entry, dict):
            return entry.get("displayname") or cand
    for k, v in assets.items():
        if isinstance(v, dict) and v.get("filename", "").lstrip("/") == ref.lstrip("/"):
            return v.get("displayname") or k
    return None


COURSE_REF_RE = re.compile(r"^course-v1:", re.I)


def parse_course_ref(ref: str) -> dict:
    """Expand 'course-v1:org+course+run' into a structured dict matching course_meta."""
    body = ref.split(":", 1)[1] if ":" in ref else ref
    parts = body.split("+")
    return {
        "org": parts[0] if len(parts) > 0 else None,
        "course": parts[1] if len(parts) > 1 else None,
        "url_name": parts[2] if len(parts) > 2 else None,
    }


def expand_course_refs(obj):
    """Recursively replace any 'course-v1:...' string with its parsed dict."""
    if isinstance(obj, dict):
        return {k: expand_course_refs(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_course_refs(x) for x in obj]
    if isinstance(obj, str) and COURSE_REF_RE.match(obj):
        return parse_course_ref(obj)
    return obj


ASSET_REF_RE = re.compile(r"asset-v1", re.I)


def rewrite_asset_refs(obj, course_dir: Path, assets: dict, assets_out: Path,
                       course_id: str, copied: set, unresolved: list):
    """Recursively rewrite any asset-reference string value in obj.

    For each value containing 'asset-v1', resolve it to the physical static file,
    copy that file into the media assets dir, and replace the value with the new
    media/<course>/assets/<file> path. Unresolvable refs are left unchanged.
    """
    if isinstance(obj, dict):
        return {k: rewrite_asset_refs(v, course_dir, assets, assets_out, course_id, copied, unresolved)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [rewrite_asset_refs(x, course_dir, assets, assets_out, course_id, copied, unresolved)
                for x in obj]
    if isinstance(obj, str) and ASSET_REF_RE.search(obj):
        phys = resolve_physical_name(obj, assets)
        static_dir = course_dir / "static"
        if phys and (static_dir / phys).exists():
            assets_out.mkdir(parents=True, exist_ok=True)
            shutil.copy2(static_dir / phys, assets_out / phys)
            copied.add(phys)
            return f"{course_id}/assets/{phys}"
        unresolved.append(obj)
    return obj


def element_name(category_dir: Path, url_name: str) -> str:
    """display_name of category/<url_name>.xml, falling back to the url_name."""
    f = category_dir / f"{url_name}.xml"
    if f.exists():
        try:
            dn = clean(ET.parse(f).getroot().get("display_name"))
            if dn:
                return dn
        except ET.ParseError:
            pass
    return url_name


def clean_block(text: str) -> str:
    """Clean inline whitespace but PRESERVE newlines (from <br>). ZWNJ -> space."""
    text = text.translate({ord(c): None for c in INVISIBLE_JUNK})
    text = text.replace(ZWNJ, " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


# Block-level tags whose text becomes one paragraph/header entry.
_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li",
               "section", "article", "blockquote", "td", "th", "ul", "ol"}


def block_key(cls: str) -> str | None:
    """Map an element's class to its content role, or None to drop it.

    Drops buttons/submit controls and the bare 'پاسخ:' answer title; recognises
    free-response question blocks (question number / text) and their answer.
    """
    c = cls.lower()
    if "btn" in c or "submit" in c:
        return None
    if "correct-answer-title" in c:  # the "پاسخ:" label — not needed
        return None
    if "correct-answer-text" in c:   # the actual answer
        return "answer"
    if "question-text" in c:
        return "question"
    if "question-icon" in c:         # the question number
        return "number"
    if "header" in c:
        return "header"
    return "paragraph"


_TABLE_TAGS = {"table", "tr", "td", "th"}


class _HtmlBlocks(HTMLParser):
    """Extract ordered content blocks: {paragraph|header: text}, {list: [...]},
    {image: media_path} for inline <img>, and {table: [[cell, ...], ...]}.

    Rule: an element whose class contains 'header' -> 'header'; other blocks ->
    'paragraph'. <br> -> newline. Inline <img src=/static/..> are copied to media.
    """

    def __init__(self, course_dir: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.course_dir = course_dir
        self.stack: list[dict] = []
        self.out: list[dict] = []

    def _in_cell(self) -> bool:
        return any(fr["tag"] in ("td", "th") for fr in self.stack)

    def _new_frame(self, tag, attrs):
        cls = dict(attrs).get("class", "") or ""
        return {"tag": tag, "cls": cls, "parts": [], "child": False,
                "items": [], "rows": [], "cells": [],
                "header_rows": [], "is_header": False}

    def _handle_img(self, attrs):
        src = dict(attrs).get("src", "") or ""
        if "static/" in src:
            media_path = copy_content_asset(self.course_dir, src)
            if media_path:
                self.out.append({"image": media_path})

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            if self.stack:
                self.stack[-1]["parts"].append("\n")
            return
        if tag == "img":
            self._handle_img(attrs)
            return
        if tag in _TABLE_TAGS:
            self.stack.append(self._new_frame(tag, attrs))
            return
        if tag in _BLOCK_TAGS:
            if self._in_cell():
                return  # inner block inside a table cell: text flows into the cell
            self.stack.append(self._new_frame(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.stack:
            self.stack[-1]["parts"].append("\n")
        elif tag == "img":
            self._handle_img(attrs)

    def handle_data(self, data):
        if self.stack and data.strip():
            self.stack[-1]["parts"].append(data)

    def handle_endtag(self, tag):
        if not self.stack:
            return

        if tag in ("td", "th"):
            frame = self.stack.pop()
            if self.stack and self.stack[-1]["tag"] == "tr":
                self.stack[-1]["cells"].append(clean_block("".join(frame["parts"])))
                if tag == "th":  # a <th> marks this row as a header row
                    self.stack[-1]["is_header"] = True
            return
        if tag == "tr":
            frame = self.stack.pop()
            if frame["cells"] and self.stack and self.stack[-1]["tag"] == "table":
                bucket = "header_rows" if frame["is_header"] else "rows"
                self.stack[-1][bucket].append(frame["cells"])
            return
        if tag == "table":
            frame = self.stack.pop()
            all_cells = [c for row in frame["header_rows"] + frame["rows"] for c in row]
            # Skip layout/empty tables that have no actual cell text.
            if any(c.strip() for c in all_cells):
                table: dict = {}
                hdr = frame["header_rows"]
                if hdr:
                    table["header"] = hdr[0] if len(hdr) == 1 else hdr
                table["body"] = frame["rows"]
                self.out.append({"table": table})
            if self.stack:
                self.stack[-1]["child"] = True
            return

        if tag not in _BLOCK_TAGS:
            return
        # Inner block inside a table cell wasn't pushed — nothing to pop.
        if self._in_cell():
            return

        frame = self.stack.pop()
        text = clean_block("".join(frame["parts"]))

        if frame["tag"] in ("ul", "ol"):
            if frame["items"]:
                self.out.append({"list": frame["items"]})
            if self.stack:
                self.stack[-1]["child"] = True
            return

        if frame["tag"] == "li" and self.stack and self.stack[-1]["tag"] in ("ul", "ol"):
            if text:
                self.stack[-1]["items"].append(text)
            return

        if text and not frame["child"]:
            key = block_key(frame["cls"])
            if key is not None:
                self.out.append({key: text})
        if self.stack:
            self.stack[-1]["child"] = True


def copy_content_asset(course_dir: Path, ref: str) -> str | None:
    """Copy a /static/<file> asset into the course media dir; return its media path."""
    name = ref.split("/static/")[-1] if "/static/" in ref else ref.lstrip("/")
    name = name.split("?")[0].split("#")[0]  # drop any query/fragment
    src = course_dir / "static" / name
    if not src.exists():
        return None
    course_id = course_dir.parent.name
    out = MEDIA_DIR / course_id / "assets"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out / name)
    return f"{course_id}/assets/{name}"


_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", re.I)


def css_static_assets(raw_html: str, course_dir: Path) -> list[dict]:
    """Find /static/ url() refs in <style> blocks, copy them, return {image: path}."""
    refs: list[str] = []
    seen: set[str] = set()
    for style in re.findall(r"<style.*?</style>", raw_html, flags=re.S):
        for m in _CSS_URL_RE.finditer(style):
            ref = m.group(1).strip()
            if "static/" in ref.lower() and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    entries: list[dict] = []
    for ref in refs:
        media_path = copy_content_asset(course_dir, ref)
        if media_path:
            entries.append({"image": media_path})
    return entries


def html_content_file(course_dir: Path, url_name: str) -> Path:
    """Resolve html/<url_name>.xml pointer (filename attr) to its .html file."""
    html_dir = course_dir / "html"
    filename = url_name
    pointer = html_dir / f"{url_name}.xml"
    if pointer.exists():
        try:
            filename = ET.parse(pointer).getroot().get("filename") or url_name
        except ET.ParseError:
            filename = url_name
    return html_dir / f"{filename}.html"


def group_free_response(blocks: list[dict]) -> list[dict]:
    """Merge consecutive number/question/answer blocks into one entry, e.g.
    {"number": "۲", "question": "…", "answer": "…"}. paragraph/header pass through."""
    out: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if cur:
            out.append(cur)
            cur = None

    for b in blocks:
        key = next(iter(b))
        val = b[key]
        if key == "number":
            flush()
            cur = {"number": val}
        elif key == "question":
            if cur is not None and "question" in cur:
                flush()
            if cur is None:
                cur = {}
            cur["question"] = val
        elif key == "answer":
            if cur is None:
                cur = {}
            cur["answer"] = val
            flush()
        else:  # paragraph / header — standalone
            flush()
            out.append(b)
    flush()
    return out


def attach_list_intro(blocks: list[dict]) -> list[dict]:
    """When a {list: [...]} is immediately preceded by a plain {paragraph: ...},
    merge them into {paragraph: ..., list: [...]} (the paragraph introduces the list).
    Lists preceded by anything else stay standalone."""
    out: list[dict] = []
    for b in blocks:
        if set(b) == {"list"} and out and set(out[-1]) == {"paragraph"}:
            intro = out.pop()
            out.append({"paragraph": intro["paragraph"], "list": b["list"]})
        else:
            out.append(b)
    return out


def html_blocks(course_dir: Path, url_name: str) -> list[dict]:
    """Return the ordered content blocks of an html component (paragraph/header,
    lists with optional intro, and grouped number/question/answer items)."""
    content_file = html_content_file(course_dir, url_name)
    if not content_file.exists():
        return []
    raw = content_file.read_text(encoding="utf-8", errors="ignore")
    images = css_static_assets(raw, course_dir)  # before stripping <style>
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S)
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.S)
    parser = _HtmlBlocks(course_dir)
    parser.feed(raw)
    return images + group_free_response(attach_list_intro(parser.out))


RESPONSE_TAGS = {
    "multiplechoiceresponse": "single",
    "choiceresponse": "multi",
    "optionresponse": "dropdown",
    "stringresponse": "text",
    "numericalresponse": "numeric",
}


# Containers that hold the answer options — their text is NOT the question.
ANSWER_CONTAINERS = {"choicegroup", "checkboxgroup", "optioninput", "choice", "option"}


def question_text_of(resp) -> str:
    """Text inside a response that forms the question (excludes answer options)."""
    parts: list[str] = []

    def walk(el):
        for c in el:
            if not isinstance(c.tag, str):
                continue
            if c.tag in ANSWER_CONTAINERS or c.tag in ("style", "script"):
                if c.tail and c.tail.strip():
                    parts.append(c.tail)
                continue
            if c.text and c.text.strip():
                parts.append(c.text)
            walk(c)
            if c.tail and c.tail.strip():
                parts.append(c.tail)

    if resp.text and resp.text.strip():
        parts.append(resp.text)
    walk(resp)
    return clean(" ".join(parts))


def build_question(resp, question_text: str) -> dict:
    """Turn one response element into {question, type, kind, options, answer}."""
    kind = RESPONSE_TAGS[resp.tag]
    options: list[dict] = []
    answer: list[str] = []
    for el in resp.iter():
        if el.tag in ("choice", "option"):
            txt = clean("".join(el.itertext()))
            is_correct = el.get("correct", "").lower() == "true"
            options.append({"text": txt, "correct": is_correct})
            if is_correct:
                answer.append(txt)
    if resp.tag in ("stringresponse", "numericalresponse"):
        if resp.get("answer"):
            answer.append(clean(resp.get("answer")))
        for add in resp.iter("additional_answer"):
            if add.get("answer"):
                answer.append(clean(add.get("answer")))
    q: dict = {"question": question_text, "type": resp.tag, "kind": kind}
    if options:
        q["options"] = options
    q["answer"] = answer
    return q


def extract_problem(course_dir: Path, url_name: str) -> list[dict]:
    """Parse a problem file into a list of questions, pairing each response with
    the HTML text that precedes it (document order)."""
    pfile = course_dir / "problem" / f"{url_name}.xml"
    if not pfile.exists():
        return []
    try:
        root = ET.parse(pfile).getroot()
    except ET.ParseError:
        return []

    questions: list[dict] = []
    buf: list[str] = []

    def walk(el):
        for child in el:
            if not isinstance(child.tag, str):
                continue
            if child.tag in RESPONSE_TAGS:
                # Prefer the question text inside the response; fall back to any
                # HTML text that preceded it in document order.
                q = question_text_of(child) or clean(" ".join(buf))
                questions.append(build_question(child, q))
                buf.clear()
                continue
            if child.tag in ("style", "script"):
                if child.tail and child.tail.strip():
                    buf.append(child.tail)
                continue
            if child.text and child.text.strip():
                buf.append(child.text)
            walk(child)
            if child.tail and child.tail.strip():
                buf.append(child.tail)

    if root.text and root.text.strip():
        buf.append(root.text)
    walk(root)
    return questions


def group_html_blocks(blocks: list[dict]) -> dict:
    """Collapse an html component's blocks into one readable dict grouped by type,
    e.g. {"image": "…", "paragraph": ["…", "…"], "header": ["…"], "list": [[…]]}.
    'image' is a single string (or list if several); other types are lists."""
    grouped: dict[str, list] = {}
    for b in blocks:
        if set(b) == {"image"}:
            name, val = "image", b["image"]
        elif "table" in b:
            name, val = "table", b["table"]
        elif "question" in b:        # free-response {number, question, answer}
            name, val = "question", b
        elif "list" in b:            # {list:[...]} or {paragraph, list:[...]}
            name, val = "list", (b if len(b) > 1 else b["list"])
        elif "header" in b:
            name, val = "header", b["header"]
        else:
            name, val = "paragraph", b.get("paragraph", next(iter(b.values())))
        grouped.setdefault(name, []).append(val)

    out: dict = {}
    for name, vals in grouped.items():
        out[name] = vals[0] if name == "image" and len(vals) == 1 else vals
    return out


def _clean_deep(obj):
    """Recursively apply clean() (ZWNJ->space) to every string in a structure."""
    if isinstance(obj, dict):
        return {k: _clean_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_deep(x) for x in obj]
    if isinstance(obj, str):
        return clean(obj)
    return obj


def extract_drag_and_drop(el, course_dir: Path) -> dict:
    """Parse a drag-and-drop-v2 inline component into its full structure:
    the element's question_text/mode/limits plus the decoded `data` JSON
    (feedback, items, zones, targetImg). The targetImg is copied into the
    course media dir and its path rewritten; all text is ZWNJ-normalised."""
    data = el.get("data")
    if not data:
        return {}
    try:
        d = json.loads(data)
    except json.JSONDecodeError:
        return {}

    d = _clean_deep(d)

    # Copy the target image into media/assets and rewrite its path (as before).
    target = d.get("targetImg")
    if target:
        media_path = copy_content_asset(course_dir, target)
        if media_path:
            d["targetImg"] = media_path

    return {
        "question_text": clean(el.get("question_text")),
        "mode": el.get("mode"),
        "max_attempts": el.get("max_attempts"),
        "max_items_per_zone": el.get("max_items_per_zone"),
        **d,
    }


def oa_html_text(raw: str) -> str:
    """Decode HTML entities (e.g. &zwnj;), strip tags, ZWNJ->space, collapse."""
    if not raw:
        return ""
    return clean(re.sub(r"<[^>]+>", " ", html.unescape(raw)))


def extract_openassessment(el) -> dict:
    """Parse an inline <openassessment> (ORA) into its essay prompt, response
    settings, grading steps, and rubric criteria/options."""
    out: dict = {}

    title = el.find("title")
    t = clean("".join(title.itertext())) if title is not None else ""
    if t:
        out["title"] = t

    prompts = []
    for pr in el.iter("prompt"):
        desc = pr.find("description")
        txt = oa_html_text("".join(desc.itertext())) if desc is not None else ""
        if txt:
            prompts.append(txt)
    out["question"] = prompts[0] if len(prompts) == 1 else prompts

    out["response"] = {
        "text": el.get("text_response"),
        "file_upload": el.get("file_upload_response"),
        "allowed_files": el.get("white_listed_file_types"),
    }
    out["graded_by"] = [a.get("name") for a in el.iter("assessment")]

    rubric = []
    rub = el.find("rubric")
    if rub is not None:
        for crit in rub.iter("criterion"):
            cprompt = crit.find("prompt")
            criterion = oa_html_text("".join(cprompt.itertext())) if cprompt is not None else ""
            options = []
            for opt in crit.iter("option"):
                pts = opt.get("points")
                o: dict = {"points": int(pts) if pts and pts.lstrip("-").isdigit() else pts}
                oexp = opt.find("explanation")
                exp = oa_html_text("".join(oexp.itertext())) if oexp is not None else ""
                if exp:
                    o["explanation"] = exp
                options.append(o)
            rubric.append({"criterion": criterion, "options": options})
    if rubric:
        out["rubric"] = rubric
    return out


def copy_static_as(course_dir: Path, ref: str, dest_name: str) -> str | None:
    """Copy a static/<file> asset into media/assets under a chosen name."""
    name = ref.split("/static/")[-1] if "/static/" in ref else ref.lstrip("/")
    name = name.split("?")[0].split("#")[0]
    src = course_dir / "static" / name
    if not src.exists():
        return None
    course_id = course_dir.parent.name
    out_dir = MEDIA_DIR / course_id / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, out_dir / dest_name)
    return f"{course_id}/assets/{dest_name}"


def download_video(url: str, course_dir: Path) -> str | None:
    """Download a video URL into the course media/assets dir; return its media
    path, or None if the download fails. Cached: skips if already present."""
    import urllib.error
    import urllib.request
    from urllib.parse import unquote, urlparse

    name = unquote(urlparse(url).path.split("/")[-1]) or "video.mp4"
    course_id = course_dir.parent.name
    out_dir = MEDIA_DIR / course_id / "assets"
    dest = out_dir / name
    rel = f"{course_id}/assets/{name}"
    if dest.exists() and dest.stat().st_size > 0:
        return rel
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        return rel
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"  video download failed ({url[:60]}…): {exc}")
        dest.unlink(missing_ok=True)
        return None


def find_ffmpeg() -> str | None:
    """Return the directory containing ffmpeg, from PATH or a winget install."""
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if base.exists():
        for exe in base.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
            return str(exe.parent)
    return None


def download_youtube(youtube_id: str, course_dir: Path) -> str | None:
    """Download a YouTube video (<= YOUTUBE_VIDEO_QUALITY height) via yt-dlp into
    media/assets; return its media path, or None if it fails. Cached by id.
    Uses ffmpeg to merge the best video+audio streams (needed for 720p+)."""
    course_id = course_dir.parent.name
    out_dir = MEDIA_DIR / course_id / "assets"
    existing = [p for p in out_dir.glob(f"{youtube_id}.*")
                if p.suffix.lower() in (".mp4", ".webm", ".mkv")]
    if existing:
        return f"{course_id}/assets/{existing[0].name}"

    out_dir.mkdir(parents=True, exist_ok=True)
    q = youtube_quality()
    # Prefer m4a (aac) audio for mp4 compatibility; fall back to any audio, then
    # to a single progressive stream if merging isn't possible.
    fmt = (f"bestvideo[height<={q}]+bestaudio[ext=m4a]/"
           f"bestvideo[height<={q}]+bestaudio/best[height<={q}]/best")
    ytdlp = Path(sys.executable).parent / "yt-dlp.exe"
    cmd = [str(ytdlp), "-f", fmt, "--merge-output-format", "mp4",
           "--no-playlist", "--no-warnings",
           "-o", str(out_dir / f"{youtube_id}.%(ext)s"),
           f"https://www.youtube.com/watch?v={youtube_id}"]
    ffmpeg_dir = find_ffmpeg()
    if ffmpeg_dir:
        cmd += ["--ffmpeg-location", ffmpeg_dir]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"  youtube download failed ({youtube_id}): {exc}")
        return None
    files = [p for p in out_dir.glob(f"{youtube_id}.*")
             if p.suffix.lower() in (".mp4", ".webm", ".mkv")]
    return f"{course_id}/assets/{files[0].name}" if files else None


def extract_video(el, course_dir: Path) -> dict:
    """Parse a <video> component: title, source video_url (downloaded into
    assets), youtube id, edx id, and transcript files (copied)."""
    # The vertical holds a pointer <video url_name=..>; the real element with
    # sources lives in video/<url_name>.xml.
    url = el.get("url_name")
    if url:
        vfile = course_dir / "video" / f"{url}.xml"
        if vfile.exists():
            try:
                el = ET.parse(vfile).getroot()
            except ET.ParseError:
                pass

    urls: list[str] = []
    try:
        urls += [u for u in json.loads(el.get("html5_sources") or "[]") if u]
    except json.JSONDecodeError:
        pass
    for s in el.iter("source"):
        if s.get("src"):
            urls.append(s.get("src"))
    video_url = next((u for u in urls if u.startswith("http")), None)

    out: dict = {"title": clean(el.get("display_name")) or None}
    if video_url:
        out["video_url"] = video_url
        out["video_file"] = download_video(video_url, course_dir)

    # YouTube id: modern @youtube_id_1_0, or legacy @youtube="1.00:ID,0.75:ID2,..".
    yt = el.get("youtube_id_1_0")
    if not yt and el.get("youtube"):
        yt_map = {}
        for part in el.get("youtube").split(","):
            if ":" in part:
                speed, vid = part.split(":", 1)
                yt_map[speed.strip()] = vid.strip()
        yt = yt_map.get("1.00") or yt_map.get("1.0") or next(iter(yt_map.values()), None)
    if yt:
        out["youtube_id"] = yt
        out["youtube_url"] = f"https://www.youtube.com/watch?v={yt}"
        if "video_file" not in out:  # no direct mp4 — try downloading from YouTube
            out["video_file"] = download_youtube(yt, course_dir)

    if el.get("edx_video_id"):
        out["edx_video_id"] = el.get("edx_video_id")

    # Base the transcript filename on the video's name so they pair up cleanly
    # (instead of the original hash names), e.g. "<video>.srt" / "<video>.en.srt".
    from urllib.parse import unquote, urlparse
    if out.get("video_file"):
        base = Path(out["video_file"]).stem
    elif video_url:
        base = Path(unquote(urlparse(video_url).path.split("/")[-1])).stem
    else:
        base = el.get("edx_video_id") or url or "video"

    trans = [(tr.get("language") or tr.get("language_code") or "und", tr.get("src"))
             for tr in el.iter("transcript") if tr.get("src")]
    transcripts: dict = {}
    for lang, src in trans:
        dest = f"{base}.srt" if len(trans) == 1 else f"{base}.{lang}.srt"
        mp = copy_static_as(course_dir, src, dest)
        if mp:
            transcripts[lang] = mp
    if transcripts:
        out["transcripts"] = transcripts
    _bump_video()
    return out


def extract_poll(el) -> dict:
    """Parse an inline <poll> survey: question + option labels."""
    out: dict = {"question": clean(el.get("question"))}
    try:
        answers = json.loads(el.get("answers") or "[]")
    except json.JSONDecodeError:
        answers = []
    options = [clean(a[1].get("label")) for a in answers
              if len(a) > 1 and isinstance(a[1], dict) and a[1].get("label")]
    if options:
        out["options"] = options
    if clean(el.get("feedback")):
        out["feedback"] = clean(el.get("feedback"))
    return out


def extract_library_content(el, course_dir: Path) -> str:
    """library_content is a pointer to library_content/<url_name>.xml. We don't
    have a real extractor for it (and the sample is empty), so emit a review note
    pointing at the source file for a human to inspect."""
    url = el.get("url_name")
    src = course_dir / "library_content" / f"{url}.xml"
    rel = str(src).replace("\\", "/")
    return (f"check this path {rel} and search for library_content; if you don't "
            f"get anything from that leave it, but if you understand something "
            f"tell us danialhedaiat@gmail.com")


def extract_pdf(el, course_dir: Path) -> dict:
    """Parse an inline <pdf> component: copy its static PDF into media and
    return {title, url, allow_download}."""
    out: dict = {"title": clean(el.get("display_name")) or None}
    url = el.get("url")
    if url:
        out["url"] = copy_content_asset(course_dir, url) or url
    else:
        out["url"] = None
    if el.get("source_url"):
        out["source_url"] = el.get("source_url")
    out["allow_download"] = el.get("allow_download") == "true"
    return out


def extract_vertical(course_dir: Path, v_url: str) -> dict:
    """A vertical -> {name, content} where content is an ordered dict of its
    components keyed by position: {"1": {type: value}, "2": {...}, ...}."""
    vfile = course_dir / "vertical" / f"{v_url}.xml"
    content: dict[str, dict] = {}
    name = v_url
    if vfile.exists():
        try:
            root = ET.parse(vfile).getroot()
        except ET.ParseError:
            root = None
        if root is not None:
            name = clean(root.get("display_name")) or v_url
            n = 0  # one entry per component
            for child in root:
                if not isinstance(child.tag, str):
                    continue
                tag = child.tag
                url = child.get("url_name")
                n += 1
                if tag == "html" and url:
                    content[str(n)] = group_html_blocks(html_blocks(course_dir, url))
                elif tag == "problem" and url:
                    content[str(n)] = {"problem": extract_problem(course_dir, url)}
                elif tag == "drag-and-drop-v2":
                    content[str(n)] = {tag: extract_drag_and_drop(child, course_dir)}
                elif tag == "openassessment":
                    content[str(n)] = {tag: extract_openassessment(child)}
                elif tag == "pdf":
                    content[str(n)] = {tag: extract_pdf(child, course_dir)}
                elif tag == "video":
                    content[str(n)] = {tag: extract_video(child, course_dir)}
                elif tag == "library_content":
                    content[str(n)] = {tag: extract_library_content(child, course_dir)}
                elif tag == "poll":
                    content[str(n)] = {tag: extract_poll(child)}
                else:
                    label = element_name(course_dir / tag, url) if url else clean(child.get("display_name"))
                    content[str(n)] = {tag: label}
    return {"name": name, "content": content}


def extract_verticals(course_dir: Path, sq_url: str) -> list[dict]:
    sqfile = course_dir / "sequential" / f"{sq_url}.xml"
    verticals: list[dict] = []
    if not sqfile.exists():
        return verticals
    try:
        root = ET.parse(sqfile).getroot()
    except ET.ParseError:
        return verticals
    for v in root.findall("vertical"):
        v_url = v.get("url_name")
        if v_url:
            verticals.append(extract_vertical(course_dir, v_url))
    return verticals


def extract_structure(course_dir: Path, run: str | None) -> dict:
    """Walk course -> chapters -> sequentials -> verticals -> components."""
    chapters: list[dict] = []
    if not run:
        return {"chapters": chapters}
    run_xml = course_dir / "course" / f"{run}.xml"
    if not run_xml.exists():
        return {"chapters": chapters}
    try:
        root = ET.parse(run_xml).getroot()
    except ET.ParseError:
        return {"chapters": chapters}

    for ch in root.findall("chapter"):
        ch_url = ch.get("url_name")
        if not ch_url:
            continue
        ch_file = course_dir / "chapter" / f"{ch_url}.xml"
        sequentials: list[dict] = []
        if ch_file.exists():
            try:
                ch_root = ET.parse(ch_file).getroot()
            except ET.ParseError:
                ch_root = None
            if ch_root is not None:
                for sq in ch_root.findall("sequential"):
                    sq_url = sq.get("url_name")
                    if not sq_url:
                        continue
                    sequentials.append({
                        "name": element_name(course_dir / "sequential", sq_url),
                        "verticals": extract_verticals(course_dir, sq_url),
                    })
        chapters.append({
            "name": element_name(course_dir / "chapter", ch_url),
            "sequentials": sequentials,
        })
    return {"chapters": chapters}


def extract_about(course_dir: Path) -> dict:
    """Read every about/*.html field; key = field name, value = cleaned text."""
    about: dict[str, str] = {}
    about_dir = course_dir / "about"
    if not about_dir.is_dir():
        return about
    for f in sorted(about_dir.glob("*.html")):
        field = f.stem
        text = strip_html(f.read_text(encoding="utf-8", errors="ignore"))
        if text:  # only keep populated fields
            about[field] = text
    return about


def extract_course(extracted_root: Path, course_id: str, progress=None) -> dict:
    """Extract one OLX course and bundle it under MEDIA_DIR/<course_id>/.

    `extracted_root` is the unpacked course folder (it must contain `course/` with
    course.xml) and `extracted_root.name` must equal `course_id` so the asset-copy
    helpers route into MEDIA_DIR/<course_id>/assets. `progress` is an optional
    callback(done, total) invoked after each video download.

    Returns {course_id, course_name, json_path, zip_path}.
    """
    course_dir = extracted_root / "course"
    if not course_dir.is_dir():
        raise FileNotFoundError(f"OLX course folder not found: {course_dir}")

    _init_progress(progress, count_videos(course_dir))
    run = get_run(course_dir)
    data = {
        "course_id": course_id,
        "course_name": get_course_name(course_dir, run),
        "run": run,
        "course_meta": get_course_meta(course_dir),
        "about": extract_about(course_dir),
        "policies": extract_policies(course_dir),
        "course": extract_structure(course_dir, run),
    }

    # Per-course media dir: MEDIA_DIR/<course_id>/ with an assets/ subdir.
    course_media = MEDIA_DIR / course_id
    assets_out = course_media / "assets"
    assets = load_assets(course_dir)
    copied: set[str] = set()
    unresolved: list[str] = []
    data["policies"] = rewrite_asset_refs(
        data["policies"], course_dir, assets, assets_out, course_id, copied, unresolved
    )
    data["policies"] = expand_course_refs(data["policies"])

    course_media.mkdir(parents=True, exist_ok=True)
    json_path = course_media / f"extracted_{course_id}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Bundle the course folder (json + assets) into a zip inside the course dir.
    zip_path = course_media / f"{course_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(course_media.rglob("*")):
            if p.is_file() and p != zip_path:
                zf.write(p, p.relative_to(MEDIA_DIR))

    return {
        "course_id": course_id,
        "course_name": data["course_name"],
        "json_path": str(json_path),
        "zip_path": str(zip_path),
    }