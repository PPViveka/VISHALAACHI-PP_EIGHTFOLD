"""
merge.py
--------
Stage 4 (merge) + Stage 5 (confidence).

Matching key: normalized email if present on >=2 sources, else
normalized full_name (lowercased, whitespace-collapsed) as a fallback.
This is a simplifying assumption -- see README "edge cases".

Source trust order (highest first) used to break ties when two sources
disagree on a scalar field:
    recruiter_csv > resume

Resumes are self-reported and unstructured (regex-extracted), so they
rank below recruiter-provided structured data, but are the richer
source for skills/experience/education which the CSV doesn't carry at
all.

Confidence model (0-1 per field, then averaged for overall_confidence):
    - structured source, exact field match            -> 0.95
    - structured source, normalized w/ no info loss    -> 0.85
    - unstructured source, regex-extracted             -> 0.6
    - value present in >1 source and they agree        -> +0.1 (capped at 0.99)
    - value present in >1 source and they disagree      -> winner gets base score, -0.15
"""

import re
import uuid

from . import normalize as N

SOURCE_TRUST = {
    "recruiter_csv": 5,
    "ats_json": 4,
    "linkedin": 3,
    "github": 2,
    "resume": 1,
    "recruiter_notes": 0
}

BASE_CONFIDENCE = {
    ("recruiter_csv", "exact"): 0.95,
    ("recruiter_csv", "normalized"): 0.85,
    ("ats_json", "exact"): 0.92,
    ("ats_json", "normalized"): 0.82,
    ("linkedin", "exact"): 0.80,
    ("linkedin", "regex_extracted"): 0.70,
    ("github", "exact"): 0.75,
    ("github", "regex_extracted"): 0.65,
    ("resume", "regex_extracted"): 0.60,
    ("recruiter_notes", "regex_extracted"): 0.50
}


