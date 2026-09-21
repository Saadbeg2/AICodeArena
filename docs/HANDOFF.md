# AICodeArena Handoff Notes

This document is for the next developer inheriting AICodeArena. It is not a replacement for the root `README.md`, `docs/ARCHITECTURE.md`, or `docs/ADDING_PROBLEMS.md`. Instead, it focuses on the current operational state of the project, what is active versus historical, what rough edges still exist, and what should be preserved during future changes.

## 1. Current project state

The current application is a working end-to-end competition demo for AI-generated programming submissions.

### What is fully working today

The following systems are implemented and actively wired into the current application:

- universal JSON problem bank under `backend/problem_bank/`
- React frontend dashboard under `frontend/`
- FastAPI backend under `backend/app/`
- provider adapter architecture for real model providers
- browser evaluator using Playwright + Chromium + hidden QUnit tests
- Node/Pug evaluator using Jest + jsdom
- asynchronous competition creation with background execution
- per-model deadlines during competition runs
- stale-run recovery on backend startup
- separate Current Run versus All-Time Best result views in the frontend
- AI Code Review for eligible saved results
- SQLite persistence for problems, competition runs, evaluation results, and per-test results
- automated backend and frontend test suites

In practical terms, the application already supports this flow:

```text
Choose problem
   │
   ▼
Run one model or all active models
   │
   ▼
Validate submission format strictly
   │
   ▼
Evaluate hidden tests in the correct runtime
   │
   ▼
Persist result rows and per-test rows
   │
   ▼
View Current Run, All-Time Best, per-test detail, comparison, and AI review
```

The active problem system is centered on universal problem JSON files, not hardcoded Python seed content.

## 2. Active versus legacy components

The repo contains both active application code and historical modules that were intentionally left in place. The distinction matters before deleting anything.

### Active components

These are the modules and paths that define the current live application behavior:

- `backend/app/main.py`
- `backend/app/problem_loader.py`
- `backend/app/seed.py`
- `backend/app/models.py`
- `backend/app/prompt_builder.py`
- `backend/app/submission_validator.py`
- `backend/app/model_adapters.py`
- `backend/app/browser_qunit_evaluator.py`
- `backend/app/node_jest_pug_evaluator.py`
- `backend/app/reference_comparison.py`
- `backend/app/ai_analysis.py`
- `frontend/src/App.jsx`
- `frontend/src/api.js`
- active JSON files in `backend/problem_bank/`

### `backend/app/legacy/mock_models.py`

Status:

- legacy

What it is:

- a preserved library of old mock model responses from earlier demo phases

Whether anything still imports it:

- yes, backend tests still import it, especially fixture-style and historical behavior tests

Why it remains:

- it preserves deterministic sample outputs used by older tests and historical documentation context

Safe to remove later?

- not yet without test cleanup
- it is not part of the active provider catalog, but removing it now would break tests that still rely on those fixtures

### `backend/app/legacy/quality_grader.py`

Status:

- legacy

What it is:

- the old deterministic code-quality grading system

Whether anything still imports it:

- yes, tests import it, and there are explicit tests asserting that the active pipeline no longer calls it

Why it remains:

- historical reference
- backward-compatibility for tests that document the old behavior and the decision to disable it

Safe to remove later?

- only after intentionally removing or rewriting those tests
- it is not part of active scoring anymore

### `backend/app/code_cleaner.py`

Status:

- transitional legacy helper

What it is:

- an earlier “forgiving cleanup” utility that strips markdown fences and surrounding prose

Whether anything still imports it:

- backend tests still import it directly
- the active official scoring path does not use it

Why it remains:

- historical reference
- some tests still verify its behavior

Safe to remove later?

- only if the team intentionally decides the cleanup helper is no longer worth preserving and also updates the tests

Important:

- official evaluation now depends on strict validation in `submission_validator.py`, not automatic repair

### Judge0-related code

Main file:

- `backend/app/judge0_client.py`

Status:

- legacy compatibility path

What it is:

- the older execution path for Python harness-style problems, including mock local execution and optional Judge0 submission

Whether anything still imports it:

- yes
- `backend/app/main.py` still imports and calls `run_python_code()`
- tests still cover it

Why it remains:

- the repo still supports legacy Python problem routes such as `judge-sample`
- older tests and legacy problem behavior still depend on it

Safe to remove later?

- not until the team intentionally drops those legacy Python routes and their tests

