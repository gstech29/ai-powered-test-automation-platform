"""Turn the supported subset of an OpenAPI 3.0.x document into Pytest source.

Generation has two steps:

* ``analyse_spec`` decides, for every operation, either what one test will
  send and expect, or why the operation is skipped.
* ``render_module`` writes those plans out as Python source.

Every value taken from the specification reaches the generated source only
through ``repr()``, so it is always a valid, inert Python literal.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from qa_platform import __version__
from qa_platform.openapi_loader import SpecError

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARAMETER_LOCATIONS = ("path", "query", "header", "cookie")
DEFAULT_STYLES = {"path": "simple", "query": "form"}
SCALAR_TYPES = {"string", "integer", "number", "boolean"}
COMPOSITION_KEYWORDS = ("allOf", "oneOf", "anyOf", "not")
SUCCESS_STATUS = re.compile(r"2\d\d")
PATH_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


@dataclass(frozen=True)
class OperationTest:
    """One generated test: a single request and the statuses it may return."""

    name: str
    method: str
    path_template: str
    url_path: str
    query: tuple[tuple[str, str], ...]
    expected_statuses: tuple[int, ...]


@dataclass(frozen=True)
class SkippedOperation:
    """An operation the generator cannot test, with the reason."""

    method: str
    path: str
    reason: str


@dataclass(frozen=True)
class Analysis:
    tests: tuple[OperationTest, ...]
    skipped: tuple[SkippedOperation, ...]


class _Unsupported(Exception):
    """This operation (or parameter) is outside the supported subset."""


def analyse_spec(spec: dict[str, Any]) -> Analysis:
    """Plan one test per supported GET operation and explain every skip.

    Operations are visited in document order, so the result is deterministic.
    Structurally invalid documents raise ``SpecError``.
    """
    global_security = spec.get("security")
    tests: list[OperationTest] = []
    skipped: list[SkippedOperation] = []
    used_names: set[str] = set()

    for path, path_item in spec["paths"].items():
        if "$ref" in path_item:
            skipped.append(
                SkippedOperation("*", path, "path item $ref requires reference resolution, which is not supported")
            )
            continue
        for method in HTTP_METHODS:
            if method not in path_item:
                continue
            label = method.upper()
            if method != "get":
                skipped.append(SkippedOperation(label, path, f"HTTP method {label} is not supported yet (GET only)"))
                continue
            operation = path_item[method]
            if not isinstance(operation, dict):
                raise SpecError(f"Operation {label} {path} must be a mapping")
            try:
                test = _plan_get(path, path_item, operation, global_security, used_names)
            except _Unsupported as exc:
                skipped.append(SkippedOperation(label, path, str(exc)))
            else:
                used_names.add(test.name)
                tests.append(test)

    return Analysis(tuple(tests), tuple(skipped))


def _plan_get(
    path: str,
    path_item: dict[str, Any],
    operation: dict[str, Any],
    global_security: Any,
    used_names: set[str],
) -> OperationTest:
    where = f"GET {path}"
    if _requires_auth(operation.get("security", global_security), where):
        raise _Unsupported("requires authentication; security requirements are not supported yet")
    if "requestBody" in operation:
        raise _Unsupported("request bodies are not supported")

    expected = _expected_statuses(operation.get("responses"))

    path_values: dict[str, str] = {}
    query: list[tuple[str, str]] = []
    for param in _merge_parameters(path_item.get("parameters"), operation.get("parameters"), where):
        value = _parameter_value(param)
        if value is None:
            continue
        if param["in"] == "path":
            path_values[param["name"]] = value
        else:
            query.append((param["name"], value))

    for placeholder in PATH_PLACEHOLDER.findall(path):
        if placeholder not in path_values:
            raise _Unsupported(f"path placeholder {{{placeholder}}} has no matching path parameter")
    url_path = PATH_PLACEHOLDER.sub(lambda m: quote(path_values[m.group(1)], safe=""), path)

    return OperationTest(
        name=_test_name(operation.get("operationId"), path, used_names),
        method="GET",
        path_template=path,
        url_path=url_path,
        query=tuple(query),
        expected_statuses=expected,
    )


def _requires_auth(security: Any, where: str) -> bool:
    if security is None:
        return False
    if not isinstance(security, list):
        raise SpecError(f"'security' for {where} must be a list")
    # An empty requirement object ({}) means anonymous access is allowed.
    return bool(security) and all(requirement != {} for requirement in security)


def _expected_statuses(responses: Any) -> tuple[int, ...]:
    if not isinstance(responses, dict) or not responses:
        raise _Unsupported("no responses are documented")
    statuses = sorted({int(str(code)) for code in responses if SUCCESS_STATUS.fullmatch(str(code))})
    if not statuses:
        documented = ", ".join(str(code) for code in responses)
        raise _Unsupported(f"no explicitly documented numeric 2xx response (documented: {documented})")
    return tuple(statuses)


def _merge_parameters(path_level: Any, operation_level: Any, where: str) -> list[dict[str, Any]]:
    """Combine path-item and operation parameters; the operation wins on (name, in)."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for source in (path_level, operation_level):
        if source is None:
            continue
        if not isinstance(source, list):
            raise SpecError(f"'parameters' for {where} must be a list")
        for param in source:
            if not isinstance(param, dict):
                raise SpecError(f"Each parameter for {where} must be a mapping")
            if "$ref" in param:
                raise _Unsupported(
                    f"parameter $ref {param['$ref']!r} requires reference resolution, which is not supported"
                )
            name, location = param.get("name"), param.get("in")
            if not isinstance(name, str) or not name or location not in PARAMETER_LOCATIONS:
                raise SpecError(
                    f"Invalid parameter for {where}: each parameter needs a non-empty 'name' "
                    f"and 'in' set to one of {', '.join(PARAMETER_LOCATIONS)}"
                )
            merged[(name, location)] = param
    return list(merged.values())


