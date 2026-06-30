"""
validate.py
-----------
Stage 7 (validate). Builds a minimal JSON Schema dynamically from the
config (so we validate against *what was requested*, not the full
canonical schema -- a projection that legitimately dropped fields
shouldn't fail validation for missing fields it was told to omit).

Validation failures are collected and returned, not raised -- callers
decide whether to abort or just log per the "robust" constraint
(missing/garbage data must not crash the run).
"""

from jsonschema import Draft7Validator

TYPE_MAP = {
    "string": "string",
    "number": "number",
    "object": "object",
    "array": "array",
    "string[]": "array",
}


def build_schema(config):
    props = {}
    required = []
    for f in config.get("fields", []):
        name = f["path"]
        jtype = TYPE_MAP.get(f.get("type"), None)
        prop_schema = {"type": [jtype, "null"]} if jtype else {}
        props[name] = prop_schema
        if f.get("required"):
            required.append(name)
    if config.get("include_confidence", True):
        props["overall_confidence"] = {"type": "number"}
    if config.get("include_provenance", True):
        props["provenance"] = {"type": "array"}
    return {"type": "object", "properties": props, "required": required}


def validate_output(output, config):
    """Returns (is_valid: bool, errors: list[str]). Never raises."""
    try:
        schema = build_schema(config)
        validator = Draft7Validator(schema)
        errors = [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                  for e in validator.iter_errors(output)]
        return (len(errors) == 0, errors)
    except Exception as e:
        return (False, [f"validation engine error: {e}"])


def validate_all(outputs, config):
    results = []
    for out in outputs:
        ok, errs = validate_output(out, config)
        results.append({"candidate_id": out.get("candidate_id"), "valid": ok, "errors": errs})
    return results
