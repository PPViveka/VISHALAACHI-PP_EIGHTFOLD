"""
project.py
----------
Stage 6 (project-to-output). Takes one canonical candidate record
(internal, full-fidelity) and a runtime config, and produces the
requested *projection* of it. The canonical record itself is never
mutated -- this keeps "what we know" cleanly separated from "what we
chose to show."

Config shape (see assignment spec / config/*.json for examples):
{
  "fields": [
    { "path": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string" },
    { "path": "phone", "from": "phones[0]", "normalize": "E164" },
    { "path": "skills", "from": "skills[].name", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": true,
  "on_missing": "null"   # "null" | "omit" | "error"
}

If no config is given, the default schema (every canonical field,
1:1, confidence+provenance included) is emitted.
"""

import re

from .normalize import normalize_phone, normalize_skill


class MissingRequiredFieldError(Exception):
    pass


def _get_path(record, path):
    """Resolve a dotted/bracketed path like 'skills[].name' or
    'emails[0]' or 'location.city' against the canonical record."""
    if path is None:
        return None

    m = re.match(r"^([a-zA-Z_]+)\[\](?:\.(.+))?$", path)
    if m:
        field, sub = m.group(1), m.group(2)
        items = record.get(field) or []
        if not isinstance(items, list):
            return None
        if sub:
            return [_get_path_from_obj(item, sub) for item in items]
        return items

    m = re.match(r"^([a-zA-Z_]+)\[(\d+)\](?:\.(.+))?$", path)
    if m:
        field, idx, sub = m.group(1), int(m.group(2)), m.group(3)
        items = record.get(field) or []
        if not isinstance(items, list) or idx >= len(items):
            return None
        item = items[idx]
        return _get_path_from_obj(item, sub) if sub else item

    return _get_path_from_obj(record, path)


def _get_path_from_obj(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _apply_normalize(value, kind):
    if value is None:
        return None
    if kind == "E164":
        if isinstance(value, list):
            return [normalize_phone(v) for v in value]
        return normalize_phone(value)
    if kind == "canonical":
        if isinstance(value, list):
            return [normalize_skill(v) for v in value]
        return normalize_skill(value)
    return value


DEFAULT_CONFIG = {
    "fields": [
        {"path": "candidate_id", "from": "candidate_id", "type": "string", "required": True},
        {"path": "full_name", "from": "full_name", "type": "string", "required": True},
        {"path": "emails", "from": "emails", "type": "string[]"},
        {"path": "phones", "from": "phones", "type": "string[]"},
        {"path": "location", "from": "location", "type": "object"},
        {"path": "links", "from": "links", "type": "object"},
        {"path": "headline", "from": "headline", "type": "string"},
        {"path": "years_experience", "from": "years_experience", "type": "number"},
        {"path": "skills", "from": "skills", "type": "array"},
        {"path": "experience", "from": "experience", "type": "array"},
        {"path": "education", "from": "education", "type": "array"},
    ],
    "include_confidence": True,
    "include_provenance": True,
    "on_missing": "null",
}


def project(record, config=None):
    """Apply a config to a single canonical record -> output dict."""
    config = config or DEFAULT_CONFIG
    on_missing = config.get("on_missing", "null")
    out = {}

    for f in config.get("fields", []):
        path = f.get("from", f.get("path"))
        value = _get_path(record, path)
        if f.get("normalize"):
            value = _apply_normalize(value, f["normalize"])

        is_missing = value in (None, [], {}, "")
        if is_missing:
            if f.get("required") and on_missing == "error":
                raise MissingRequiredFieldError(
                    f"Required field '{f['path']}' missing for candidate "
                    f"{record.get('candidate_id')}"
                )
            if on_missing == "omit" and not f.get("required"):
                continue
            out[f["path"]] = None
        else:
            out[f["path"]] = value

    if config.get("include_provenance", True):
        out["provenance"] = record.get("provenance", [])
    if config.get("include_confidence", True):
        out["overall_confidence"] = record.get("overall_confidence", 0.0)

    return out


def project_all(records, config=None):
    return [project(r, config) for r in records]
