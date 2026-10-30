"""Load and structurally check OpenAPI 3.0.x documents from local files.

Only local files are read. YAML is parsed with ``yaml.safe_load`` so no
specification content is ever executed, and ``$ref`` values are never
followed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_EXTENSIONS = (".yaml", ".yml", ".json")
SUPPORTED_VERSION = re.compile(r"3\.0\.\d+")


class SpecError(Exception):
    """The specification cannot be loaded or is not a supported OpenAPI document."""


def load_spec(path: str | Path) -> dict[str, Any]:
    """Read, parse and validate the specification at ``path``."""
    path = Path(path)
    if not path.exists():
        raise SpecError(f"Specification file not found: {path}")
    if not path.is_file():
        raise SpecError(f"Specification path is not a file: {path}")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise SpecError(
            f"Unsupported file extension {path.suffix!r} for {path}: use .yaml, .yml or .json"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SpecError(f"Specification is not valid UTF-8 text: {path}") from exc
    except OSError as exc:
        raise SpecError(f"Could not read {path}: {exc.strerror or exc}") from exc

    if suffix == ".json":
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecError(
                f"Malformed JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno})"
            ) from exc
    else:
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecError(f"Malformed YAML in {path}: {exc}") from exc

    validate_spec(document)
    return document


def validate_spec(document: Any) -> None:
    """Check the top-level structure the generator relies on."""
    if not isinstance(document, dict):
        raise SpecError("The specification must be a mapping (JSON object) at the top level")
    if "swagger" in document:
        raise SpecError(
            f"Swagger/OpenAPI 2.0 documents are not supported (found swagger: "
            f"{document['swagger']!r}); only OpenAPI 3.0.x is supported"
        )
    version = document.get("openapi")
    if version is None:
        raise SpecError("Missing 'openapi' version field; only OpenAPI 3.0.x is supported")
    if not isinstance(version, str) or not SUPPORTED_VERSION.fullmatch(version):
        raise SpecError(
            f"Unsupported OpenAPI version {version!r}; only 3.0.x (for example '3.0.3') is "
            f"supported. In YAML, quote the version if needed: openapi: \"3.0.3\""
        )

    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise SpecError("The specification must contain a 'paths' mapping")
    for key, path_item in paths.items():
        if not isinstance(key, str) or not key.startswith("/"):
            raise SpecError(f"Path keys must be strings starting with '/', found {key!r}")
        if not isinstance(path_item, dict):
            raise SpecError(f"Path item {key!r} must be a mapping")