def _parameter_value(param: dict[str, Any]) -> str | None:
    """Return the value to send as text, or None when an optional parameter is omitted."""
    name, location = param["name"], param["in"]
    required = location == "path" or param.get("required") is True
    try:
        if location not in DEFAULT_STYLES:
            raise _Unsupported(f"{location} parameters are not supported")
        _check_simple_serialisation(param)
        value = _first_value(param)
    except _Unsupported as exc:
        if required:
            raise _Unsupported(f"required {location} parameter {name!r}: {exc}") from None
        return None
    if value is None and required:
        raise _Unsupported(
            f"required {location} parameter {name!r} has no example or default value"
        )
    return value


def _check_simple_serialisation(param: dict[str, Any]) -> None:
    location = param["in"]
    if "content" in param:
        raise _Unsupported("'content' serialisation is not supported")
    style = param.get("style", DEFAULT_STYLES[location])
    if style != DEFAULT_STYLES[location]:
        raise _Unsupported(f"style {style!r} is not supported")
    if param.get("allowReserved") is True:
        raise _Unsupported("allowReserved is not supported")
    schema = param.get("schema", {})
    if not isinstance(schema, dict):
        raise _Unsupported("schema must be a mapping")
    if "$ref" in schema:
        raise _Unsupported(f"schema $ref {schema['$ref']!r} requires reference resolution, which is not supported")
    for keyword in COMPOSITION_KEYWORDS:
        if keyword in schema:
            raise _Unsupported(f"schema composition ({keyword}) is not supported")
    schema_type = schema.get("type")
    if schema_type is not None and schema_type not in SCALAR_TYPES:
        raise _Unsupported(f"schema type {schema_type!r} is not supported (scalar types only)")


def _first_value(param: dict[str, Any]) -> str | None:
    """Parameter example, then schema example, then schema default."""
    schema = param.get("schema", {})
    for source, key in ((param, "example"), (schema, "example"), (schema, "default")):
        if source.get(key) is not None:
            return _as_text(source[key])
    return None


def _as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _Unsupported(f"value {value!r} is not a finite number")
        return repr(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise _Unsupported("value is not encodable as UTF-8") from None
        return value
    raise _Unsupported(f"value of type {type(value).__name__} is not a scalar")


def _snake_case(text: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()


def _test_name(operation_id: Any, path: str, used: set[str]) -> str:
    base = _snake_case(operation_id) if isinstance(operation_id, str) else ""
    if not base:
        base = _snake_case(f"get {path}")
    name = candidate = f"test_{base}"
    suffix = 2
    while candidate in used:
        candidate = f"{name}_{suffix}"
        suffix += 1
    return candidate


_MODULE_DOCSTRING = '''\
"""API tests generated by qa-platform {version}. Do not edit by hand; regenerate instead.

Each test sends one GET request and checks only that the response status is one
of the operation's documented 2xx statuses. Response bodies and schemas are not
validated. Set API_BASE_URL to the base URL of the API under test.
"""
'''

_MODULE_PRELUDE = '''\
import os

import pytest
import requests

TIMEOUT_SECONDS = 10


@pytest.fixture(scope="session")
def base_url():
    """Base URL of the API under test, taken only from API_BASE_URL."""
    url = os.environ.get("API_BASE_URL", "").strip()
    if not url:
        pytest.fail(
            "API_BASE_URL is not set. Point it at the API under test, for example: "
            "export API_BASE_URL=http://127.0.0.1:8000",
            pytrace=False,
        )
    if not url.startswith(("http://", "https://")):
        pytest.fail(f"API_BASE_URL must start with http:// or https://, got {url!r}", pytrace=False)
    return url.rstrip("/")


def _assert_documented_status(response, operation, expected):
    assert response.status_code in expected, (
        f"{operation} returned HTTP {response.status_code}, but the specification "
        f"documents only {', '.join(map(str, expected))}. "
        f"Response body starts with: {response.text[:200]!r}"
    )
'''


def render_module(analysis: Analysis, source_name: str) -> str:
    """Render the planned tests as a Pytest module. Identical input gives identical output."""
    lines = [_MODULE_DOCSTRING.format(version=__version__).rstrip("\n"), ""]
    # repr() never contains a newline, so these comments cannot break out.
    lines.append(f"# Source specification: {source_name!r}")
    if analysis.skipped:
        lines.append("# Operations skipped by the generator:")
        for item in analysis.skipped:
            lines.append(f"#   {item.method + ' ' + item.path!r}: {item.reason!r}")
    lines.append("")
    lines.append(_MODULE_PRELUDE.rstrip("\n"))
    for test in analysis.tests:
        lines.extend(_render_test(test))
    return "\n".join(lines) + "\n"


def _render_test(test: OperationTest) -> list[str]:
    lines = [
        "",
        "",
        f"def {test.name}(base_url):",
        "    response = requests.get(",
        f"        base_url + {test.url_path!r},",
    ]
    if test.query:
        lines.append(f"        params={dict(test.query)!r},")
    lines += [
        "        timeout=TIMEOUT_SECONDS,",
        "        allow_redirects=False,",
        "    )",
        "    _assert_documented_status(",
        "        response,",
        f"        operation={test.method + ' ' + test.path_template!r},",
        f"        expected={test.expected_statuses!r},",
        "    )",
    ]
    return lines
