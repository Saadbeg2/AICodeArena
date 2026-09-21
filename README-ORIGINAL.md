# AICodeArena

AICodeArena is a controlled evaluation framework for AI-generated code. It is designed to send the same programming problem to multiple AI models, evaluate their submissions under the same rules, store the results, and present side-by-side comparisons through a live competition dashboard.

The current repository includes:

- a FastAPI backend
- a React frontend
- a JSON-based problem bank
- multiple evaluator paths for browser and Node-based assignments
- real AI provider adapters
- asynchronous competition runs
- leaderboard and result history views
- reference-solution comparison
- AI Code Review for eligible saved results

## Why this project exists

AI code generation is easy to demo and hard to compare fairly. AICodeArena exists to make model evaluation more reproducible. Instead of judging models informally, it standardizes the flow:

Problem → Prompt → Model Output → Validation → Evaluation → Stored Results → Leaderboard

That makes it easier to compare models on the same assignment, diagnose failures, and inspect how generated submissions differ from official reference solutions.

## High-level feature list

- Loads problems from `backend/problem_bank/` JSON files
- Supports universal problem definitions with editable and read-only files
- Builds student-safe prompts without exposing hidden tests
- Runs asynchronous multi-model competitions
- Persists competition runs, evaluation results, and per-test results in SQLite
- Evaluates browser assignments with Playwright + Chromium + hidden QUnit tests
- Evaluates Node/Pug assignments with Jest + jsdom
- Stores reference-solution comparison data for completed results
- Provides AI Code Review for eligible saved results
- Exposes a React dashboard for running competitions and inspecting results

## Technology stack

Backend:

- Python
- FastAPI
- SQLAlchemy
- SQLite
- Playwright
- Requests
- Google GenAI SDK

Frontend:

- React
- Vite
- Vitest
- Testing Library

Evaluation runtimes:

- Chromium via Playwright for browser assignments
- Node.js + npm for Node/Pug assignments
- Jest + jsdom for Node/Pug testing

## Repository structure

```text
AICodeArena/
├── backend/
│   ├── app/                 # FastAPI app, evaluators, adapters, validation, persistence
│   ├── problem_bank/        # Universal problem JSON definitions
│   ├── scripts/             # Maintenance scripts
│   ├── tests/               # Backend test suite
│   └── .env.example         # Backend environment example
├── frontend/
│   ├── src/                 # React dashboard
│   └── .env.example         # Frontend environment example
├── docs/                    # Project documentation beyond the root README
└── README.md                # Main project entry point
```

## Quick start

### Backend

```bash
cd AICodeArena/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Backend URL:

```text
http://127.0.0.1:8000
```

Interactive API docs:

```text
http://127.0.0.1:8000/docs
```

### Frontend

In a second terminal:

```bash
cd AICodeArena/frontend
npm install
cp .env.example .env.local
npm run dev
```

Frontend URL:

```text
http://127.0.0.1:5173
```

## Environment configuration

Backend configuration lives in:

- `backend/.env.example`

Frontend configuration lives in:

- `frontend/.env.example`

Common backend variables include:

- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `MISTRAL_API_KEY`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODELS`
- `MODEL_EXECUTION_TIMEOUT_SECONDS`
- `AI_REVIEW_PROVIDER`
- `AI_REVIEW_OPENROUTER_API_KEY`
- `AI_REVIEW_MODELS`

Common frontend variables include:

- `VITE_API_BASE_URL`

Notes:

- The backend loads environment variables from `.env` at startup.
- The frontend defaults to `http://127.0.0.1:8000` if `VITE_API_BASE_URL` is not set.
- OpenRouter competition models are registered dynamically from `OPENROUTER_MODELS`.
- AI Code Review uses its own reviewer configuration and separate OpenRouter key.

## Running the application

1. Start the backend.
2. Start the frontend.
3. Open the frontend in the browser.
4. Select a problem.
5. Click `RUN ALL MODELS`.
6. Watch the current competition run update as results are persisted.
7. Open a model result to inspect output, test breakdown, reference comparison, and AI Code Review when available.

## Running tests

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

Frontend production build:

```bash
cd AICodeArena/frontend
npm run build
```

## High-level architecture summary

At a high level, AICodeArena works like this:

```text
React Frontend
      │
      ▼
FastAPI Backend
      │
      ├── Problem Loader
      ├── Prompt Builder
      ├── Provider Adapters
      ├── Submission Validator
      ├── Evaluators
      │     ├── Browser QUnit / Playwright
      │     └── Node Jest / Pug / jsdom
      ├── SQLite Persistence
      └── AI Code Review / Reference Comparison
```

Key design choices:

- Problem JSON is the source of truth.
- SQLite is used as a lightweight index and result store.
- Hidden tests are never included in model prompts.
- Competitions run asynchronously and persist incremental results.
- The frontend renders stored results rather than reproducing grading logic.

## Current active repository state

The current active application is centered on:

- universal JSON problem definitions
- real AI providers
- browser and Node-based evaluator paths
- asynchronous competitions
- stored result inspection

The repo also contains some historical or legacy modules for earlier phases. Those should not be treated as the primary application path unless a document explicitly says otherwise.

## Additional documentation

The root README is intentionally concise. More detailed project documentation should live in `docs/` as the repository matures.

Planned documentation entry points:

- `docs/ARCHITECTURE.md`
- `docs/ADDING_PROBLEMS.md`
- `docs/HANDOFF.md`

Potential additional documents:

- `docs/PROBLEM_SCHEMA.md`
- `docs/EVALUATORS.md`
- `docs/PROVIDERS.md`
- `docs/COMPETITIONS.md`
- `docs/AI_CODE_REVIEW.md`

These files may not exist yet, but this is the intended documentation direction for long-term maintainability.

## Where to look next

- `docs/ARCHITECTURE.md` for the end-to-end system design
- `docs/ADDING_PROBLEMS.md` for the practical problem-authoring workflow
- `backend/problem_bank/` for current universal problem examples
- `backend/tests/` for executable examples of expected backend behavior
