# Multi-Source Candidate Data Transformer

Eightfold Engineering Intern (Jul–Dec 2026) — Assignment submission.

Merges candidate data from a **Recruiter CSV export** (structured) and a
**Resume file** (.docx/.pdf/.txt, unstructured) into one canonical JSON
profile per candidate, with provenance and confidence on every field, and
a runtime config that reshapes the output without touching the engine.

## Pipeline

```
detect -> extract -> normalize -> merge -> confidence -> project -> validate
```

| Stage | File | What it does |
|---|---|---|
| detect | `pipeline/extract.py: detect_source` | Picks a parser by file extension |
| extract | `pipeline/extract.py` | CSV rows -> dicts; resume text -> regex-extracted fields. Never invents missing values. |
| normalize | `pipeline/normalize.py` | Phones -> E.164, dates -> `YYYY-MM`, skills -> canonical names, country -> ISO-3166 alpha-2 |
| merge + confidence | `pipeline/merge.py` | Matches candidates across sources (email, fallback to name), resolves conflicts by source trust, scores each field |
| project | `pipeline/project.py` | Applies the runtime config: field selection, renaming (`from`), normalization, `on_missing` policy |
| validate | `pipeline/validate.py` | Builds a JSON Schema from the config and validates the projected output (never raises — returns errors) |

See `docs/Design_Write_up.pdf` for the full design write-up
(merge policy, confidence model, edge cases, scope cuts).

## Setup

```bash
pip install -r requirements.txt
```

## Run

Default schema (full canonical profile, confidence + provenance included):

```bash
python cli.py --csv sources/recruiter.csv --resume sources/resume_candidate.docx \
  --out sample_output/default_output.json
```

Custom config (subset of fields, renamed, no provenance):

```bash
python cli.py --csv sources/recruiter.csv --resume sources/resume_candidate.docx \
  --config config/custom_config.json --out sample_output/custom_output.json
```

Omit `--out` to print JSON to stdout. Either `--csv` or `--resume` alone is
fine — the pipeline degrades gracefully (lower confidence, fewer fields)
rather than crashing when a source is missing.

## Web Dashboard

To run the interactive web-based dashboard:

```bash
python app.py
```

Then open `http://localhost:5000` in your web browser. The dashboard allows you to upload CSV/resume files, edit the projection config in real time, visualize the pipeline stages, inspect the canonical profiles, and see JSON schema validation results.

## Tests

```bash
pytest tests/ -v
```

21 tests covering normalization edge cases (garbage phone numbers, invalid
emails, "Present" as an end date), extraction robustness (missing files,
blank CSV rows), merge matching/conflict handling, config projection
(rename, omit, error-on-missing), and schema validation.

## Sample data

- `sources/recruiter.csv` — 3 rows: one clean, one with a malformed
  email and no name (tests robustness), one clean but resume-less.
- `sources/resume_candidate.docx` — matches the first CSV row by email, so
  you can see cross-source merge + provenance + conflict resolution in
  the output.
- `sample_output/` — pre-generated output for both configs above.

## Config format

```json
{
  "fields": [
    { "path": "full_name", "from": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string" },
    { "path": "phone", "from": "phones[0]", "normalize": "E164" },
    { "path": "top_skills", "from": "skills[].name", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "null"
}
```

`from` supports dotted paths (`location.city`), array indices
(`emails[0]`), and array-map (`skills[].name`). `on_missing` is
`null` | `omit` | `error`.

## Known limitations / deliberately out of scope

- Matching is email-first, name-fallback — no fuzzy name matching
  (e.g. nicknames, typos) or phone-based matching.
- Resume parsing is regex/heuristic-based, not ML-based, so unusual
  resume layouts will yield fewer extracted fields (degrades to fewer
  fields, not wrong fields).
- `years_experience` is not auto-computed from experience date ranges
  in this cut (left as `null` unless a source provides it directly).
- No ATS JSON / GitHub / LinkedIn parsers implemented (out of scope per
  assignment: one structured + one unstructured source is sufficient),
  but `pipeline/extract.py` is structured so adding `extract_ats_json`
  or `extract_github` is a same-shaped function away.
