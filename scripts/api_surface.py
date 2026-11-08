"""
Prints a compact map of every API endpoint from the OpenAPI document:
method, path, auth, header/query params, request body fields, response fields.

Usage (API running on :8000):
    curl -s http://localhost:8000/openapi.json | python scripts/api_surface.py > api_surface.txt
"""

import json
import sys
from typing import Any

MAX_DEPTH = 3


def _ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def _resolve(schema: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        return spec["components"]["schemas"][_ref_name(schema["$ref"])]
    return schema


def _type(schema: dict[str, Any], spec: dict[str, Any], depth: int) -> str:
    if "$ref" in schema:
        target = _resolve(schema, spec)
        if "enum" in target:
            return "enum(" + "|".join(str(v) for v in target["enum"]) + ")"
        return _object(target, spec, depth + 1, _ref_name(schema["$ref"]))
    if "enum" in schema:
        return "enum(" + "|".join(str(v) for v in schema["enum"]) + ")"
    for key in ("anyOf", "oneOf"):
        if key in schema:
            parts = [_type(part, spec, depth) for part in schema[key]]
            optional = "null" in parts
            parts = [part for part in parts if part != "null"]
            # Decimal fields are documented as number|string-with-pattern: show just the number.
            if any(part.startswith("number") for part in parts):
                parts = [part for part in parts if not part.startswith("string(pattern=^(?!^[-+.]*$)")]
            return "|".join(parts) + ("?" if optional else "")
    if "allOf" in schema:
        return "&".join(_type(part, spec, depth) for part in schema["allOf"])
    kind = schema.get("type", "any")
    if kind == "array":
        return f"list[{_type(schema.get('items', {}), spec, depth)}]"
    if kind == "object" and "properties" in schema:
        return _object(schema, spec, depth + 1, "")
    extras = []
    if "format" in schema:
        extras.append(schema["format"])
    if "pattern" in schema:
        extras.append(f"pattern={schema['pattern']}")
    for bound in ("minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum"):
        if bound in schema:
            extras.append(f"{bound}={schema[bound]}")
    return kind + (f"({', '.join(extras)})" if extras else "")


def _object(schema: dict[str, Any], spec: dict[str, Any], depth: int, name: str) -> str:
    if depth > MAX_DEPTH:
        return name or "object"
    required = set(schema.get("required", []))
    fields = []
    for field, sub in schema.get("properties", {}).items():
        mark = "*" if field in required else ""
        fields.append(f"{field}{mark}: {_type(sub, spec, depth)}")
    return (name or "") + "{" + ", ".join(fields) + "}"


def _body(op: dict[str, Any], spec: dict[str, Any]) -> str:
    content = op.get("requestBody", {}).get("content", {})
    for media, payload in content.items():
        schema = payload.get("schema", {})
        return f"{media.split('/')[-1]} " + _type(schema, spec, 0)
    return ""


def _response(op: dict[str, Any], spec: dict[str, Any]) -> str:
    for code, payload in op.get("responses", {}).items():
        if code.startswith("2"):
            content = payload.get("content", {})
            for media, body in content.items():
                if "json" in media:
                    return f"{code} " + _type(body.get("schema", {}), spec, 0)
                return f"{code} {media}"
            return code
    return ""


def main() -> None:
    spec = json.load(sys.stdin)
    for path, methods in sorted(spec["paths"].items()):
        for method, op in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            params = op.get("parameters", [])
            headers = [p["name"] + ("*" if p.get("required") else "") for p in params if p["in"] == "header"]
            queries = [p["name"] + ("*" if p.get("required") else "") for p in params if p["in"] == "query"]
            print(f"{method.upper()} {path}  [{'auth' if op.get('security') else 'public'}]")
            if headers:
                print(f"    headers: {', '.join(headers)}")
            if queries:
                print(f"    query:   {', '.join(queries)}")
            body = _body(op, spec)
            if body:
                print(f"    body:    {body}")
            response = _response(op, spec)
            if response:
                print(f"    returns: {response}")


if __name__ == "__main__":
    main()
