# AICodeArena Architecture

## 1. Project purpose

AICodeArena is a controlled evaluation system for AI-generated programming submissions. Its purpose is to send the same assignment to multiple AI models, validate the returned code strictly, run hidden evaluator tests in a real execution environment, persist the results, and present model outcomes side by side through a competition dashboard.

The current implementation is centered on fairness and traceability:

- problem definitions live in JSON files under `backend/problem_bank/`
- prompts are built from those definitions without exposing hidden tests
- model output is validated before execution rather than automatically repaired
- evaluators run hidden tests and return normalized result objects
- SQLite stores problem index data, competition runs, evaluation results, and per-test results
- the frontend renders stored backend results rather than reproducing evaluation logic in the browser

At a high level, the system looks like this:

```text
React Frontend
      │
      ▼
FastAPI API
      │
      ├── Problem Loader
      ├── Prompt Builder
      ├── Provider Adapters
      ├── Submission Validator
      ├── Evaluators
      │     ├── Browser QUnit / Playwright / Chromium
      │     └── Node Jest / Pug / jsdom
      ├── Result Persistence
      ├── Leaderboard / Competition Runs
      ├── Reference Comparison
      └── AI Code Review
```

## 2. High-level architecture

The repository is split into two active application layers:

- `backend/`: FastAPI application, SQLite persistence, model adapters, evaluators, problem loading, validation, comparison, and AI Code Review
- `frontend/`: React dashboard that consumes backend endpoints and renders competitions, leaderboards, per-test details, reference comparison, and model metadata

The backend is the system of record. It owns:

- problem loading and validation
- prompt construction
- model dispatch
- submission validation
- evaluator execution
- competition orchestration
- persistence
- AI Code Review generation and caching

The frontend is intentionally thin. It owns:

- problem browsing
- current-run competition display
- all-time best leaderboard display
- model detail presentation
- comparison viewer
- AI Code Review viewer

The frontend does not grade anything locally.

## 3. Overall request and competition lifecycle

The most important user-facing flow is a competition run.

```text
User selects a problem
        │
        ▼
Frontend calls POST /problems/{id}/run-competition
        │
        ▼
Backend creates a CompetitionRun row
        │
        ▼
Background worker runs one task per selected model
        │
        ├── build prompt
        ├── call provider adapter
        ├── validate returned submission
        ├── evaluate hidden tests
        ├── compare with reference solution
        └── persist EvaluationResult + EvaluationTestResult rows
        │
        ▼
Frontend polls /problems/{id}/competition-runs/{run_id}
        │
        ▼
Current-run table updates as each model finishes
        │
        ▼
User opens one result for details, comparison, and AI Code Review
```

### Single model flow

`POST /problems/{problem_id}/run-model` runs the same pipeline for one model synchronously from the API caller’s perspective:

1. Load the problem row from SQLite.
2. Build the model prompt from the problem definition.
3. Call the selected provider adapter.
4. Validate the returned submission format.
5. Choose the evaluator based on the problem definition.
6. Execute hidden tests.
7. Compare submitted editable files against the stored reference solution when one exists.
8. Save the result and per-test rows.
9. Return the saved result payload.

### Competition flow

`POST /problems/{problem_id}/run-competition` is intentionally different:

1. The endpoint creates a `CompetitionRun` row immediately.
2. It returns `202 Accepted` with a run identifier and initial placeholder status.
3. A background thread launches one worker future per model.
4. Each model is persisted independently as soon as it reaches a terminal state.
5. The frontend polls the exact run by `competition_run_id`.
6. If the backend crashes or is interrupted, startup reconciliation marks stale runs and persists interrupted results for missing models.

This design avoids one slow provider blocking the entire frontend request.

## 4. Universal problem system

The active problem system is JSON-driven. The source of truth is the files in `backend/problem_bank/`, not the SQLite problem row.

### Problem loading model

At startup, `seed_database()` in `backend/app/seed.py`:

1. creates database tables
2. applies additive compatibility columns for older databases
3. loads all problem definitions from `backend/problem_bank/`
4. validates each definition through `backend/app/problem_loader.py`
5. upserts a lightweight `Problem` index row for each file
6. stores the full JSON definition inside `Problem.raw_definition_json`

