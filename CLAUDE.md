# CLAUDE.md

Guidance for working in this repository.

## What this is

A deterministic OpenAPI 3.0.x → Pytest API test generator (v0.1.0), the first milestone of a planned AI-powered test automation platform. **There is no runtime AI/LLM integration.** Don't describe planned features (see `docs/roadmap.md`) as implemented.

## Architecture

- `src/qa_platform/openapi_loader.py`: reads local YAML/JSON (`yaml.safe_load` only), checks the version (3.0.x) and top-level structure, and raises `SpecError`.
- `src/qa_platform/test_generator.py`: `analyse_spec()` returns an `Analysis` with planned `OperationTest`s and `SkippedOperation`s (each with a reason). `render_module()` turns it into Python source. Unsupported features raise the internal `_Unsupported` (skip the operation), while structurally invalid documents raise `SpecError` (fail the run).
- `src/qa_platform/cli.py`: argparse CLI (`qa-platform generate SPEC -o FILE [--force]`). Exit code 0 on success, 1 on any error.
- `examples/mock_api.py`: stdlib HTTP server on 127.0.0.1 with synthetic data, matching `examples/sample-api.yaml`.

## Rules

- Keep the generator deterministic: no timestamps, absolute paths, randomness or set-ordering in output.
- Spec-derived values reach generated source only through `repr()`. Never interpolate them raw into code, docstrings or comments.
- Never fetch remote content, follow `$ref`s or target a spec's `servers`. Generated tests read `API_BASE_URL` only.
- Report unsupported cases with a clear skip reason rather than generating a weaker test. Never generate a test that can pass regardless of the response.
- Keep dependencies minimal (PyYAML, requests, and pytest for dev). Use synthetic data only, with no secrets or real endpoints.
- Don't commit, push or change repository settings unless asked.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest                      # tests/ only, including the end-to-end mock API test
qa-platform generate examples/sample-api.yaml --output generated_tests/test_sample_api.py --force
```

If generator output changes, regenerate `generated_tests/test_sample_api.py` with the command above. `tests/test_generation.py::test_committed_example_matches_generator_output` enforces this.

## Keep docs aligned

When behaviour changes, update the README sections "What works today", "Supported OpenAPI subset" and "Known limitations" in the same change, and move items in `docs/roadmap.md` only once they are implemented and tested.
