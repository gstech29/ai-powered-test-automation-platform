"""Generate tests through the CLI and run them against the local mock API.

The mock API runs as a separate process on a free 127.0.0.1 port and is
always stopped in the fixture's teardown. No external network is used.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_API = REPO_ROOT / "examples" / "mock_api.py"
SAMPLE_SPEC = REPO_ROOT / "examples" / "sample-api.yaml"


def _free_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(base_url, process, log_path, timeout=15):
    session = requests.Session()
    session.trust_env = False  # never route loopback traffic through a proxy
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Mock API exited early:\n{log_path.read_text()}")
        try:
            if session.get(base_url + "/health", timeout=1).status_code == 200:
                return
        except requests.ConnectionError:
            pass
        time.sleep(0.1)
    pytest.fail(f"Mock API did not become ready within {timeout}s:\n{log_path.read_text()}")


@pytest.fixture
def mock_api(tmp_path):
    port = _free_loopback_port()
    log_path = tmp_path / "mock_api.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(MOCK_API), "--port", str(port)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_until_ready(base_url, process, log_path)
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def generate(spec, output):
    result = subprocess.run(
        [sys.executable, "-m", "qa_platform", "generate", str(spec), "--output", str(output)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return output


def run_generated(test_file, base_url):
    env = {k: v for k, v in os.environ.items() if k not in ("API_BASE_URL", "PYTEST_ADDOPTS")}
    env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
    if base_url is not None:
        env["API_BASE_URL"] = base_url
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q", "-p", "no:cacheprovider"],
        cwd=test_file.parent, env=env, capture_output=True, text=True, timeout=120,
    )


def test_generated_tests_pass_against_mock_api(mock_api, tmp_path):
    test_file = generate(SAMPLE_SPEC, tmp_path / "generated" / "test_sample_api.py")
    result = run_generated(test_file, mock_api)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout


def test_generated_test_fails_on_undocumented_status(mock_api, tmp_path):
    # The mock API answers 404 for this item, but the spec documents only 200.
    spec = tmp_path / "missing-item.yaml"
    spec.write_text(
        "openapi: 3.0.3\n"
        "info: {title: t, version: '1'}\n"
        "paths:\n"
        "  /items/{item_id}:\n"
        "    get:\n"
        "      parameters:\n"
        "        - {name: item_id, in: path, required: true, example: item-does-not-exist}\n"
        "      responses:\n"
        "        '200': {description: ok}\n"
    )
    test_file = generate(spec, tmp_path / "test_missing_item.py")
    result = run_generated(test_file, mock_api)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout
    assert "GET /items/{item_id} returned HTTP 404, but the specification documents only 200" in result.stdout


def test_generated_tests_fail_clearly_without_api_base_url(tmp_path):
    test_file = generate(SAMPLE_SPEC, tmp_path / "test_sample_api.py")
    result = run_generated(test_file, base_url=None)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "API_BASE_URL is not set" in result.stdout
    assert "passed" not in result.stdout