SQLite therefore acts as a searchable index and cached copy of the current problem definitions, while the JSON files remain the authored source.

### Dual-schema support

The loader still supports two schemas:

- legacy schema
- universal schema

The active application path is the universal schema. Legacy support remains for backward compatibility with older Python and CSS paths.

### What the universal schema represents

The universal schema is built to describe assignments in a way that is evaluator-aware without putting evaluator logic into the frontend. It includes:

- assignment metadata
- prompt-safe student instructions
- a file list with editable versus read-only roles
- submission rules
- runtime description
- prompt policy
- hidden tests
- scoring metadata
- optional `referenceSolution`

In practice, the current active problem bank uses it for:

- browser HTML + QUnit assignments
- browser CSS + QUnit assignments
- browser JavaScript/XHR assignments
- Node.js Pug + Jest/jsdom assignments

### Current active problem files

As of the current implementation, the active universal problem bank includes:

- `starting_lineup_form.json`
- `tic_tac_toe_board.json`
- `notable_quotes.json`
- `super-heroes-vs-super-villains.json`
- `todo-list-pug.json`

### Prompt isolation

The universal schema separates what the evaluator needs from what the model is allowed to see.

The backend uses:

- `instructions.studentPrompt`
- `files[].includeInPrompt`
- `files[].role`
- `submissionRules`
- `promptPolicy`

to construct prompts.

Hidden tests, point values, and the official reference solution are intentionally excluded from model prompts.

## 5. Evaluator architecture

Evaluator selection happens in the backend, not in the frontend. The key routing logic lives in `backend/app/main.py` inside `evaluate_universal_problem()`.

The current active evaluator families are:

- browser QUnit evaluator
- Node Jest/Pug evaluator

There is also a legacy CSS static-region evaluator still present for backward compatibility.

### 5.1 Browser evaluator

The browser evaluator lives in `backend/app/browser_qunit_evaluator.py`.

It is used for problem definitions whose `evaluatorType` starts with `browser_qunit_`.

Current evaluator types in this family include:

- `browser_qunit_html`
- `browser_qunit_css`
- `browser_qunit_mocked_api`
- `browser_qunit_javascript`

The browser evaluator does not inspect source code text and guess correctness. It launches real Chromium through Playwright and runs hidden QUnit tests against the live page.

The flow is:

1. Build a temporary workspace with read-only files plus the submitted editable file.
2. Serve the workspace through a temporary HTTP server bound to `127.0.0.1`.
3. Launch headless Chromium.
4. Open the assignment page through `http://127.0.0.1:<port>/...`.
5. Inject vendored QUnit and a hidden test script.
6. Wait for one hidden test to finish.
7. Collect assertions, console errors, page errors, diagnostics, and timing.
8. Repeat in a fresh browser context for the next hidden test.

The local HTTP server is an important architectural choice. The evaluator previously used `file://` loading, but Chromium restricted CSS `cssRules` access under file origin in ways that broke CSS assignments. Serving the workspace over localhost makes browser behavior consistent with a normal web origin and allows tests such as stylesheet inspection to work reliably.

The evaluator also blocks external network access while still allowing localhost requests to the temporary workspace. This matters most for mocked API problems such as `notable_quotes`, where the page and scripts load locally but real network calls are not permitted.

### 5.2 Node Jest/Pug evaluator

The Node evaluator lives in `backend/app/node_jest_pug_evaluator.py`.

It is currently used for:

- `node_jest_pug_jsdom`

This evaluator exists separately from the browser evaluator because the execution model is different. Instead of loading a page in Chromium and injecting QUnit, it:

1. creates a temporary Node workspace
2. writes all problem files into that workspace
3. replaces only the editable file with the submitted version
4. validates the editable Pug file by compiling it before tests
5. writes hidden Jest tests into the workspace
6. runs Jest in subprocesses
7. normalizes each test result into the same general result shape used elsewhere in the system

It reuses a stable runtime dependency directory under `backend/node_evaluator_runtime/` rather than installing packages per submission.

### 5.3 Legacy evaluator path

`backend/app/css_static_checker.py` remains in the repository for the older `css_static_region` problem style. It is not the main path for the current browser problem bank, because current CSS assignments use the browser evaluator with full-file CSS submissions and hidden QUnit tests.

