import json

import pytest

from qa_platform.openapi_loader import SpecError, load_spec, validate_spec

MINIMAL = {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {}}


def test_loads_yaml(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths:\n  /a:\n    get: {}\n")
    assert load_spec(path)["paths"] == {"/a": {"get": {}}}


def test_loads_yml_extension(tmp_path):
    path = tmp_path / "spec.yml"
    path.write_text("openapi: 3.0.0\npaths: {}\n")
    assert load_spec(path)["openapi"] == "3.0.0"


def test_loads_json(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(MINIMAL))
    assert load_spec(path) == MINIMAL


def test_missing_file(tmp_path):
    with pytest.raises(SpecError, match="not found"):
        load_spec(tmp_path / "nope.yaml")


def test_directory_is_rejected(tmp_path):
    folder = tmp_path / "spec.yaml"
    folder.mkdir()
    with pytest.raises(SpecError, match="not a file"):
        load_spec(folder)


def test_unknown_extension(tmp_path):
    path = tmp_path / "spec.txt"
    path.write_text(json.dumps(MINIMAL))
    with pytest.raises(SpecError, match="extension"):
        load_spec(path)


def test_malformed_yaml(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("openapi: 3.0.3\npaths: [unclosed\n")
    with pytest.raises(SpecError, match="Malformed YAML"):
        load_spec(path)


def test_malformed_json_reports_position(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text('{"openapi": "3.0.3",\n "paths": }')
    with pytest.raises(SpecError, match=r"Malformed JSON .*line 2"):
        load_spec(path)


def test_yaml_python_tags_are_not_executed(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text("openapi: !!python/object/apply:os.system ['echo unsafe']\npaths: {}\n")
    with pytest.raises(SpecError, match="Malformed YAML"):
        load_spec(path)


def test_non_utf8_file(tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_bytes(b"openapi: '3.0.3'\ntitle: \xff\xfe\n")
    with pytest.raises(SpecError, match="UTF-8"):
        load_spec(path)


@pytest.mark.parametrize("version", ["3.0.0", "3.0.3", "3.0.10"])
def test_supported_versions(version):
    validate_spec({**MINIMAL, "openapi": version})


@pytest.mark.parametrize("version", ["3.1.0", "2.0", "3.0", "4.0.0", "3.0.3-rc1", 3.0])
def test_unsupported_versions(version):
    with pytest.raises(SpecError, match="Unsupported OpenAPI version"):
        validate_spec({**MINIMAL, "openapi": version})


def test_swagger_2_is_rejected():
    with pytest.raises(SpecError, match="Swagger"):
        validate_spec({"swagger": "2.0", "paths": {}})


def test_missing_version():
    with pytest.raises(SpecError, match="Missing 'openapi'"):
        validate_spec({"paths": {}})


@pytest.mark.parametrize("document", [None, [], "openapi: 3.0.3", 42])
def test_top_level_must_be_mapping(document):
    with pytest.raises(SpecError, match="top level"):
        validate_spec(document)


@pytest.mark.parametrize("paths", [None, [], "x"])
def test_paths_must_be_mapping(paths):
    document = {"openapi": "3.0.3"} if paths is None else {"openapi": "3.0.3", "paths": paths}
    with pytest.raises(SpecError, match="'paths' mapping"):
        validate_spec(document)


def test_path_keys_must_start_with_slash():
    with pytest.raises(SpecError, match="starting with '/'"):
        validate_spec({**MINIMAL, "paths": {"items": {}}})


def test_path_item_must_be_mapping():
    with pytest.raises(SpecError, match="must be a mapping"):
        validate_spec({**MINIMAL, "paths": {"/items": ["get"]}})
