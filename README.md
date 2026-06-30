# Multi-Source Candidate Data Transformer

Ingests, merges, and projects candidate data from **six distinct structured, semi-structured, and unstructured sources** into a single canonical profile per candidate. Features automatic conflict resolution, field-level provenance tracking, weighted confidence scoring, and a runtime configuration engine that reshapes output structures dynamically.

## Supported Input Sources
1. **Recruiter CSV Export (Structured)**: High-trust database records containing candidate names and contact info.
2. **ATS JSON Export (Semi-Structured)**: Standard database dump matching candidate details using dynamic key mapping.
3. **Resume Document (Unstructured)**: Parses PDF, DOCX, and TXT files using regular expressions and layout heuristics.
4. **Recruiter Notes (Unstructured)**: Extracts contact details, current role, and skills from free-text recruiter logs.
5. **GitHub Profile URL (API integration)**: Queries the public GitHub REST API to fetch profiles, bios, and repository programming languages as skills (with offline test caches).
6. **LinkedIn Profile URL (Simulated)**: Ingests mock professional profiles mapping experience and education.

---

## Pipeline Architecture

```
detect -> extract -> normalize -> merge -> confidence -> project -> validate
```

| Stage | File | What it does |
|---|---|---|
| **detect** | `pipeline/extract.py: detect_source` | Automatically resolves parser type by file extension or name |
| **extract** | `pipeline/extract.py` | Extracts raw records from all 6 sources (gracefully degrading on malformed inputs) |
| **normalize** | `pipeline/normalize.py` | Normalizes phone numbers (E.164), dates (`YYYY-MM`), skills (alias mapping), and names |
| **merge** | `pipeline/merge.py` | Deduplicates and matches records (emails, falling back to fuzzy name matching) |
| **confidence** | `pipeline/merge.py` | Scores fields based on source trust (5=CSV to 0=Notes) and applies overlap/disagreement penalties |
| **project** | `pipeline/project.py` | Reshapes output canonical profiles into target JSON objects based on the runtime config |
| **validate** | `pipeline/validate.py` | Generates a JSON Schema dynamically on the fly matching the runtime config, returning error lists |

---

## Setup

```bash
pip install -r requirements.txt
```

---

## CLI Execution

Run the end-to-end pipeline with the default configuration (canonical profile, confidence, and provenance included):
```bash
python cli.py --csv sources/sample_recruiter_large.csv --resume sources/resume_candidate.docx \
  --ats sources/sample_ats_large.json --notes sources/notes_nina_chen.txt \
  --github alexmercer --linkedin https://linkedin.com/in/alex-mercer \
  --out sample_output/default_output.json
```

Run with custom config (subset of fields, renamed, no provenance):
```bash
python cli.py --csv sources/sample_recruiter_large.csv --resume sources/resume_candidate.docx \
  --ats sources/sample_ats_large.json --notes sources/notes_nina_chen.txt \
  --github alexmercer --linkedin https://linkedin.com/in/alex-mercer \
  --config config/custom_config.json --out sample_output/custom_output.json
```

---

## Interactive Web Dashboard

To run the interactive web-based dashboard:
```bash
python app.py
```
Open **`http://localhost:5000`** in your browser.

### Key UI Features:
* **Unified Drag & Drop Dropzone**: Drag and drop any combination of candidate files (CSV, JSON, DOCX, PDF, TXT) sequentially. Clear selected items using the red "x" delete button.
* **Profile Links Accumulator Text Area**: Paste multiple profile URLs (GitHub/LinkedIn, one per line). The UI processes and submits them in batch.
* **Glassmorphic Theme**: Dark mode design with animated pipeline steppers and side-by-side verification logs.

---

## Core Edge Cases Handled

### 1. Overlapping Experience & Calendar Years Calculation
* Summing the duration of all experience entries double-counts overlapping dates (e.g. holding two jobs concurrently in 2021). 
* The pipeline integrates an interval-merging algorithm (`calculate_years_experience`) that sorts intervals, merges overlapping periods, and sums non-overlapping months, yielding a highly accurate years of experience score.

### 2. Fuzzy Name & Nickname Matching
* Matches candidates using nicknames or spelling variations (e.g. `Alexander Mercer` vs `Alex Mercer`) across sources when emails are missing.
* Last names must match exactly, and first names must match or share a common prefix (minimum 3 characters), avoiding matching unrelated candidates (e.g., `John` and `Jane`).

### 3. Unicode NFKC Normalization
* Standardizes unicode characters and diacritics using the `NFKC` standard. This ensures characters parsed differently across environments (e.g., NFD accents vs NFC composites in names like `François`) resolve to identical strings.

### 4. Experience & Company Deduplication
* Merges overlapping positions at the same company (e.g. `Software Developer` at `Google Inc.` vs `Software Engineer` at `Google`) by stripping trailing punctuation and common suffixes (like `LLC` or `Inc.`).

---

## Automated Tests

Run the test suite:
```bash
pytest tests/ -v
```
Contains **30 unit tests** covering normalization, extraction robustness, multi-source merging, custom configurations, dynamic schemas, name nickname fuzzy logic, interval calculations, role deduplications, and Unicode diacritics.

---

## Pre-Generated Sample Outputs

The pipeline has been run on all sample inputs to produce pre-generated outputs, which are checked into the repository:
* **[default_output.json](sample_output/default_output.json)**: The complete resolved profile records for all 12 candidates, generated using the default configuration (which includes full confidence scores and detailed field-level provenances).
* **[custom_output.json](sample_output/custom_output.json)**: A customized, reshaped profile subset containing only selected and renamed fields, demonstrating the runtime projection engine.