## 6. AI provider architecture

Provider integration lives in `backend/app/model_adapters.py`.

The active architecture is registry-driven rather than a hardcoded one-off per endpoint. The backend exposes model metadata through `GET /models`, and competition defaults are built from that same active model catalog.

### Active provider families

The current backend supports:

- Gemini
- Groq
- Mistral
- OpenRouter

OpenRouter models are dynamic. They are registered at startup from the comma-separated `OPENROUTER_MODELS` environment variable, and only `:free` models are accepted into the active catalog.

### Provider metadata

Each registered model exposes metadata such as:

- internal model id
- display name
- provider
- model creator
- API provider
- description
- provider type

This is the same metadata consumed by the frontend’s MODEL INFO view.

### Provider dispatch flow

```text
Prompt
  │
  ▼
generate_solution(...)
  │
  ├── resolve model in active catalog
  ├── dispatch to provider-specific function
  ├── normalize provider output
  └── return raw generated submission text
```

The provider layer is intentionally narrow. It is responsible only for turning a prompt into returned code text and converting provider failures into normalized adapter errors. It does not evaluate submissions or score results.

### Timeouts and competition isolation

Provider timeout configuration is centralized in `model_adapters.py`, but competition handling is managed in `main.py`. Each competition model runs independently in the background worker pool, so one slow provider does not prevent other models from being persisted and displayed.

## 7. AI Code Review architecture

AI Code Review lives in `backend/app/ai_analysis.py`.

It is a separate post-evaluation feature, not part of functional grading.

### What it reviews

The current implementation allows AI Code Review for saved results that are either:

- functionally perfect `Accepted` results
- `Wrong Answer` results

The review mode is derived from the persisted evaluation outcome:

- `accepted_review`
- `wrong_answer_diagnosis`

### Input sources

AI Code Review does not inspect only the raw submission. It builds a review package from:

- assignment metadata and instructions
- prompt-visible context files
- candidate editable-file submission
- official reference solution files
- for wrong-answer diagnosis, safe failure evidence from normalized test results

### Provider model

The AI Code Review subsystem has its own provider configuration. It is separate from the competition provider catalog and uses its own environment variables, reviewer configuration, timeout handling, and caching.

### Output model

The current active response format is plain text review output plus backend metadata, not a frontend-generated summary. The review is stored on the `EvaluationResult` row and reused on repeated requests.

### Caching

Once a review is generated for a saved result, subsequent frontend requests return the stored review instead of making another provider call.

### Relationship to functional grading

AI Code Review does not change:

- execution status
- functional score
- per-test results
- leaderboard ranking

It is an auxiliary analysis layer on top of a completed functional evaluation.

## 8. Database and persistence overview

The backend uses SQLite through SQLAlchemy. The current persistence model is intentionally simple and centers on four major tables.

```text
Problem
  ├── lightweight index fields
  └── raw_definition_json

CompetitionRun
  ├── problem_id
  ├── model list
  └── run status/timestamps

EvaluationResult
  ├── one saved model result
  ├── score/status/output
  ├── comparison_json
  ├── AI review fields
  └── competition_run_id

EvaluationTestResult
  └── one persisted hidden test outcome per saved result
```

### Problem table

`Problem` stores:

- summary fields needed for existing endpoints
- `problem_key`
- `problem_type`
- `raw_definition_json`

This means the full validated problem definition is available from the database row without flattening every schema field into separate columns.

### CompetitionRun table

`CompetitionRun` groups all model results produced by one `RUN ALL MODELS` action. This is what allows the frontend to display the current run exactly as it happened instead of reconstructing it from historical best results.

### EvaluationResult table

`EvaluationResult` stores:

- model identity
- problem id
- status and execution outputs
- score summary
- competition run id
- legacy quality fields
- AI analysis fields
- comparison JSON
- created timestamp

### EvaluationTestResult table

Each `EvaluationTestResult` row stores one normalized hidden test outcome, including:

- test id
- test name
- status
- earned and possible points
- message
- details JSON for assertions and diagnostics
- duration

This is the source used by the frontend test breakdown panels.

## 9. Startup behavior

