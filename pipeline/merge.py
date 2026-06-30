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
from datetime import date, datetime

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


def _is_name_match(n1, n2):
    """
    Fuzzy match logic for names. Returns True if last names match exactly AND:
    - First names match exactly, OR
    - One first name is a prefix of the other (e.g. 'Alex' matches 'Alexander', min 3 chars).
    """
    if not n1 or not n2:
        return False
    n1_parts = n1.split()
    n2_parts = n2.split()
    if len(n1_parts) < 2 or len(n2_parts) < 2:
        return n1 == n2
    # Last name exact match
    if n1_parts[-1] != n2_parts[-1]:
        return False
    f1, f2 = n1_parts[0], n2_parts[0]
    if f1 == f2:
        return True
    if len(f1) >= 3 and len(f2) >= 3:
        if f1.startswith(f2) or f2.startswith(f1):
            return True
    return False


def deduplicate_experiences(experience_list):
    """
    Deduplicate experience entries. If two entries have the same company (normalized)
    and overlapping dates, merge them into one entry.
    """
    if not experience_list:
        return []

    def clean_company(name):
        if not name:
            return ""
        name = name.lower().strip()
        # Remove punctuation
        name = re.sub(r"[.,\/#!$%\^&\*;:{}=\-_`~()]", "", name)
        # Remove common suffixes
        name = re.sub(r"\b(inc|corp|ltd|co|gmbh|llc|corporation|limited)\b", "", name)
        return re.sub(r"\s+", "", name)

    def clean_title(title):
        if not title:
            return ""
        title = title.lower().strip()
        # standard replacements
        title = title.replace("developer", "engineer").replace("dev", "engineer")
        return re.sub(r"\s+", "", title)

    # Group experiences by company + title similarity
    unique_groups = []
    
    for exp in experience_list:
        comp_clean = clean_company(exp.get("company"))
        title_clean = clean_title(exp.get("title"))
        
        placed = False
        for group in unique_groups:
            g_comp = clean_company(group[0].get("company"))
            g_title = clean_title(group[0].get("title"))
            
            if comp_clean == g_comp and (not title_clean or not g_title or title_clean == g_title or title_clean in g_title or g_title in title_clean):
                group.append(exp)
                placed = True
                break
                
        if not placed:
            unique_groups.append([exp])
            
    deduped = []
    for group in unique_groups:
        merged_exp = {
            "company": next((e.get("company") for e in group if e.get("company")), None) or group[0].get("company"),
            "title": next((e.get("title") for e in group if e.get("title")), None) or group[0].get("title"),
            "start": None,
            "end": None,
            "summary": next((e.get("summary") for e in group if e.get("summary")), None),
        }
        
        starts = [e.get("start") for e in group if e.get("start")]
        ends = [e.get("end") for e in group if e.get("end")]
        
        if starts:
            merged_exp["start"] = min(starts)
        if ends:
            merged_exp["end"] = max(ends)
            
        deduped.append(merged_exp)
        
    return deduped


def calculate_years_experience(experience_list):
    """
    Sum the lengths of non-overlapping experience intervals.
    Each exp entry should have 'start' (YYYY-MM) and 'end' (YYYY-MM).
    """
    if not experience_list:
        return 0.0

    intervals = []
    today = date.today()

    for exp in experience_list:
        start_str = exp.get("start")
        end_str = exp.get("end")

        if not start_str and not end_str:
            continue

        try:
            if start_str:
                dt_start = datetime.strptime(start_str, "%Y-%m").date()
            else:
                dt_start = today

            if end_str:
                dt_end = datetime.strptime(end_str, "%Y-%m").date()
            else:
                dt_end = today

            if dt_start > dt_end:
                dt_start, dt_end = dt_end, dt_start

            intervals.append((dt_start, dt_end))
        except Exception:
            continue

    if not intervals:
        return 0.0

    # Sort and merge overlaps
    intervals.sort(key=lambda x: x[0])
    merged = []
    for current in intervals:
        if not merged:
            merged.append(current)
        else:
            prev_start, prev_end = merged[-1]
            curr_start, curr_end = current

            if curr_start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, curr_end))
            else:
                merged.append(current)

    total_months = 0
    for start, end in merged:
        diff_months = (end.year - start.year) * 12 + (end.month - start.month) + 1
        total_months += max(1, diff_months)

    return round(total_months / 12.0, 1)


