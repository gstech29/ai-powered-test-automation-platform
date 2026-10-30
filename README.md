# ai-powered-test-automation-platform

An AI-powered platform for generating, executing, analysing and maintaining automated tests for web applications and APIs, built with Python, Playwright, Pytest and Claude Code.

> **Current state (v0.1.0):** this first milestone is a small, **deterministic OpenAPI-to-Pytest API test generator**. It does **not** call an AI model or LLM at runtime: the same input always produces the same output. AI-assisted test generation, failure analysis and Playwright browser testing are **planned** (see [docs/roadmap.md](docs/roadmap.md)) and not implemented yet.

## What works today

- `qa-platform generate` reads a local OpenAPI 3.0.x file (YAML or JSON) and writes a Pytest module with one smoke test per supported `GET` operation.
- Each generated test sends one request with `requests` (10-second timeout, redirects not followed) and asserts that the status code is one of the operation's documented numeric 2xx codes.
- Operations outside the supported subset are skipped and reported with the reason, both on stderr and as comments at the top of the generated file.
- The generated tests take their target only from `API_BASE_URL`. They never use the specification's `servers` section, and they fail with a clear message if `API_BASE_URL` is missing.
- A fictional sample API (`examples/sample-api.yaml`) and a matching standard-library mock server (`examples/mock_api.py`) let you run the whole workflow locally.

The generated tests check **status codes only**. They do not validate response bodies or schemas.

## Installation

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## Usage

```bash
qa-platform generate SPEC --output FILE.py [--force]
```

| Option | Meaning |
| --- | --- |
| `SPEC` | Local `.yaml`, `.yml` or `.json` OpenAPI 3.0.x file. Remote URLs are not fetched. |
| `-o`, `--output` | Python file to write. Parent directories are created. |
| `--force` | Overwrite the output file if it exists. Without it, an existing file is never touched. |

Exit codes: `0` success, `1` error (missing or malformed file, unsupported version, invalid structure, no supported operations, output exists), `2` invalid command-line usage.

`python -m qa_platform generate ...` works too.

## Local demonstration

Everything runs on your machine with synthetic data. No credentials, external services or paid APIs are needed.

**Terminal 1: start the mock API** (binds to `127.0.0.1`; change the port with `--port`):

```bash
source .venv/bin/activate
python examples/mock_api.py --port 8000
```

**Terminal 2: generate and run the tests:**

```bash
source .venv/bin/activate
qa-platform generate examples/sample-api.yaml --output generated_tests/test_sample_api.py --force
export API_BASE_URL=http://127.0.0.1:8000
python -m pytest generated_tests/test_sample_api.py -v
```

Expected output: the generator reports two skipped operations (`POST /items`, because only GET is supported, and `GET /reports/summary`, because it requires authentication), writes 3 tests, and all 3 pass against the mock API.

[`generated_tests/test_sample_api.py`](generated_tests/test_sample_api.py) is committed as an example of real generator output. A unit test fails if it ever drifts from what the generator produces.

## Running the project's own tests

```bash
python -m pytest
```

Plain `pytest` collects only `tests/`, so the generated demo tests (which need a running API) are never picked up by accident. The suite includes an end-to-end test that:

1. starts `examples/mock_api.py` on a free loopback port,
2. generates tests through the CLI into a temporary directory,
3. runs them in a separate pytest process with `API_BASE_URL` set, and checks that they pass,
4. checks that a generated test **fails** when the API returns an undocumented status (404 where only 200 is documented),
5. checks that generated tests fail clearly when `API_BASE_URL` is missing,

and always stops the mock API, even when a test fails. GitHub Actions runs the same suite on Python 3.11 to 3.13 ([.github/workflows/tests.yml](.github/workflows/tests.yml)).

## Supported OpenAPI subset

**Documents**
- OpenAPI `3.0.x` only (the `openapi` field must be a string such as `"3.0.3"`). Swagger 2.0 and OpenAPI 3.1 are rejected.
- Local `.yaml`/`.yml` (parsed with `yaml.safe_load`) or `.json` files, UTF-8 encoded.
- The top level must be a mapping with a `paths` mapping, and every path key must start with `/`.

**Operations**
- Only `GET`. Other methods are reported as skipped.
- Operations are processed in document order.
- Skipped (with a reason): operations that require authentication (`security`, operation-level or inherited from the top level, unless it includes an empty `{}` requirement); operations with a `requestBody`; path items that are `$ref`s.

**Parameters**
- Path-item and operation parameters are merged, and the operation-level definition wins for the same `name` + `in`.
- Supported: `in: path` and `in: query` with scalar values (`string`, `integer`, `number`, `boolean`, or no `type`) and default serialisation (`style: simple` for path, `style: form` for query, `allowReserved` not set).
- Value source, first non-null wins: parameter `example`, then `schema.example`, then `schema.default`. The plural `examples` field is not used.
- Booleans are sent as `true`/`false`. Path values are percent-encoded. Query values are encoded by `requests`.
- Optional parameters with no value, or with an unsupported form (header/cookie, `content`, non-default `style`, `allowReserved`, array/object schemas, schema `$ref`, `allOf`/`oneOf`/`anyOf`/`not`), are **omitted**.
- Required parameters in any of those situations cause the operation to be **skipped**, with the reason. Path parameters are always treated as required. A parameter given as a `$ref` always skips the operation. A `{placeholder}` with no matching path parameter also skips it.

**Responses**
- Expected statuses are the explicitly documented numeric `2xx` codes (for example `200`, `204`). Range keys (`2XX`) and `default` are not used.
- Operations with no documented numeric 2xx response are skipped.
- Response objects themselves are not inspected, so a `$ref` response still counts as a documented status.

**Generated code**
- One `test_<name>` function per operation, named from `operationId` (snake_cased) or, failing that, from the method and path. Duplicate names get `_2`, `_3`, ... suffixes.
- Every value taken from the specification is written through `repr()`, so it is an inert Python literal.
- Output is byte-for-byte deterministic for the same input file name, content and generator version.

## Known limitations

- No response body or schema validation. Tests check status codes only.
- No authentication, request bodies, header/cookie parameters, or non-GET methods.
- No `$ref` resolution of any kind, and remote references are never fetched.
- No OpenAPI 3.1 or Swagger 2.0.
- Each operation gets exactly one test using the documented example/default values. There is no negative or boundary-value generation yet.
- The generated tests do send real HTTP requests to whatever `API_BASE_URL` points at. Point it only at environments you are allowed to test.

## Project layout

```
src/qa_platform/       cli.py, openapi_loader.py, test_generator.py
tests/                 unit, CLI and end-to-end tests (collected by default)
examples/              sample-api.yaml (fictional spec), mock_api.py (local mock)
generated_tests/       committed example output (not collected by default)
docs/roadmap.md        planned milestones
```
