import json
import subprocess
import sys
from pathlib import Path

import pytest

from qa_platform.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SPEC = REPO_ROOT / "examples" / "sample-api.yaml"


def write_json_spec(path, paths):
    path.write_text(json.dumps({"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": paths}))
    return path


def test_generate_writes_file_and_reports_skips(tmp_path, capsys):
    output = tmp_path / "nested" / "dir" / "test_sample.py"
    assert main(["generate", str(SAMPLE_SPEC), "--output", str(output)]) == 0

    captured = capsys.readouterr()
    assert f"Generated 3 test(s) in {output}" in captured.out
    assert "Skipped POST /items: HTTP method POST is not supported yet (GET only)" in captured.err
    assert "Skipped GET /reports/summary: requires authentication" in captured.err
    compile(output.read_text(encoding="utf-8"), str(output), "exec")


def test_refuses_to_overwrite_without_force(tmp_path, capsys):
    output = tmp_path / "test_out.py"
    output.write_text("# keep me\n")
    assert main(["generate", str(SAMPLE_SPEC), "-o", str(output)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert output.read_text() == "# keep me\n"


def test_force_overwrites(tmp_path):
    output = tmp_path / "test_out.py"
    output.write_text("# old\n")
    assert main(["generate", str(SAMPLE_SPEC), "-o", str(output), "--force"]) == 0
    assert "def test_get_health(base_url):" in output.read_text()


def test_identical_input_gives_identical_files(tmp_path):
    first, second = tmp_path / "a" / "test_x.py", tmp_path / "b" / "test_x.py"
    assert main(["generate", str(SAMPLE_SPEC), "-o", str(first)]) == 0
    assert main(["generate", str(SAMPLE_SPEC), "-o", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda d: d / "missing.yaml", "not found"),
        (lambda d: (d / "bad.yaml").write_text("paths: [") and d / "bad.yaml", "Malformed YAML"),
        (lambda d: (d / "v.yaml").write_text("openapi: 3.1.0\npaths: {}\n") and d / "v.yaml", "Unsupported OpenAPI version"),
        (lambda d: (d / "s.yaml").write_text("- just\n- a list\n") and d / "s.yaml", "top level"),
    ],
)
def test_bad_specs_fail_with_message(tmp_path, capsys, setup, message):
    spec = setup(tmp_path)
    output = tmp_path / "test_out.py"
    assert main(["generate", str(spec), "-o", str(output)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("qa-platform: error: ")
    assert message in err
    assert not output.exists()


def test_no_supported_operations_fails(tmp_path, capsys):
    spec = write_json_spec(tmp_path / "spec.json", {"/a": {"post": {}}, "/b": {"get": {"responses": {"404": {}}}}})
    output = tmp_path / "test_out.py"
    assert main(["generate", str(spec), "-o", str(output)]) == 1
    err = capsys.readouterr().err
    assert "Skipped POST /a" in err
    assert "Skipped GET /b: no explicitly documented numeric 2xx response" in err
    assert "no supported operations found" in err
    assert not output.exists()


def test_output_must_be_python_file(tmp_path, capsys):
    assert main(["generate", str(SAMPLE_SPEC), "-o", str(tmp_path / "out.txt")]) == 1
    assert "must end in .py" in capsys.readouterr().err


def test_output_directory_is_rejected(tmp_path, capsys):
    folder = tmp_path / "test_dir.py"
    folder.mkdir()
    assert main(["generate", str(SAMPLE_SPEC), "-o", str(folder), "--force"]) == 1
    assert "is a directory" in capsys.readouterr().err


def test_missing_arguments_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["generate"])
    assert excinfo.value.code == 2


def test_console_entry_point_runs_as_module(tmp_path):
    output = tmp_path / "test_out.py"
    result = subprocess.run(
        [sys.executable, "-m", "qa_platform", "generate", str(SAMPLE_SPEC), "-o", str(output)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert output.exists()