### Legacy Python evaluator and problem paths

Relevant files:

- `backend/app/test_harness.py`
- `backend/app/judge0_client.py`

Status:

- legacy / compatibility

What they are:

- older problem-specific Python harness builders
- a generic local/Judge0 execution bridge for those Python harnesses

Whether anything still imports them:

- yes
- `backend/app/main.py` still imports these paths
- several backend tests still exercise them

Why they remain:

- they still support older compatibility routes and older test coverage

Safe to remove later?

- only if legacy Python problem support is intentionally retired

### `css_static_region`

Relevant files:

- `backend/app/css_static_checker.py`
- branches in `backend/app/prompt_builder.py`
- branches in `backend/app/problem_loader.py`
- branches in `backend/app/main.py`

Status:

- legacy but still active in compatibility tests

What it is:

- the older CSS TODO-region evaluation approach

Whether anything still imports it:

- yes
- `main.py` routes it explicitly for `problem.problem_type == "css_static_region"`
- tests still cover it

Why it remains:

- compatibility with earlier CSS-region problem definitions

Safe to remove later?

- only after intentionally deciding that full-file browser CSS evaluation fully replaces it and then removing the associated tests and problem fixtures

### Other transitional modules

`backend/app/test_harness.py`

- still used for old Python-function style problems
- not the primary path for active browser or Node problems

`backend/app/problem_loader.py` legacy schema branch

- still supports legacy problem definitions
- the active authored problem bank uses the universal schema instead

`backend/app/main.py` old routes like `/problems/{id}/sample-harness` and `/problems/{id}/judge-sample`

- still present for legacy Python compatibility
- not part of the primary current browser/Node demo flow

## 3. Known rough edges

These are real current limitations or non-ideal areas supported by the current repo state.

### Free provider availability changes

OpenRouter free models are inherently unstable. The code already filters configured OpenRouter models to `:free` entries and normalizes model-unavailable errors, but free model availability can still change over time.

Implication:

- a previously working configured model may disappear or stop being free without any code change

### Rate limits and provider-side errors

The provider layer normalizes adapter failures, but free-tier and demo-tier providers can still return:

- rate limits
- temporary unavailability
- authentication failures
- provider-specific malformed responses

This is especially true for OpenRouter free models and any real hosted provider running on limited quotas.

### AI review reviewer availability

AI Code Review uses separate reviewer configuration from the competition provider roster. A developer can have working competition providers while AI review remains unavailable because:

- `AI_REVIEW_OPENROUTER_API_KEY` is missing
- `AI_REVIEW_MODELS` is empty
- configured reviewer models are unavailable

### Browser / Playwright environment sensitivity

The browser evaluator depends on Playwright plus Chromium being installed and functioning locally. On some machines, browser tests may be skipped or fail for environment reasons rather than application logic.

Implication:

- evaluator changes should always be validated in an environment where Chromium can actually launch

### Node / npm runtime dependency

The Node/Pug evaluator depends on:

- `node`
- `npm`
- a reusable dependency runtime under `backend/node_evaluator_runtime/`

If Node is missing or runtime dependencies have not been installed successfully, Node-backed problem evaluation will fail.

### Background-thread competition scalability

Competition execution currently uses background threads plus a `ThreadPoolExecutor` inside the FastAPI process. That is appropriate for local/demo use, but it is not a production worker architecture.

Implication:

- it works well for the presentation MVP
- it is not the right design for large-scale or multi-instance deployment

### Additive SQLite schema updates instead of formal migrations

`seed.py` applies additive column updates on startup rather than using a full migration toolchain. This has kept iteration simple, but it is not equivalent to formal database migrations.

Implication:

- schema evolution is easy for the current demo
- long-term maintainability would improve with formal migrations later

### Possible Chromium-related skips or test environment differences

Some backend tests are environment-sensitive because they depend on Playwright/Chromium availability. A passing logic change can still look flaky on a machine where Chromium is missing or blocked.

### No dedicated one-command verification workflow for new problems

There is not yet a single built-in command that automatically:

- validates a new problem JSON
- runs the reference solution
- runs a deliberately wrong solution
- confirms frontend visibility

That workflow is currently manual and described in `docs/ADDING_PROBLEMS.md`.

## 4. AI Code Review current behavior

AI Code Review is implemented in `backend/app/ai_analysis.py`.

Current behavior:

