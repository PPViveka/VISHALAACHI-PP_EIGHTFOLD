"""
Canonical output schema for a candidate profile, and the JSON Schema
used to validate the *projected* output (i.e. after the runtime config
has reshaped it). Because the config can select/rename/drop fields,
validate.py builds a schema dynamically based on which fields survive
projection -- this module just holds the canonical (full) shape.
"""

CANONICAL_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "full_name": {"type": "string"},
        "emails": {"type": "array", "items": {"type": "string"}},
        "phones": {"type": "array", "items": {"type": "string"}},
        "location": {
            "type": ["object", "null"],
            "properties": {
                "city": {"type": ["string", "null"]},
                "region": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
            },
        },
        "links": {
            "type": "object",
            "properties": {
                "linkedin": {"type": ["string", "null"]},
                "github": {"type": ["string", "null"]},
                "portfolio": {"type": ["string", "null"]},
                "other": {"type": "array", "items": {"type": "string"}},
            },
        },
        "headline": {"type": ["string", "null"]},
        "years_experience": {"type": ["number", "null"]},
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": ["string", "null"]},
                    "title": {"type": ["string", "null"]},
                    "start": {"type": ["string", "null"]},
                    "end": {"type": ["string", "null"]},
                    "summary": {"type": ["string", "null"]},
                },
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": ["string", "null"]},
                    "degree": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]},
                    "end_year": {"type": ["number", "null"]},
                },
            },
        },
        "provenance": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "source": {"type": "string"},
                    "method": {"type": "string"},
                },
            },
        },
        "certifications": {
            "type": "array",
            "items": {"type": "string"}
        },
        "languages": {
            "type": "array",
            "items": {"type": "string"}
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                    "primary_language": {"type": ["string", "null"]}
                }
            }
        },
        "overall_confidence": {"type": "number"},
    },
    "required": ["candidate_id", "full_name"],
}

# Canonical skill vocabulary: messy alias -> canonical name.
# Small curated map; anything unmatched is title-cased and kept as-is
# (never invented, never dropped silently).
SKILL_ALIASES = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "py": "Python",
    "python": "Python",
    "python3": "Python",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "aws": "AWS",
    "amazon web services": "AWS",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "docker": "Docker",
    "sql": "SQL",
    "c++": "C++",
    "cpp": "C++",
    "golang": "Go",
    "go": "Go",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "pandas": "pandas",
    "numpy": "NumPy",
    "django": "Django",
    "flask": "Flask",
    "html": "HTML",
    "css": "CSS",
    "git": "Git",
}
