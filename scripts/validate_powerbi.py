"""Validate generated PBIR files against Microsoft's published JSON schemas."""
import argparse
import json
from pathlib import Path
from urllib.request import urlopen

from jsonschema import Draft7Validator
from referencing import Registry, Resource


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    cache = {}

    def retrieve(uri):
        if not uri.startswith("https://developer.microsoft.com/json-schemas/"):
            raise ValueError("Unexpected schema origin: " + uri)
        if uri not in cache:
            with urlopen(uri, timeout=30) as response:
                cache[uri] = json.load(response)
        return Resource.from_contents(cache[uri])

    registry = Registry(retrieve=retrieve)
    checked, errors = [], []
    for path in sorted(args.project.rglob("*")):
        if path.suffix not in (".json", ".pbip", ".pbir", ".pbism"):
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if "$schema" not in value:
            continue
        schema = retrieve(value["$schema"]).contents
        validator = Draft7Validator(schema, registry=registry)
        checked.append(path.relative_to(args.project).as_posix())
        for error in validator.iter_errors(value):
            errors.append({"file": checked[-1], "path": list(error.path), "message": error.message})
    evidence = {"checked_files": checked, "schema_count": len(cache), "errors": errors,
                "scope": "JSON schema validation only; does not execute M/DAX or render Power BI visuals"}
    (args.project / "schema-validation.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
