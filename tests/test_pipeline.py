"""
Run with: pytest tests/
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.normalize import normalize_phone, normalize_date, normalize_skill, normalize_email
from pipeline.extract import (
    extract_recruiter_csv, extract_resume, extract_ats_json,
    extract_github, extract_linkedin, extract_recruiter_notes
)
from pipeline.merge import merge_all
from pipeline.project import project, DEFAULT_CONFIG, MissingRequiredFieldError
from pipeline.validate import validate_output

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CSV_PATH = os.path.join(ROOT, "sources", "recruiter.csv")
RESUME_PATH = os.path.join(ROOT, "sources", "resume_candidate.docx")


# ---------------------------------------------------------- normalize ----

def test_normalize_phone_valid():
    assert normalize_phone("+1 415-555-0182") == "+14155550182"


def test_normalize_phone_garbage_returns_none():
    assert normalize_phone("not a phone at all") is None


def test_normalize_phone_empty_returns_none():
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_normalize_email_invalid():
    assert normalize_email("bademail") is None


def test_normalize_date_present_is_none():
    assert normalize_date("Present") is None


def test_normalize_date_parses_month_year():
    assert normalize_date("Jan 2022") == "2022-01"


def test_normalize_skill_alias():
    assert normalize_skill("js") == "JavaScript"


def test_normalize_skill_unknown_kept_titlecased():
    assert normalize_skill("rust programming") == "Rust Programming"


# ------------------------------------------------------------ extract ----

def test_extract_recruiter_csv_skips_blank_rows():
    records = extract_recruiter_csv(CSV_PATH)
    # 3 rows in CSV, one is fully blank-ish but has 'bademail' so it's kept
    # as a row with no name -- the point is it doesn't crash and doesn't
    # invent a name.
    assert all(r["source"] == "recruiter_csv" for r in records)
    assert any(r["full_name"] is None for r in records)


def test_extract_recruiter_csv_missing_file_returns_empty():
    assert extract_recruiter_csv("does_not_exist.csv") == []


def test_extract_resume_docx_pulls_email_and_skills():
    rec = extract_resume(RESUME_PATH)
    assert rec is not None
    assert rec["email"] == "alex.mercer@example.com"
    assert "skills_raw" in rec
    assert "Python" in rec["skills_raw"]


def test_extract_resume_missing_file_returns_none():
    assert extract_resume("does_not_exist.docx") is None


# -------------------------------------------------------------- merge ----

def test_merge_links_csv_and_resume_by_email():
    raw = extract_recruiter_csv(CSV_PATH) + [extract_resume(RESUME_PATH)]
    profiles = merge_all(raw)
    viveka = next(p for p in profiles if p["full_name"] == "Alex Mercer")
    sources_used = {p["source"] for p in raw if p.get("email") == "alex.mercer@example.com"}
    assert sources_used == {"recruiter_csv", "resume"}
    # Provenance should show both sources contributed
    prov_sources = {p["source"] for p in viveka["provenance"]}
    assert "recruiter_csv" in prov_sources
    assert "resume" in prov_sources


def test_merge_never_crashes_on_empty_input():
    assert merge_all([]) == []


def test_merge_row_with_no_identifiers_does_not_crash():
    # Row with no name/email at all -- should still produce a profile,
    # not raise, with full_name falling back to "Unknown".
    raw = [{"source": "recruiter_csv", "raw": {}}]
    profiles = merge_all(raw)
    assert len(profiles) == 1
    assert profiles[0]["full_name"] == "Unknown"
    assert profiles[0]["overall_confidence"] == 0.0


# ------------------------------------------------------------ project ----

def test_project_default_config_includes_all_fields():
    raw = extract_recruiter_csv(CSV_PATH) + [extract_resume(RESUME_PATH)]
    profiles = merge_all(raw)
    viveka = next(p for p in profiles if p["full_name"] == "Alex Mercer")
    out = project(viveka, DEFAULT_CONFIG)
    assert out["full_name"] == "Alex Mercer"
    assert "overall_confidence" in out
    assert "provenance" in out


def test_project_custom_config_renames_and_drops_fields():
    raw = extract_recruiter_csv(CSV_PATH) + [extract_resume(RESUME_PATH)]
    profiles = merge_all(raw)
    viveka = next(p for p in profiles if p["full_name"] == "Alex Mercer")
    config = {
        "fields": [
            {"path": "primary_email", "from": "emails[0]", "type": "string", "required": True},
        ],
        "include_confidence": False,
        "include_provenance": False,
        "on_missing": "null",
    }
    out = project(viveka, config)
    assert out == {"primary_email": "alex.mercer@example.com"}


def test_project_on_missing_error_raises_for_required_field():
    record = {"candidate_id": "x", "full_name": None}
    config = {
        "fields": [{"path": "full_name", "from": "full_name", "type": "string", "required": True}],
        "on_missing": "error",
        "include_confidence": False,
        "include_provenance": False,
    }
    try:
        project(record, config)
        assert False, "expected MissingRequiredFieldError"
    except MissingRequiredFieldError:
        pass


def test_project_on_missing_omit_drops_optional_field():
    record = {"candidate_id": "x", "full_name": "Someone", "headline": None}
    config = {
        "fields": [
            {"path": "full_name", "from": "full_name", "type": "string", "required": True},
            {"path": "headline", "from": "headline", "type": "string"},
        ],
        "on_missing": "omit",
        "include_confidence": False,
        "include_provenance": False,
    }
    out = project(record, config)
    assert "headline" not in out


# ----------------------------------------------------------- validate ----

def test_validate_default_output_is_valid():
    raw = extract_recruiter_csv(CSV_PATH) + [extract_resume(RESUME_PATH)]
    profiles = merge_all(raw)
    viveka = next(p for p in profiles if p["full_name"] == "Alex Mercer")
    out = project(viveka, DEFAULT_CONFIG)
    ok, errors = validate_output(out, DEFAULT_CONFIG)
    assert ok, errors


def test_validate_catches_type_mismatch():
    config = {"fields": [{"path": "full_name", "type": "string", "required": True}]}
    bad_output = {"full_name": 12345}  # wrong type
    ok, errors = validate_output(bad_output, config)
    assert not ok
    assert errors


# -------------------------------------------------------- new sources ----

def test_extract_ats_json():
    ats_path = os.path.join(ROOT, "sources", "sample_ats.json")
    recs = extract_ats_json(ats_path)
    assert len(recs) == 1
    assert recs[0]["full_name"] == "Alex Mercer"
    assert recs[0]["email"] == "alex.mercer@example.com"
    assert recs[0]["phone"] == "+1 415-555-0182"
    assert "skills_raw" in recs[0]
    assert "Go" in recs[0]["skills_raw"]


def test_extract_github():
    rec = extract_github("https://github.com/alexmercer")
    assert rec is not None
    assert rec["full_name"] == "Alex Mercer"
    assert rec["email"] == "alex.mercer@example.com"
    assert "skills_raw" in rec
    assert "Docker" in rec["skills_raw"]


def test_extract_linkedin():
    rec = extract_linkedin("https://linkedin.com/in/alex-mercer")
    assert rec is not None
    assert rec["full_name"] == "Alex Mercer"
    assert rec["headline"] == "Software Engineer at Acme Corp"


def test_extract_recruiter_notes():
    notes_path = os.path.join(ROOT, "sources", "sample_notes.txt")
    rec = extract_recruiter_notes(notes_path)
    assert rec is not None
    assert rec["full_name"] == "Alex Mercer"
    assert rec["email"] == "alex.mercer@example.com"
    assert "skills_raw" in rec
    assert "Kubernetes" in rec["skills_raw"]


def test_merge_all_six_sources():
    ats_path = os.path.join(ROOT, "sources", "sample_ats.json")
    notes_path = os.path.join(ROOT, "sources", "sample_notes.txt")
    
    raw = (
        extract_recruiter_csv(CSV_PATH) +
        [extract_resume(RESUME_PATH)] +
        extract_ats_json(ats_path) +
        [extract_github("https://github.com/alexmercer")] +
        [extract_linkedin("https://linkedin.com/in/alex-mercer")] +
        [extract_recruiter_notes(notes_path)]
    )
    
    profiles = merge_all(raw)
    
    # Check that Alex Mercer got merged successfully
    alex = next(p for p in profiles if p["full_name"] == "Alex Mercer")
    
    # Check links populated
    assert alex["links"]["github"] == "https://github.com/alexmercer"
    assert alex["links"]["linkedin"] == "https://linkedin.com/in/alex-mercer"
    
    # Merged emails and phones lists
    assert "alex.mercer@example.com" in alex["emails"]
    assert "+14155550182" in alex["phones"]
    
    # High confidence because we matched on reliable sources
    assert alex["overall_confidence"] >= 0.8


def test_calculate_years_experience():
    from pipeline.merge import calculate_years_experience
    # 2020-01 to 2021-12 is 24 months. 
    # 2021-06 to 2022-06 is 13 months, but overlaps by 7 months (2021-06 to 2021-12).
    # Total merged interval: 2020-01 to 2022-06 (30 months = 2.5 years)
    exp_list = [
        {"start": "2020-01", "end": "2021-12"},
        {"start": "2021-06", "end": "2022-06"},
    ]
    years = calculate_years_experience(exp_list)
    assert years == 2.5


def test_fuzzy_name_matching():
    # Merge records that have nickname variations of the same name and no emails
    raw = [
        {"source": "resume", "full_name": "Alexander Mercer"},
        {"source": "recruiter_csv", "full_name": "Alex Mercer"}
    ]
    profiles = merge_all(raw)
    assert len(profiles) == 1
    # recruiter_csv has higher trust, so "Alex Mercer" wins
    assert profiles[0]["full_name"] == "Alex Mercer"


def test_deduplicate_experiences():
    from pipeline.merge import deduplicate_experiences
    exp_list = [
        {"company": "Google Inc.", "title": "Software Developer", "start": "2020-01", "end": "2021-06"},
        {"company": "Google", "title": "Software Engineer", "start": "2021-01", "end": "2022-01"}
    ]
    deduped = deduplicate_experiences(exp_list)
    assert len(deduped) == 1
    assert deduped[0]["company"] == "Google Inc."
    assert deduped[0]["start"] == "2020-01"
    assert deduped[0]["end"] == "2022-01"


def test_unicode_normalization():
    import unicodedata
    nfd_name = unicodedata.normalize("NFD", "François")
    nfc_name = unicodedata.normalize("NFC", "François")
    
    assert len(nfd_name) != len(nfc_name)
    
    from pipeline.normalize import normalize_name
    assert normalize_name(nfd_name) == normalize_name(nfc_name)