def match_records(raw_records):
    """Group raw records into per-candidate buckets using email, falling
    back to fuzzy name matching. Returns list of {"records": [...]} groups."""
    buckets = []
    by_email = {}

    for rec in raw_records:
        email = N.normalize_email(rec.get("email"))
        name_key = _norm_key(rec.get("full_name"))

        bucket = None
        # 1. First check by email
        if email and email in by_email:
            bucket = by_email[email]
        # 2. Check by name fuzzy match fallback
        elif name_key:
            for b in buckets:
                # Find if any record in the bucket matches the name fuzzily
                for existing_rec in b["records"]:
                    existing_name = _norm_key(existing_rec.get("full_name"))
                    if existing_name and _is_name_match(name_key, existing_name):
                        bucket = b
                        break
                if bucket:
                    break

        if bucket is None:
            bucket = {"records": []}
            buckets.append(bucket)

        bucket["records"].append(rec)
        if email:
            by_email[email] = bucket

    return buckets


def _add_provenance(provenance, field, source, method):
    entry = {"field": field, "source": source, "method": method}
    if entry not in provenance:
        provenance.append(entry)


def _add_field(canonical, provenance, confidences, field, value, source, method, conflict=False):
    if value in (None, "", [], {}):
        return
    base = BASE_CONFIDENCE.get((source, method), 0.5)
    if conflict:
        base = max(0.05, base - 0.15)
    canonical[field] = value
    _add_provenance(provenance, field, source, method)
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
                _add_provenance(provenance, "emails", source, method)

        # 3. Phone
        if rec.get("phone"):
            phone = N.normalize_phone(rec["phone"])
            if phone and phone not in phones:
                phones.append(phone)
                _add_provenance(provenance, "phones", source, "normalized" if is_structured else "regex_extracted")

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
                _add_provenance(provenance, "experience", source, method)
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
            _add_provenance(provenance, "skills", source, method)

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
            _add_provenance(provenance, "experience", source, method)
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
            _add_provenance(provenance, "education", source, method)
            confidences["education"] = min(confidences.get("education", 1.0), 0.85 if is_structured else 0.6)

        # 9. Link: GitHub
        if rec.get("github_url"):
            canonical["links"]["github"] = rec["github_url"]
            _add_provenance(provenance, "links.github", source, "exact")

        # 10. Link: LinkedIn
        if rec.get("linkedin_url"):
            canonical["links"]["linkedin"] = rec["linkedin_url"]
            _add_provenance(provenance, "links.linkedin", source, "exact")

        # 11. Certifications
        if rec.get("certifications"):
            certs = rec["certifications"]
            if isinstance(certs, str):
                certs = [c.strip() for c in re.split(r"[,|\n\u2022;]", certs) if c.strip()]
            canonical_certs = canonical.setdefault("certifications", [])
            for c in certs:
                if c not in canonical_certs:
                    canonical_certs.append(c)
            _add_provenance(provenance, "certifications", source, method)
            confidences["certifications"] = 0.85 if is_structured else 0.6

        # 12. Languages
        if rec.get("languages"):
            langs = rec["languages"]
            if isinstance(langs, str):
                langs = [l.strip() for l in re.split(r"[,|\n\u2022;]", langs) if l.strip()]
            canonical_langs = canonical.setdefault("languages", [])
            for l in langs:
                l_norm = l.title().strip()
                if l_norm not in canonical_langs:
                    canonical_langs.append(l_norm)
            _add_provenance(provenance, "languages", source, method)
            confidences["languages"] = 0.85 if is_structured else 0.6

        # 13. Projects
        if rec.get("projects"):
            projs = rec["projects"]
            canonical_projs = canonical.setdefault("projects", [])
            for p in projs:
                exists = any(cp.get("name") == p.get("name") for cp in canonical_projs)
                if not exists:
                    canonical_projs.append({
                        "name": p.get("name"),
                        "description": p.get("description") or None,
                        "url": p.get("url") or None,
                        "primary_language": p.get("primary_language") or None
                    })
            _add_provenance(provenance, "projects", source, method)
            confidences["projects"] = 0.9 if source == "github" else (0.85 if is_structured else 0.6)

    if emails:
        canonical["emails"] = emails
        confidences["emails"] = 0.95 if any(r.get("source") == "recruiter_csv" for r in records) else 0.85
    if phones:
        canonical["phones"] = phones
        confidences["phones"] = 0.9 if any(r.get("source") == "recruiter_csv" for r in records) else 0.8

    canonical.setdefault("skills", canonical.get("skills", []))
    canonical.setdefault("experience", canonical.get("experience", []))
    if canonical["experience"]:
        canonical["experience"] = deduplicate_experiences(canonical["experience"])
    canonical.setdefault("education", canonical.get("education", []))
    canonical.setdefault("certifications", [])
    canonical.setdefault("languages", [])
    canonical.setdefault("projects", [])
    canonical.setdefault("location", None)
    canonical["years_experience"] = calculate_years_experience(canonical.get("experience", []))
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
