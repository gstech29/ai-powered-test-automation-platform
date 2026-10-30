import ast
import copy
from pathlib import Path

import pytest

from qa_platform.openapi_loader import SpecError, load_spec
from qa_platform.test_generator import analyse_spec, render_module

REPO_ROOT = Path(__file__).resolve().parents[1]
OK = {"200": {"description": "ok"}}


def make_spec(paths, **extra):
    return {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": paths, **extra}


def only_test(spec):
    analysis = analyse_spec(spec)
    assert analysis.skipped == ()
    assert len(analysis.tests) == 1
    return analysis.tests[0]


def only_skip_reason(spec):
    analysis = analyse_spec(spec)
    assert analysis.tests == ()
    assert len(analysis.skipped) == 1
    return analysis.skipped[0].reason


def query_param(name, **fields):
    return {"name": name, "in": "query", **fields}


def path_param(name, **fields):
    return {"name": name, "in": "path", "required": True, **fields}


# --- operation discovery -------------------------------------------------------


def test_discovers_get_operations_in_document_order():
    spec = make_spec({
        "/b": {"get": {"responses": OK}},
        "/a": {"get": {"responses": OK}},
    })
    assert [t.path_template for t in analyse_spec(spec).tests] == ["/b", "/a"]


def test_other_methods_are_reported_not_generated():
    spec = make_spec({"/items": {"get": {"responses": OK}, "post": {"responses": OK}, "delete": {}}})
    analysis = analyse_spec(spec)
    assert [t.method for t in analysis.tests] == ["GET"]
    assert [(s.method, s.reason) for s in analysis.skipped] == [
        ("POST", "HTTP method POST is not supported yet (GET only)"),
        ("DELETE", "HTTP method DELETE is not supported yet (GET only)"),
    ]


def test_path_item_ref_is_reported():
    spec = make_spec({"/items": {"$ref": "#/components/pathItems/items"}})
    assert "requires reference resolution" in only_skip_reason(spec)


def test_operation_must_be_mapping():
    with pytest.raises(SpecError, match="must be a mapping"):
        analyse_spec(make_spec({"/items": {"get": "nope"}}))


# --- expected status selection -------------------------------------------------


def test_expected_statuses_are_documented_numeric_2xx_only():
    responses = {"404": {}, "204": {}, "200": {}, "2XX": {}, "default": {}, "500": {}}
    test = only_test(make_spec({"/a": {"get": {"responses": responses}}}))
    assert test.expected_statuses == (200, 204)


def test_integer_status_keys_from_yaml_are_accepted():
    test = only_test(make_spec({"/a": {"get": {"responses": {200: {}, 202: {}}}}}))
    assert test.expected_statuses == (200, 202)


@pytest.mark.parametrize("responses", [{"2XX": {}}, {"default": {}}, {"404": {}, "500": {}}])
def test_skips_without_explicit_2xx(responses):
    reason = only_skip_reason(make_spec({"/a": {"get": {"responses": responses}}}))
    assert "no explicitly documented numeric 2xx response" in reason


@pytest.mark.parametrize("operation", [{}, {"responses": {}}, {"responses": None}])
def test_skips_without_responses(operation):
    assert only_skip_reason(make_spec({"/a": {"get": operation}})) == "no responses are documented"


# --- parameters ----------------------------------------------------------------


def test_parameter_example_wins_over_schema_example_and_default():
    param = query_param("q", example="param", schema={"type": "string", "example": "schema", "default": "dflt"})
    test = only_test(make_spec({"/a": {"get": {"parameters": [param], "responses": OK}}}))
    assert test.query == (("q", "param"),)


def test_schema_example_wins_over_default():
    param = query_param("q", schema={"type": "string", "example": "schema", "default": "dflt"})
    test = only_test(make_spec({"/a": {"get": {"parameters": [param], "responses": OK}}}))
    assert test.query == (("q", "schema"),)


def test_schema_default_is_used_last():
    param = query_param("limit", schema={"type": "integer", "default": 10})
    test = only_test(make_spec({"/a": {"get": {"parameters": [param], "responses": OK}}}))
    assert test.query == (("limit", "10"),)


@pytest.mark.parametrize(
    ("value", "text"),
    [(True, "true"), (False, "false"), (3, "3"), (1.5, "1.5"), ("x y", "x y")],
)
def test_scalar_values_become_text(value, text):
    param = query_param("v", example=value)
    test = only_test(make_spec({"/a": {"get": {"parameters": [param], "responses": OK}}}))
    assert test.query == (("v", text),)


def test_optional_parameter_without_value_is_omitted():
    params = [query_param("q", schema={"type": "string"}), query_param("page", required=False)]
    test = only_test(make_spec({"/a": {"get": {"parameters": params, "responses": OK}}}))
    assert test.query == ()


def test_required_query_parameter_without_value_skips_operation():
    params = [query_param("q", required=True, schema={"type": "string"})]
    reason = only_skip_reason(make_spec({"/a": {"get": {"parameters": params, "responses": OK}}}))
    assert reason == "required query parameter 'q' has no example or default value"


def test_path_parameter_without_value_skips_operation():
    spec = make_spec({"/items/{id}": {"get": {"parameters": [path_param("id")], "responses": OK}}})
    assert only_skip_reason(spec) == "required path parameter 'id' has no example or default value"


def test_undeclared_path_placeholder_skips_operation():
    spec = make_spec({"/items/{id}": {"get": {"responses": OK}}})
    assert only_skip_reason(spec) == "path placeholder {id} has no matching path parameter"


def test_path_values_are_percent_encoded():
    spec = make_spec({"/items/{id}": {"get": {"parameters": [path_param("id", example="a b/c?d")], "responses": OK}}})
    assert only_test(spec).url_path == "/items/a%20b%2Fc%3Fd"


def test_path_level_parameters_apply_and_operation_level_overrides():
    spec = make_spec({
        "/items/{id}": {
            "parameters": [path_param("id", example="path-level"), query_param("lang", example="en")],
            "get": {"parameters": [path_param("id", example="op-level")], "responses": OK},
        }
    })
    test = only_test(spec)
    assert test.url_path == "/items/op-level"
    assert test.query == (("lang", "en"),)


def test_same_name_in_different_locations_does_not_override():
    spec = make_spec({
        "/items/{id}": {
            "parameters": [path_param("id", example="1")],
            "get": {"parameters": [query_param("id", example="q")], "responses": OK},
        }
    })
    test = only_test(spec)
    assert (test.url_path, test.query) == ("/items/1", (("id", "q"),))


@pytest.mark.parametrize(
    ("param", "fragment"),
    [
        (query_param("q", required=True, example="x", style="spaceDelimited"), "style 'spaceDelimited'"),
        (query_param("q", required=True, content={"application/json": {}}), "'content' serialisation"),
        (query_param("q", required=True, example="x", allowReserved=True), "allowReserved"),
        (query_param("q", required=True, schema={"type": "array", "example": [1]}), "schema type 'array'"),
        (query_param("q", required=True, schema={"type": "object"}), "schema type 'object'"),
        (query_param("q", required=True, schema={"$ref": "#/components/schemas/Q"}), "schema $ref"),
        (query_param("q", required=True, schema={"oneOf": [{"type": "string"}]}), "composition (oneOf)"),
        (query_param("q", required=True, example={"a": 1}), "not a scalar"),
        (query_param("q", required=True, example=float("nan")), "not a finite number"),
        ({"name": "X-Trace", "in": "header", "required": True, "example": "1"}, "header parameters"),
        ({"name": "session", "in": "cookie", "required": True, "example": "1"}, "cookie parameters"),
    ],
)
def test_required_parameter_with_unsupported_serialisation_skips_operation(param, fragment):
    reason = only_skip_reason(make_spec({"/a": {"get": {"parameters": [param], "responses": OK}}}))
    assert reason.startswith(f"required {param['in']} parameter {param['name']!r}: ")
    assert fragment in reason


def test_optional_parameter_with_unsupported_serialisation_is_omitted():
    params = [
        query_param("tags", example=["a"], schema={"type": "array"}),
        {"name": "X-Trace", "in": "header", "example": "1"},
    ]
    assert only_test(make_spec({"/a": {"get": {"parameters": params, "responses": OK}}})).query == ()


def test_parameter_ref_skips_operation():
    spec = make_spec({"/a": {"get": {"parameters": [{"$ref": "#/components/parameters/P"}], "responses": OK}}})
    assert "requires reference resolution" in only_skip_reason(spec)


@pytest.mark.parametrize("params", ["nope", [{"in": "query"}], [{"name": "q", "in": "body"}], ["q"]])
def test_invalid_parameter_structure_is_an_error(params):
    with pytest.raises(SpecError):
        analyse_spec(make_spec({"/a": {"get": {"parameters": params, "responses": OK}}}))


# --- other unsupported features ------------------------------------------------


def test_operation_security_skips():
    spec = make_spec({"/a": {"get": {"security": [{"key": []}], "responses": OK}}})
    assert "requires authentication" in only_skip_reason(spec)


def test_global_security_skips_and_operation_can_opt_out():
    spec = make_spec(
        {"/a": {"get": {"responses": OK}}, "/b": {"get": {"security": [], "responses": OK}}},
        security=[{"key": []}],
    )
    analysis = analyse_spec(spec)
    assert [t.path_template for t in analysis.tests] == ["/b"]
    assert [s.path for s in analysis.skipped] == ["/a"]


def test_optional_security_allows_anonymous_access():
    spec = make_spec({"/a": {"get": {"security": [{}, {"key": []}], "responses": OK}}})
    assert only_test(spec).path_template == "/a"


def test_request_body_on_get_skips():
    spec = make_spec({"/a": {"get": {"requestBody": {"content": {}}, "responses": OK}}})
    assert only_skip_reason(spec) == "request bodies are not supported"


# --- names and rendering -------------------------------------------------------


def test_names_come_from_operation_id_or_path_and_are_unique():
    spec = make_spec({
        "/items/{item_id}": {"get": {"operationId": "getItemByID", "parameters": [path_param("item_id", example=1)], "responses": OK}},
        "/items": {"get": {"responses": OK}},
        "/other": {"get": {"operationId": "get-item-by-id", "responses": OK}},
        "/": {"get": {"operationId": "!!!", "responses": OK}},
    })
    assert [t.name for t in analyse_spec(spec).tests] == [
        "test_get_item_by_id",
        "test_get_items",
        "test_get_item_by_id_2",
        "test_get",
    ]


def test_rendered_module_is_valid_python_with_expected_tests():
    spec = load_spec(REPO_ROOT / "examples" / "sample-api.yaml")
    source = render_module(analyse_spec(spec), "sample-api.yaml")
    tree = ast.parse(source)
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert names == ["base_url", "_assert_documented_status", "test_get_health", "test_list_items", "test_get_item"]
    assert "params={'limit': '2'}" in source
    assert "base_url + '/items/item-001'" in source
    assert "timeout=TIMEOUT_SECONDS" in source
    assert "api.example.invalid" not in source  # servers are never targeted


def test_generation_is_deterministic():
    spec = load_spec(REPO_ROOT / "examples" / "sample-api.yaml")
    first = render_module(analyse_spec(spec), "sample-api.yaml")
    second = render_module(analyse_spec(copy.deepcopy(spec)), "sample-api.yaml")
    assert first == second


def test_hostile_strings_are_inert_literals():
    nasty = "x'\"\"\"\n) ; import os; os.system('boom') #\\{}"
    spec = make_spec({
        "/items/{id}": {"get": {"parameters": [path_param("id", example=nasty), query_param(nasty, example=nasty)], "responses": OK}},
        "/" + nasty: {"post": {}},
    })
    analysis = analyse_spec(spec)
    source = render_module(analysis, nasty + ".yaml")
    tree = ast.parse(source)
    imports = [alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names]
    assert imports == ["os", "pytest", "requests"]
    assert not any(isinstance(node, ast.Attribute) and node.attr == "system" for node in ast.walk(tree))
    assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)][-1] == "test_get_items_id"
    # The values survive unchanged, as data only.
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
    assert analysis.tests[0].url_path in literals
    assert {nasty: nasty} == next(
        ast.literal_eval(kw.value) for node in ast.walk(tree) if isinstance(node, ast.Call)
        for kw in node.keywords if kw.arg == "params"
    )


def test_committed_example_matches_generator_output():
    """generated_tests/ must hold real generator output, not hand-written tests."""
    spec = load_spec(REPO_ROOT / "examples" / "sample-api.yaml")
    expected = render_module(analyse_spec(spec), "sample-api.yaml")
    committed = (REPO_ROOT / "generated_tests" / "test_sample_api.py").read_text(encoding="utf-8")
    assert committed == expected, "Regenerate with: qa-platform generate examples/sample-api.yaml --output generated_tests/test_sample_api.py --force"
