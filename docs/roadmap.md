# Roadmap

Everything below is **planned, not implemented**. The current release (v0.1.0) is the deterministic OpenAPI-to-Pytest generator described in the [README](../README.md). Milestones are listed in rough order, and their scope may change.

## Milestone 1: Deterministic OpenAPI → Pytest generator (done, v0.1.0)

GET-only status-code smoke tests from a local OpenAPI 3.0.x file, a local mock API demo, and CI. No AI at runtime.

## Milestone 2: Broader OpenAPI support and response assertions (planned)

- Local `$ref` resolution (`#/components/...`) for parameters, schemas and responses. Remote references stay disabled by default.
- Response schema assertions using a JSON Schema validator, with the 3.0 → JSON Schema differences (`nullable`, etc.) handled explicitly.
- Content-type checks against documented `content` media types.
- Use of the plural `examples` field, plus `2XX`/`default` responses where they make sense.
- OpenAPI 3.1 support.

## Milestone 3: Authentication, request bodies and more methods (planned)

- Auth schemes (API key, HTTP bearer/basic, OAuth2 client credentials), with credentials taken only from environment variables and never written into generated files.
- POST/PUT/PATCH/DELETE with request bodies built from examples.
- Header and cookie parameters, and non-default serialisation styles.
- Opt-in safety controls for state-changing requests (for example an allow-list of target hosts).

## Milestone 4: AI-assisted test-case generation (planned)

- Optional use of an LLM (for example Claude through the Anthropic API) to propose extra test cases: boundary values, negative cases and realistic data.
- Proposals are reviewed and written out as ordinary deterministic Pytest code. The generated tests themselves will not call an AI model.
- The deterministic generator remains the default and works without any API key.

## Milestone 5: Failure analysis and reporting (planned)

- Structured run results (JUnit XML / JSON) and a readable summary report.
- Grouping of failures by likely cause (spec drift, environment, auth, data).
- Optional AI-assisted explanations of failures and suggested spec or test fixes, clearly labelled as suggestions.

## Milestone 6: Optional browser testing with Playwright (planned)

- An optional extra (`pip install -e ".[browser]"`) for Playwright-based UI smoke tests.
- Kept separate from the API generator so API-only users do not need browsers installed.

## Out of scope for now

Dashboards, databases, user accounts, hosted or cloud deployment.