def _norm_key(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def match_records(raw_records):
    """Group raw records into per-candidate buckets using email, falling
    back to normalized name. Returns list of {"records": [...]} groups."""
    buckets = []
    by_email = {}
    by_name = {}

    for rec in raw_records:
        email = N.normalize_email(rec.get("email"))
        name_key = _norm_key(rec.get("full_name"))

        bucket = None
        if email and email in by_email:
            bucket = by_email[email]
        elif name_key and name_key in by_name:
            bucket = by_name[name_key]

        if bucket is None:
            bucket = {"records": []}
            buckets.append(bucket)

        bucket["records"].append(rec)
        if email:
            by_email[email] = bucket
        if name_key:
            by_name[name_key] = bucket

    return buckets


def _add_field(canonical, provenance, confidences, field, value, source, method, conflict=False):
    if value in (None, "", [], {}):
        return
    base = BASE_CONFIDENCE.get((source, method), 0.5)
    if conflict:
        base = max(0.05, base - 0.15)
    canonical[field] = value
    provenance.append({"field": field, "source": source, "method": method})
    confidences[field] = round(min(0.99, base), 2)


def merge_candidate(records):
    """Merge one candidate's raw records (already matched) into a
    canonical profile dict + provenance list + per-field confidence."""
    canonical = {
        "candidate_id": str(uuid.uuid4()),
        "links": {"linkedin": None, "github": None, "portfolio": None, "other": []}
    }
    provenance = []
    confidences = {}

    # Order by trust so the highest-trust source is applied last and wins
    # on scalar fields, while we still record disagreement.
    ordered = sorted(records, key=lambda r: SOURCE_TRUST.get(r.get("source"), 0))

    seen_values = {}  # field -> set of distinct normalized values seen, for conflict detection

    def track(field, value):
        seen_values.setdefault(field, set())
        had_conflict = bool(seen_values[field]) and value not in seen_values[field]
        seen_values[field].add(value)
        return had_conflict

    emails, phones = [], []

    for rec in ordered:
        source = rec.get("source")
        is_structured = source in ("recruiter_csv", "ats_json")
        method = "exact" if is_structured else "regex_extracted"

        # 1. Full Name
        if rec.get("full_name"):
            name = N.normalize_name(rec["full_name"])
            if name:
                conflict = track("full_name", name)
                _add_field(canonical, provenance, confidences, "full_name", name, source, method, conflict)

        # 2. Email
        if rec.get("email"):
            email = N.normalize_email(rec["email"])
            if email and email not in emails:
                emails.append(email)
                provenance.append({"field": "emails", "source": source, "method": method})

        # 3. Phone
        if rec.get("phone"):
            phone = N.normalize_phone(rec["phone"])
            if phone and phone not in phones:
                phones.append(phone)
                provenance.append({"field": "phones", "source": source, "method": "normalized" if is_structured else "regex_extracted"})

        # 4. Headline
        if rec.get("headline"):
            headline = rec["headline"]
            conflict = track("headline", headline)
            _add_field(canonical, provenance, confidences, "headline", headline, source, method, conflict)

        # 5. Current Company / Title (Experience scalar helper)
        if rec.get("current_company") or rec.get("title"):
            exp_list = canonical.setdefault("experience", [])
            # Avoid direct duplicate entries
            exists = any(e.get("company") == rec.get("current_company") and e.get("title") == rec.get("title") for e in exp_list)
            if not exists:
                exp_list.append({
                    "company": rec.get("current_company") or None,
                    "title": rec.get("title") or None,
                    "start": None,
                    "end": None,
                    "summary": None,
                })
                provenance.append({"field": "experience", "source": source, "method": method})
                confidences["experience"] = 0.92 if source == "ats_json" else 0.9

        # 6. Skills
        skills_raw = rec.get("skills_raw") or []
        if isinstance(skills_raw, str):
            skills_raw = [s.strip() for s in re.split(r"[,|;\u2022\n]", skills_raw) if s.strip()]
        if skills_raw:
            skill_objs = canonical.setdefault("skills", [])
            existing = {s["name"] for s in skill_objs}
            for tok in skills_raw:
                name_norm = N.normalize_skill(tok)
                if name_norm and name_norm not in existing:
                    skill_conf = 0.85 if is_structured else 0.6
                    skill_objs.append({"name": name_norm, "confidence": skill_conf, "sources": [source]})
                    existing.add(name_norm)
            provenance.append({"field": "skills", "source": source, "method": method})

        # 7. Experience List
        for exp in rec.get("experience_raw", []):
            entry = {
                "company": (exp.get("company") or "").strip() or None,
                "title": (exp.get("title") or "").strip() or None,
                "start": N.normalize_date(exp.get("start")),
                "end": N.normalize_date(exp.get("end")),
                "summary": (exp.get("summary") or "").strip() or None,
            }
            canonical.setdefault("experience", []).append(entry)
            provenance.append({"field": "experience", "source": source, "method": method})
            confidences["experience"] = min(confidences.get("experience", 1.0), 0.85 if is_structured else 0.6)

        # 8. Education List
        for edu in rec.get("education_raw", []):
            end_yr = edu.get("end_year")
            entry = {
                "institution": (edu.get("institution") or "").strip() or None,
                "degree": (edu.get("degree") or "").strip() or None,
                "field": (edu.get("field") or "").strip() or None,
                "end_year": int(end_yr) if end_yr and str(end_yr).isdigit() else None,
            }
            canonical.setdefault("education", []).append(entry)
            provenance.append({"field": "education", "source": source, "method": method})
            confidences["education"] = min(confidences.get("education", 1.0), 0.85 if is_structured else 0.6)

        # 9. Link: GitHub
        if rec.get("github_url"):
            canonical["links"]["github"] = rec["github_url"]
            provenance.append({"field": "links.github", "source": source, "method": "exact"})

        # 10. Link: LinkedIn
        if rec.get("linkedin_url"):
            canonical["links"]["linkedin"] = rec["linkedin_url"]
            provenance.append({"field": "links.linkedin", "source": source, "method": "exact"})

    if emails:
        canonical["emails"] = emails
        confidences["emails"] = 0.95 if any(r.get("source") == "recruiter_csv" for r in records) else 0.85
    if phones:
        canonical["phones"] = phones
        confidences["phones"] = 0.9 if any(r.get("source") == "recruiter_csv" for r in records) else 0.8

    canonical.setdefault("skills", canonical.get("skills", []))
    canonical.setdefault("experience", canonical.get("experience", []))
    canonical.setdefault("education", canonical.get("education", []))
    canonical.setdefault("location", None)
    canonical.setdefault("years_experience", None)
    canonical.setdefault("headline", canonical.get("headline"))
    canonical.setdefault("full_name", canonical.get("full_name") or "Unknown")

    if confidences:
        overall = round(sum(confidences.values()) / len(confidences), 2)
    else:
        overall = 0.0
    canonical["overall_confidence"] = overall
    canonical["provenance"] = provenance

    return canonical


def merge_all(raw_records):
    """Full merge stage: match then merge each bucket. Returns list of
    canonical candidate profiles (usually length 1 for this assignment's
    sample inputs, but designed to scale to many)."""
    buckets = match_records(raw_records)
    return [merge_candidate(b["records"]) for b in buckets if b["records"]]