Startup logic is defined in the FastAPI lifespan function in `backend/app/main.py`.

On backend startup, the application:

1. loads environment variables with `load_dotenv()`
2. creates and migrates database tables additively
3. validates and seeds all problem-bank definitions into SQLite
4. reconciles stale competition runs that were left in `running` state

The stale run reconciliation step is important because competitions execute asynchronously. If the server stops mid-run, the next startup does not leave those runs permanently unresolved. Instead, it attempts to mark missing model outcomes as interrupted and close the run cleanly.

## 10. Legacy versus active components

The repository contains both active and legacy subsystems.

### Active components

The active application path is:

- universal JSON problem loading
- strict prompt generation from universal definitions
- strict submission validation
- real provider adapters
- browser QUnit evaluator
- Node Jest/Pug evaluator
- asynchronous competition runs
- current-run plus all-time-best views
- reference comparison
- AI Code Review

### Legacy but still present

Several older modules remain because they still support compatibility or historical tests:

- `backend/app/code_cleaner.py`
- `backend/app/test_harness.py`
- `backend/app/judge0_client.py`
- `backend/app/css_static_checker.py`
- `backend/app/legacy/mock_models.py`
- `backend/app/legacy/quality_grader.py`

Their presence does not mean they are the main production path. For example:

- official scoring now prefers strict validation over automatic cleanup
- browser and Node evaluators are the main active evaluation paths
- deterministic quality grading has been disabled and moved to legacy code
- mock model code remains only as legacy material, not as the active provider system

When orienting to the codebase, new development should start from the active universal pipeline rather than from these legacy utilities.

## 11. Extension points for future development

The current implementation already exposes several clean extension points.

### Adding new problems

The main extension point is the universal problem bank. New assignments are added as JSON definitions and then loaded automatically at backend startup through the existing seeding and validation path.

What belongs in a future dedicated problem-authoring guide rather than this architecture overview includes:

- exact schema authoring rules
- how to choose `evaluatorType`
- how to write hidden tests
- how to set `includeInPrompt`
- how to validate a reference solution against a new problem

### Adding new evaluators

A new evaluator family can be introduced by:

1. defining a new `evaluatorType`
2. adding validation rules for that submission shape
3. adding a new evaluator module
4. wiring dispatch in `evaluate_universal_problem()`

This keeps evaluator logic out of the frontend and out of the problem loader.

### Adding new providers

The provider architecture is already registry-based. New providers fit by:

1. adding provider-specific call logic in `model_adapters.py`
2. exposing model metadata in the active catalog
3. returning normalized adapter errors on failure

Competition mode, result persistence, and the frontend model catalog then reuse that provider automatically.

### Extending AI Code Review

The AI Code Review subsystem is already isolated enough to evolve independently. Future work can expand review prompts, provider choices, caching policy, or result presentation without changing evaluator scoring.

### Frontend growth

The frontend currently reflects backend state rather than recreating it. That architecture leaves room for:

- additional result filters
- richer historical views
- deeper model analytics
- separate problem-authoring interfaces

without moving grading logic into the client.

## 12. End-to-end architecture summary

The complete active flow can be summarized like this:

```text
Problem JSON in backend/problem_bank/
        │
        ▼
Problem Loader + Validator
        │
        ▼
SQLite Problem index (with raw_definition_json)
        │
        ▼
Prompt Builder
        │
        ▼
AI Provider Adapter
        │
        ▼
Strict Submission Validator
        │
        ▼
Evaluator Dispatch
   ┌────┴───────────────────────────────┐
   │                                    │
   ▼                                    ▼
Browser QUnit Evaluator          Node Jest/Pug Evaluator
   │                                    │
   ▼                                    ▼
Normalized execution result + per-test results
        │
        ├── Reference comparison
        ├── EvaluationResult persistence
        ├── EvaluationTestResult persistence
        └── CompetitionRun tracking
        │
        ▼
Leaderboard / Current Run / Result Detail
        │
        └── Optional AI Code Review on eligible saved results
```

This is the current implemented architecture. A new developer can understand the project as a pipeline that begins with problem-bank JSON, evaluates model submissions through environment-specific executors, persists normalized evidence, and lets the frontend render that evidence without performing grading itself.