- functionally perfect `Accepted` results use `accepted_review`
- `Wrong Answer` results use `wrong_answer_diagnosis`
- other failure types are not eligible
- review output is plain text
- reviews are cached on the saved `EvaluationResult`
- reviewer configuration is separate from competition provider configuration
- accepted-review prompt version is `ai-code-review-v3`
- wrong-answer prompt version is `ai-code-review-wrong-answer-v1`
- reviews do not affect functional score
- reviews do not affect leaderboard order

Important operational details:

- AI review is post-evaluation, not part of the grading pipeline
- repeated requests for the same result reuse stored analysis data
- the review system has its own provider settings and timeout settings
- accepted-review prompts and wrong-answer prompts are intentionally different

## 5. Competition behavior

The competition system is one of the most important areas to preserve correctly.

### What must remain true

- competition creation is asynchronous
- the frontend gets a run id immediately
- the frontend polls for that exact run
- each model has its own deadline
- one slow model must never block completed models from being saved or shown
- model results persist incrementally as they finish
- stale `running` competitions are reconciled on startup

### Operational summary

Competition flow today is:

1. frontend calls `POST /problems/{id}/run-competition`
2. backend creates a `CompetitionRun`
3. backend returns `202 Accepted`
4. background thread launches one future per model
5. each model persists its own terminal `EvaluationResult`
6. frontend polls the specific competition-run endpoint
7. Current Run uses that exact run, not historical best rows

### Terminal statuses

The system currently persists statuses such as:

- `Accepted`
- `Wrong Answer`
- `Runtime Error`
- `Timed Out`
- `Time Limit Exceeded`
- `Adapter Error`
- `Interrupted`

These statuses matter operationally because stale-run reconciliation and frontend current-run rendering depend on terminal rows being persisted even when the provider or worker fails.

## 6. Provider configuration caveats

Solution-generation providers are configured in `backend/app/model_adapters.py`.

### Current solution-generation providers

- Gemini
- Groq
- Mistral
- OpenRouter

### Dynamic OpenRouter models

OpenRouter models come from:

- `OPENROUTER_MODELS`

This is a comma-separated list. The backend trims whitespace, ignores empty entries, and only registers models whose configured slug ends in `:free`.

That means:

- the frontend model list can change without code changes if `OPENROUTER_MODELS` changes
- OpenRouter availability is partly configuration-driven rather than hardcoded

### Timeouts

Solution-provider timeout behavior is centrally configurable through:

- `MODEL_EXECUTION_TIMEOUT_SECONDS`

with compatibility fallback to:

- `AICODEARENA_PROVIDER_TIMEOUT_SECONDS`

The adapters convert that into provider-specific units where needed.

### Separate AI review provider configuration

AI Code Review does not reuse the same provider config as solution generation.

Relevant AI review environment variables include:

- `AI_REVIEW_PROVIDER`
- `AI_REVIEW_OPENROUTER_API_KEY`
- `AI_REVIEW_MODELS`
- `AI_REVIEW_TIMEOUT_SECONDS`
- `AI_REVIEW_MAX_OUTPUT_TOKENS`
- `AI_REVIEW_MAX_INPUT_CHARS`

### Why free models may disappear

This is a real operational caveat:

- free tiers change
- models can become unavailable
- provider routing can change
- quota and rate limits can change

The current code handles this more gracefully than before, but it cannot prevent upstream model availability changes.

## 7. Testing expectations

### Core commands

Backend:

```bash
cd AICodeArena/backend
./.venv/bin/python -m unittest discover -s tests -v
```

Frontend tests:

```bash
cd AICodeArena/frontend
npm test -- --run
```

Frontend build:

```bash
cd AICodeArena/frontend
npm run build
```

### Playwright / browser caveat

Browser evaluator tests depend on a working Playwright + Chromium environment. If Chromium cannot launch locally, browser-related failures may reflect environment setup rather than code regressions.

### What should always be run after certain changes

After changing evaluators:

- run focused evaluator tests
- run the full backend suite

After changing competition logic:

- run focused competition tests
- run the full backend suite
- run frontend tests if response shapes or polling behavior changed

After changing providers:

- run focused provider tests
- run the full backend suite
- run the frontend build if `/models` metadata or API-visible provider data changed

After changing AI Code Review:

- run focused AI analysis tests
- run the full backend suite
- run frontend tests if any response/display shape changed

After changing problem schema or loader behavior:

