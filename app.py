import os
import json
import uuid
import shutil
from flask import Flask, request, jsonify, send_from_directory
from pipeline.extract import extract_all
from pipeline.merge import merge_all
from pipeline.project import project_all, DEFAULT_CONFIG
from pipeline.validate import validate_all

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")

@app.route("/api/run", methods=["POST"])
def run_pipeline():
    uploaded_files = request.files.getlist("files")
    github_url = request.form.get("github_url")
    linkedin_url = request.form.get("linkedin_url")
    config_str = request.form.get("config")

    csv_path = None
    resume_path = None
    ats_path = None
    notes_path = None
    saved_paths = []
    session_id = str(uuid.uuid4())

    try:
        # Save and classify all uploaded files
        for f in uploaded_files:
            if not f or not f.filename:
                continue
            
            ext = os.path.splitext(f.filename)[1].lower()
            save_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_{f.filename}")
            f.save(save_path)
            saved_paths.append(save_path)

            if ext == ".csv":
                csv_path = save_path
            elif ext == ".json":
                ats_path = save_path
            elif ext == ".txt":
                if "notes" in f.filename.lower() or "feedback" in f.filename.lower():
                    notes_path = save_path
                else:
                    resume_path = save_path
            elif ext in (".pdf", ".docx"):
                resume_path = save_path

        # Run extraction
        raw_records = extract_all(
            recruiter_csv_path=csv_path,
            resume_path=resume_path,
            ats_json_path=ats_path,
            github_url=github_url,
            linkedin_url=linkedin_url,
            notes_path=notes_path
        )
        
        # Run merging
        canonical_records = merge_all(raw_records)

        # Load config
        if config_str:
            try:
                config = json.loads(config_str)
            except Exception:
                config = DEFAULT_CONFIG
        else:
            config = DEFAULT_CONFIG

        # Run projection and validation
        outputs = project_all(canonical_records, config)
        validation = validate_all(outputs, config)

        result = {
            "profiles": outputs,
            "validation": validation,
            "canonical": canonical_records
        }
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        # Cleanup saved files
        for p in saved_paths:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

if __name__ == "__main__":
    app.run(debug=True, port=5000)
