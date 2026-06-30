#!/usr/bin/env python3
"""
cli.py
------
Thin CLI surface for the Multi-Source Candidate Data Transformer.

Usage:
    python cli.py --csv sources/recruiter.csv --resume sources/resume.docx \
                   [--config config/custom_config.json] [--out output.json]

If --config is omitted, the default schema/config is used.
The pipeline runs: detect -> extract -> normalize -> merge -> confidence
-> project -> validate, end to end, and never crashes on a missing or
garbage source -- it just produces a profile with fewer fields and
lower confidence.
"""

import argparse
import json
import sys

from pipeline.extract import extract_all
from pipeline.merge import merge_all
from pipeline.project import project_all, DEFAULT_CONFIG
from pipeline.validate import validate_all


def run(csv_path=None, resume_path=None, ats_path=None, github_url=None, linkedin_url=None, notes_path=None, config_path=None, out_path=None):
    raw_records = extract_all(
        recruiter_csv_path=csv_path,
        resume_path=resume_path,
        ats_json_path=ats_path,
        github_url=github_url,
        linkedin_url=linkedin_url,
        notes_path=notes_path
    )

    if not raw_records:
        print("WARNING: no usable records extracted from any source -- "
              "check that input paths exist and are readable.",
              file=sys.stderr)

    canonical_records = merge_all(raw_records)

    if config_path:
        with open(config_path) as f:
            config = json.load(f)
    else:
        config = DEFAULT_CONFIG

    outputs = project_all(canonical_records, config)
    validation = validate_all(outputs, config)

    for v in validation:
        if not v["valid"]:
            print(f"VALIDATION WARNING for {v['candidate_id']}: {v['errors']}",
                  file=sys.stderr)

    result = {"profiles": outputs, "validation": validation}

    text = json.dumps(result, indent=2)
    if out_path:
        with open(out_path, "w") as f:
            f.write(text)
        print(f"Wrote {len(outputs)} profile(s) to {out_path}")
    else:
        print(text)

    return result


def main():
    parser = argparse.ArgumentParser(description="Multi-Source Candidate Data Transformer")
    parser.add_argument("--csv", help="Path to recruiter CSV export")
    parser.add_argument("--resume", help="Path to resume file (.pdf/.docx/.txt)")
    parser.add_argument("--ats", help="Path to ATS JSON export file")
    parser.add_argument("--github", help="GitHub profile URL or username")
    parser.add_argument("--linkedin", help="LinkedIn profile URL")
    parser.add_argument("--notes", help="Path to recruiter notes text file (.txt)")
    parser.add_argument("--config", help="Path to runtime projection config JSON")
    parser.add_argument("--out", help="Path to write output JSON (default: stdout)")
    args = parser.parse_args()

    if not any([args.csv, args.resume, args.ats, args.github, args.linkedin, args.notes]):
        parser.error("At least one input source (--csv, --resume, --ats, --github, --linkedin, or --notes) must be provided.")

    run(
        csv_path=args.csv,
        resume_path=args.resume,
        ats_path=args.ats,
        github_url=args.github,
        linkedin_url=args.linkedin,
        notes_path=args.notes,
        config_path=args.config,
        out_path=args.out
    )


if __name__ == "__main__":
    main()