- run loader/problem-bank tests
- run full backend suite
- verify active example problems still load

## 8. Current problem bank

The active universal problem files are:

- `starting_lineup_form.json` → `browser_qunit_html`
- `tic_tac_toe_board.json` → `browser_qunit_css`
- `notable_quotes.json` → `browser_qunit_mocked_api`
- `super-heroes-vs-super-villains.json` → `browser_qunit_javascript`
- `todo-list-pug.json` → `node_jest_pug_jsdom`

These are the best current examples for:

- browser HTML authoring
- browser CSS authoring
- browser JavaScript with mocked API behavior
- browser JavaScript class/object behavior
- Node/Pug project-style evaluation

## 9. Recommended next work

### Good next steps

- add more problems to the universal problem bank
- add larger and more realistic multi-file problems
- create `problem-template.json`
- improve problem verification tooling for authors
- continue refining AI Code Review prompt quality
- introduce formal database migrations if the schema is expected to keep evolving
- move to a stronger worker architecture if the project needs to scale beyond local/demo use

Potentially worthwhile, but only with care:

- revisit deterministic quality scoring only if a defensible rubric is designed and intentionally reintroduced

### Do not spend time reviving unless intentionally needed

- old mock-model architecture as an active application path
- deterministic quality grader as if it were still authoritative
- legacy Python/Judge0 demo paths as the main product direction
- older CSS TODO-region paths if the intent is to stay on browser full-file evaluation

Those paths remain for compatibility and historical context, not because they are the recommended future direction.

## 10. Handoff checklist

### Start here

1. Clone the repo.
2. Configure backend and frontend environment files.
3. Run the backend.
4. Run the frontend.
5. Run backend tests.
6. Run frontend tests and frontend build.
7. Read `docs/ARCHITECTURE.md`.
8. Read `docs/ADDING_PROBLEMS.md`.
9. Inspect the active problem examples in `backend/problem_bank/`.
10. Understand the legacy folder and compatibility modules before deleting anything.

### Start here if you want to…

Add a problem:

- read `docs/ADDING_PROBLEMS.md`
- copy one similar active problem JSON
- validate it through backend startup and active examples

Add a provider:

- start in `backend/app/model_adapters.py`
- preserve the provider abstraction and error normalization

Add an evaluator:

- start with `evaluate_universal_problem()` in `backend/app/main.py`
- add a dedicated evaluator module rather than overloading unrelated ones

Modify AI Code Review:

- start in `backend/app/ai_analysis.py`
- preserve caching and keep it separate from functional scoring

Modify competition behavior:

- start in `backend/app/main.py`
- preserve async run creation, incremental persistence, per-model deadlines, and stale-run recovery

## Summary

Files referenced:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/ADDING_PROBLEMS.md`
- `backend/app/main.py`
- `backend/app/problem_loader.py`
- `backend/app/seed.py`
- `backend/app/model_adapters.py`
- `backend/app/browser_qunit_evaluator.py`
- `backend/app/node_jest_pug_evaluator.py`
- `backend/app/ai_analysis.py`
- `backend/app/reference_comparison.py`
- `backend/app/code_cleaner.py`
- `backend/app/judge0_client.py`
- `backend/app/test_harness.py`
- `backend/app/css_static_checker.py`
- `backend/app/legacy/mock_models.py`
- `backend/app/legacy/quality_grader.py`
- `frontend/src/App.jsx`
- `frontend/src/api.js`
- `backend/problem_bank/*.json`

Legacy components found:

- `backend/app/legacy/mock_models.py`
- `backend/app/legacy/quality_grader.py`
- `backend/app/code_cleaner.py`
- `backend/app/judge0_client.py`
- `backend/app/test_harness.py`
- `backend/app/css_static_checker.py`
- legacy branches in `problem_loader.py`, `prompt_builder.py`, and `main.py`

Known rough edges documented:

- provider availability and rate limits
- AI review reviewer configuration dependency
- Playwright/Chromium environment sensitivity
- Node/npm runtime dependency
- thread-based competition scaling limits
- additive schema updates instead of formal migrations
- lack of a one-command new-problem verification workflow

Inconsistencies that still need cleanup:

- the repo still contains several compatibility paths and their tests, so “legacy” code is not always entirely isolated
- legacy Python/Judge0 and CSS-region support still exist in the main backend entrypoint
- some schema-supported roles are broader than what the current active problem bank demonstrates
