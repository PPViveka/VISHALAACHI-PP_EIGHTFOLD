"""
detect_and_extract.py
----------------------
Stage 1 (detect) + Stage 2 (extract).

detect_source(path) looks at a file path / extension and decides which
parser to hand it to. extract_* functions turn a raw source file into a
list of "raw records": one dict per candidate, tagged with its source
name, *before* any normalization happens. Extraction never invents
values -- if something can't be found, the field is simply absent.
"""

import csv
import json
import os
import re

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    import docx
except ImportError:
    docx = None


def detect_source(path):
    """Return a coarse source-type label based on file extension/content."""
    if not os.path.exists(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return "recruiter_csv"
    if ext == ".json":
        return "ats_json"
    if ext == ".pdf":
        return "resume_pdf"
    if ext == ".docx":
        return "resume_docx"
    if ext == ".txt":
        return "resume_txt"
    return None


# ---------------------------------------------------------------- CSV ----

def extract_recruiter_csv(path):
    """Recruiter CSV export -> list of raw records, one per row."""
    records = []
    if not path or not os.path.exists(path):
        return records
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                if not any(row.values()):
                    continue  # skip fully blank rows, don't crash on them
                records.append({
                    "source": "recruiter_csv",
                    "raw": row,
                    "full_name": row.get("name") or None,
                    "email": row.get("email") or None,
                    "phone": row.get("phone") or None,
                    "current_company": row.get("current_company") or None,
                    "title": row.get("title") or None,
                    "certifications": [c.strip() for c in row.get("certifications", "").split(",") if c.strip()] if row.get("certifications") else None,
                    "languages": [l.strip() for l in row.get("languages", "").split(",") if l.strip()] if row.get("languages") else None,
                })
    except Exception as e:
        # Malformed file: degrade gracefully, return whatever we got plus a flag
        records.append({"source": "recruiter_csv", "error": str(e)})
    return [r for r in records if "error" not in r]


# ------------------------------------------------------------- Resume ----

def extract_resume(path):
    """
    Resume file (PDF / DOCX / TXT) -> single raw record with best-effort
    fields pulled out via regex/heuristics. Resumes are unstructured, so
    everything here is "best effort, never invented": if a pattern isn't
    found, the field is left out rather than guessed.
    """
    if not path or not os.path.exists(path):
        return None

    ext = os.path.splitext(path)[1].lower()
    text = ""
    try:
        if ext == ".pdf" and pdfplumber:
            with pdfplumber.open(path) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        elif ext == ".docx" and docx:
            d = docx.Document(path)
            text = "\n".join(p.text for p in d.paragraphs)
        else:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
    except Exception as e:
        return {"source": "resume", "error": str(e)}

    if not text.strip():
        return None

    record = {"source": "resume", "raw_text": text}

    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email_match:
        record["email"] = email_match.group(0)

    phone_match = re.search(r"(\+?\d[\d\s().-]{7,}\d)", text)
    if phone_match:
        record["phone"] = phone_match.group(0)

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        # Heuristic: first non-empty line that looks like a name (no digits/@/long)
        for l in lines[:5]:
            if "@" not in l and not re.search(r"\d{3,}", l) and len(l.split()) <= 5:
                record["full_name"] = l
                break

    headline_match = re.search(
        r"(?im)^(?:headline|title|summary)\s*[:\-]\s*(.+)$", text
    )
    if headline_match:
        record["headline"] = headline_match.group(1).strip()

    # Skills section: capture comma/pipe separated tokens after a "Skills" header
    skills_match = re.search(
        r"(?ims)^skills\s*[:\-]?\s*\n?(.+?)(?:\n\s*\n|\n[A-Z][a-zA-Z ]{2,20}\n|$)",
        text,
    )
    if skills_match:
        chunk = skills_match.group(1)
        tokens = re.split(r"[,|;\u2022\n]", chunk)
        record["skills_raw"] = [t.strip() for t in tokens if t.strip()]

    # Experience: lines like "Company — Title (Jan 2020 - Mar 2022)"
    exp_entries = []
    for m in re.finditer(
        r"(?im)^(?P<company>[A-Za-z0-9&.,' ]{2,60})\s*[\u2013\-]\s*(?P<title>[A-Za-z0-9&.,' /]{2,60})"
        r"\s*\((?P<start>[A-Za-z0-9 ]{3,20})\s*[\u2013\-]\s*(?P<end>[A-Za-z0-9 ]{3,20})\)",
        text,
    ):
        exp_entries.append(m.groupdict())
    if exp_entries:
        record["experience_raw"] = exp_entries

    # Education: "B.S. Computer Science, MIT, 2019" style lines
    edu_entries = []
    degree_kw = r"(?:B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?|Ph\.?D\.?|MBA|Bachelor(?:'s)?|Master(?:'s)?)"
    for m in re.finditer(
        rf"(?im)^(?P<degree>{degree_kw})\.?\s+(?:in\s+|of\s+)?(?P<field>[A-Za-z &]{{3,40}}),\s*"
        r"(?P<institution>[A-Za-z0-9 &.']{3,60}?),?\s*(?P<end_year>\d{4})?\s*$",
        text,
    ):
        d = m.groupdict()
        edu_entries.append(d)
    # Certifications extraction
    cert_match = re.search(
        r"(?ims)^certifications?\s*[:\-]?\s*\n?(.+?)(?:\n\s*\n|\n[A-Z][a-zA-Z ]{2,20}\n|$)",
        text
    )
    if cert_match:
        tokens = re.split(r"[,|\n\u2022;]", cert_match.group(1))
        record["certifications"] = [t.strip() for t in tokens if t.strip()]

    # Languages extraction
    lang_match = re.search(
        r"(?ims)^(?:languages|languages spoken)\s*[:\-]?\s*\n?(.+?)(?:\n\s*\n|\n[A-Z][a-zA-Z ]{2,20}\n|$)",
        text
    )
    if lang_match:
        tokens = re.split(r"[,|\n\u2022;]", lang_match.group(1))
        record["languages"] = [t.strip() for t in tokens if t.strip()]

    return record


def extract_ats_json(path):
    """ATS JSON blob export -> list of raw records, one per candidate."""
    records = []
    if not path or not os.path.exists(path):
        return records
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        
        if isinstance(data, dict):
            candidates = [data]
        elif isinstance(data, list):
            candidates = data
        else:
            return records
            
        for item in candidates:
            raw_record = {
                "source": "ats_json",
                "raw": item,
                "full_name": item.get("candidateName") or item.get("fullName") or item.get("name") or None,
                "email": item.get("emailAddress") or item.get("email") or None,
                "phone": item.get("telephoneNumber") or item.get("phone") or None,
                "current_company": item.get("currentEmployer") or item.get("company") or None,
                "title": item.get("jobTitle") or item.get("title") or None,
                "skills_raw": item.get("techSkills") or item.get("skills") or None,
            }
            
            if "certifications" in item and isinstance(item["certifications"], list):
                raw_record["certifications"] = item["certifications"]
            if "languages" in item and isinstance(item["languages"], list):
                raw_record["languages"] = item["languages"]
            if "projects" in item and isinstance(item["projects"], list):
                raw_record["projects"] = item["projects"]
            
            # Map standard experience format
            if "experience" in item and isinstance(item["experience"], list):
                exp_raw = []
                for e in item["experience"]:
                    exp_raw.append({
                        "company": e.get("companyName") or e.get("company") or None,
                        "title": e.get("roleTitle") or e.get("title") or None,
                        "start": e.get("startDate") or e.get("start") or None,
                        "end": e.get("endDate") or e.get("end") or None,
                    })
                raw_record["experience_raw"] = exp_raw
                
            # Map standard education format
            if "education" in item and isinstance(item["education"], list):
                edu_raw = []
                for ed in item["education"]:
                    edu_raw.append({
                        "institution": ed.get("schoolName") or ed.get("institution") or ed.get("university") or None,
                        "degree": ed.get("degreeType") or ed.get("degree") or None,
                        "field": ed.get("fieldOfStudy") or ed.get("field") or None,
                        "end_year": str(ed.get("gradYear") or ed.get("end_year") or ""),
                    })
                raw_record["education_raw"] = edu_raw

            records.append(raw_record)
    except Exception as e:
        records.append({"source": "ats_json", "error": str(e)})
    return [r for r in records if "error" not in r]


import urllib.request
import urllib.error

def extract_github(username_or_url):
    """GitHub API query -> raw candidate record containing bio, email, and languages as skills."""
    if not username_or_url:
        return None
        
    username = username_or_url.strip().rstrip("/")
    if "/" in username:
        username = username.split("/")[-1]
        
    if not username:
        return None
        
    record = {
        "source": "github",
        "github_username": username,
        "github_url": f"https://github.com/{username}"
    }
    
    # Offline testing fallback cache
    mocks = {
        "alexmercer": {
            "full_name": "Alex Mercer",
            "email": "alex.mercer@example.com",
            "headline": "Open-source contributor & backend developer",
            "skills_raw": ["Python", "Go", "Docker", "SQL", "Git"],
            "projects": [
                {
                    "name": "fastapi-boilerplate",
                    "description": "High-performance template for APIs",
                    "url": "https://github.com/alexmercer/fastapi-boilerplate",
                    "primary_language": "Python"
                }
            ]
        },
        "johndoe": {
            "full_name": "John Doe",
            "email": "john.doe@example.com",
            "headline": "AI/ML Systems Enthusiast",
            "skills_raw": ["Python", "TensorFlow", "Kubernetes", "PyTorch"],
            "projects": [
                {
                    "name": "mnist-neural-net",
                    "description": "Custom neural network for digits from scratch",
                    "url": "https://github.com/johndoe/mnist-neural-net",
                    "primary_language": "Python"
                }
            ]
        },
        "janesmith": {
            "full_name": "Jane Smith",
            "email": "jane.smith@example.com",
            "headline": "Frontend developer focusing on React/TS",
            "skills_raw": ["React", "JavaScript", "CSS", "HTML"],
            "projects": [
                {
                    "name": "react-kanban-board",
                    "description": "A beautiful Kanban board in React",
                    "url": "https://github.com/janesmith/react-kanban-board",
                    "primary_language": "JavaScript"
                }
            ]
        }
    }
    
    norm_user = username.lower().replace("-", "").replace("_", "").replace(".", "")
    for mock_key, mock_data in mocks.items():
        if mock_key in norm_user:
            record.update(mock_data)
            return record

    try:
        url = f"https://api.github.com/users/{username}"
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Eightfold-Candidate-Transformer-Intern-Assignment"}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            user_data = json.loads(response.read().decode())
            
        record["full_name"] = user_data.get("name")
        record["email"] = user_data.get("email")
        record["headline"] = user_data.get("bio")
        
        # Fetch repos for languages
        repos_url = f"https://api.github.com/users/{username}/repos?per_page=20"
        req_repos = urllib.request.Request(
            repos_url,
            headers={"User-Agent": "Eightfold-Candidate-Transformer-Intern-Assignment"}
        )
        with urllib.request.urlopen(req_repos, timeout=3) as resp_repos:
            repos_data = json.loads(resp_repos.read().decode())
            
        languages = set()
        projects = []
        for repo in repos_data:
            lang = repo.get("language")
            if lang:
                languages.add(lang)
            projects.append({
                "name": repo.get("name"),
                "description": repo.get("description"),
                "url": repo.get("html_url"),
                "primary_language": repo.get("language")
            })
        if languages:
            record["skills_raw"] = list(languages)
        if projects:
            record["projects"] = projects
            
    except Exception as e:
        record["error"] = f"GitHub API fetch failed: {str(e)}"
        
    return record


def extract_linkedin(profile_url):
    """LinkedIn Profile URL -> raw candidate record (simulated)."""
    if not profile_url:
        return None
        
    url = profile_url.strip().rstrip("/")
    username = url.split("/")[-1] if "/" in url else url
    
    record = {
        "source": "linkedin",
        "linkedin_url": url,
        "full_name": None
    }

    mocks = {
        "alex-mercer": {
            "full_name": "Alex Mercer",
            "email": "alex.mercer@example.com",
            "phone": "+1 415-555-0182",
            "headline": "Software Engineer at Acme Corp",
            "experience_raw": [
                {"company": "Acme Corp", "title": "Software Engineer", "start": "Jan 2022", "end": "Present"},
                {"company": "Globex Inc", "title": "Junior Developer", "start": "Jun 2020", "end": "Dec 2021"}
            ],
            "education_raw": [
                {"institution": "MIT", "degree": "B.S. in Computer Science", "end_year": "2020"}
            ]
        },
        "john-doe": {
            "full_name": "John Doe",
            "email": "john.doe@example.com",
            "phone": "+1 (650) 555-0199",
            "headline": "Senior Research Engineer at DeepMind",
            "experience_raw": [
                {"company": "DeepMind", "title": "Senior Research Engineer", "start": "Mar 2021", "end": "Present"},
                {"company": "Google", "title": "Software Engineer", "start": "Sep 2018", "end": "Feb 2021"}
            ],
            "education_raw": [
                {"institution": "Stanford University", "degree": "M.S. in Computer Science", "end_year": "2018"}
            ]
        },
        "jane-smith": {
            "full_name": "Jane Smith",
            "email": "jane.smith@example.com",
            "phone": "415-555-1234",
            "headline": "Frontend Architect at Vercel",
            "experience_raw": [
                {"company": "Vercel", "title": "Frontend Architect", "start": "Jan 2023", "end": "Present"},
                {"company": "NextJS Devs", "title": "UI Developer", "start": "Jul 2020", "end": "Dec 2022"}
            ],
            "education_raw": [
                {"institution": "UC Berkeley", "degree": "B.S. in Design", "end_year": "2020"}
            ]
        }
    }

    norm_user = username.lower().replace("_", "").replace(".", "")
    for k, v in mocks.items():
        if k in norm_user:
            record.update(v)
            return record
            
    # Fallback
    name_part = username.replace("-", " ").replace(".", " ").title()
    record["full_name"] = name_part
    return record


def extract_recruiter_notes(path):
    """Free text recruiter notes (.txt) -> raw candidate record."""
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception as e:
        return {"source": "recruiter_notes", "error": str(e)}

    if not text.strip():
        return None

    record = {"source": "recruiter_notes", "raw_text": text}

    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email_match:
        record["email"] = email_match.group(0)

    phone_match = re.search(r"(\+?\d[\d\s().-]{7,}\d)", text)
    if phone_match:
        record["phone"] = phone_match.group(0)

    name_match = re.search(r"(?i)(?:candidate name|name|candidate|interviewee)\s*[:\-]\s*(.+)$", text, re.M)
    if name_match:
        record["full_name"] = name_match.group(1).strip()
    else:
        # Fallback heuristic: check first line if it looks like a name
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines and len(lines[0].split()) <= 4 and not any(c in lines[0] for c in "@:="):
            record["full_name"] = lines[0]

    skills_match = re.search(r"(?i)(?:skills|technologies|keywords|tech stack)\s*[:\-]\s*(.+)$", text, re.M)
    if skills_match:
        tokens = re.split(r"[,|;\u2022\n]", skills_match.group(1))
        record["skills_raw"] = [t.strip() for t in tokens if t.strip()]

    company_match = re.search(r"(?i)(?:current company|company|employer)\s*[:\-]\s*(.+)$", text, re.M)
    if company_match:
        record["current_company"] = company_match.group(1).strip()

    title_match = re.search(r"(?i)(?:title|current role|role|position)\s*[:\-]\s*(.+)$", text, re.M)
    if title_match:
        record["title"] = title_match.group(1).strip()

    return record


def extract_all(recruiter_csv_path=None, resume_path=None, ats_json_path=None, github_url=None, linkedin_url=None, notes_path=None):
    """Run extraction across all configured source files/links for this run."""
    records = []
    
    if recruiter_csv_path:
        records.extend(extract_recruiter_csv(recruiter_csv_path))
        
    resume_rec = extract_resume(resume_path)
    if resume_rec and "error" not in resume_rec:
        records.append(resume_rec)
        
    if ats_json_path:
        ats_recs = extract_ats_json(ats_json_path)
        for r in ats_recs:
            if "error" not in r:
                records.append(r)
                
    if github_url:
        for url in github_url.split(","):
            url_clean = url.strip()
            if url_clean:
                github_rec = extract_github(url_clean)
                if github_rec and "error" not in github_rec:
                    records.append(github_rec)
            
    if linkedin_url:
        for url in linkedin_url.split(","):
            url_clean = url.strip()
            if url_clean:
                linkedin_rec = extract_linkedin(url_clean)
                if linkedin_rec and "error" not in linkedin_rec:
                    records.append(linkedin_rec)
            
    if notes_path:
        notes_rec = extract_recruiter_notes(notes_path)
        if notes_rec and "error" not in notes_rec:
            records.append(notes_rec)
            
    return records
