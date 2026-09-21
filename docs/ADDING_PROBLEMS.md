# Adding Problems to AICodeArena

This guide explains how to add a new problem to AICodeArena using the current implementation. It is written for a developer who is authoring a new problem definition and wants that problem to load, prompt correctly, validate safely, run through the right evaluator, and appear in the frontend.

This document is intentionally practical. It does not repeat the full system overview from `docs/ARCHITECTURE.md`. Instead, it focuses on the authoring workflow that the current backend actually supports.

## 1. Where problem files live

Active problem definitions live in:

```text
backend/problem_bank/
```

Each problem is a single JSON file. The backend loads every `*.json` file in that folder during startup through `seed_database()` in `backend/app/seed.py`, which calls `load_problem_definitions()` in `backend/app/problem_loader.py`.

Today’s active examples are:

- `starting_lineup_form.json`
- `tic_tac_toe_board.json`
- `notable_quotes.json`
- `super-heroes-vs-super-villains.json`
- `todo-list-pug.json`

If your new JSON file validates successfully, backend startup will upsert it into SQLite automatically.

## 2. How to choose `evaluatorType`

Choose `evaluatorType` based on the runtime and hidden test style, not just the editable file extension.

### Use `browser_qunit_html`

Use this when:

- the editable submission is a complete HTML file
- hidden tests run in a real browser with QUnit
- correctness depends on DOM structure or rendered page behavior

Current example:

- `starting_lineup_form.json`

### Use `browser_qunit_css`

Use this when:

- the editable submission is a complete CSS file
- read-only HTML provides the page structure
- hidden tests inspect stylesheet rules or rendered layout in Chromium

Current example:

- `tic_tac_toe_board.json`

### Use `browser_qunit_mocked_api`

Use this when:

- the editable submission is browser JavaScript
- tests run in a browser with QUnit
- tests may replace globals such as `XMLHttpRequest`
- real network access must stay blocked

Current example:

- `notable_quotes.json`

### Use `browser_qunit_javascript`

Use this when:

- the editable submission is browser JavaScript
- tests run in a browser with QUnit
- the code is a normal browser script rather than a mocked API exercise

Current example:

- `super-heroes-vs-super-villains.json`

### Use `node_jest_pug_jsdom`

Use this when:

- the assignment is a Node/Pug project
- hidden tests run with Jest and jsdom
- the Express server does not need to be started for testing
- the editable submission is currently one complete Pug file

Current example:

- `todo-list-pug.json`

### Legacy and non-primary evaluator paths

The repository still contains legacy evaluation code, especially older Python harness and CSS static-region paths, but those are not the primary way to author new active problems now. New problem authoring should start with the universal schema plus one of the active evaluator types above unless you are deliberately maintaining a legacy problem.

## 3. Universal JSON structure

New active problems should use the universal schema validated by `validate_universal_problem_definition()` in `backend/app/problem_loader.py`.

At a high level, one problem file contains:

- top-level metadata
- student-facing instructions
- a file list
- submission rules
- runtime description
- prompt policy
- hidden tests
- scoring metadata
- optional reference solution

The JSON files in `backend/problem_bank/` are the source of truth. SQLite stores an indexed copy in `Problem.raw_definition_json`, but you author the JSON file first.

## 4. Required top-level fields

The loader currently requires all of these top-level fields for universal problems:

- `schemaVersion`
- `id`
- `title`
- `description`
- `course`
- `sourcePlatform`
- `assignmentType`
- `evaluatorType`
- `language`
- `technologies`
- `instructions`
- `files`
- `submissionRules`
- `runtime`
- `promptPolicy`
- `tests`
- `scoring`
- `metadata`

The loader also accepts optional top-level fields that are already used in the repo:

- `referenceSolution`
- `mocks`

And file-level `notes` is allowed when provided.

## 5. File roles

Each file entry in `files` must include:

- `path`
- `role`
- `language`
- `content`
- `includeInPrompt`
- `requiredInSubmission`
- `preserve`

The loader currently allows these file roles:

- `editable`
- `read_only`
- `test`
- `dependency`
- `runtime`
- `asset`

Not every evaluator uses every role today, but the roles are already part of the allowed schema.

### `editable`

Use `editable` for files the model is allowed to produce. At least one editable file is required.

Examples:

- `index.html` in `starting_lineup_form.json`
- `styles.css` in `tic_tac_toe_board.json`
- `quote.js` in `notable_quotes.json`
- `hero.js` in `super-heroes-vs-super-villains.json`
- `views/index.pug` in `todo-list-pug.json`

### `read_only`

Use `read_only` for files that define context or runtime scaffolding but must not be modified by the model.

Examples:

- `index.html` in `tic_tac_toe_board.json`
- `server.js` and `public/styles.css` in `todo-list-pug.json`

### `test`

This role is allowed by the loader, but the current authored problem bank does not use prompt-visible file entries for hidden tests. Hidden tests instead live in the top-level `tests` array. Use `test` only if you have a strong evaluator-side reason and confirm it does not create prompt leakage.

### `dependency`

Use this for auxiliary runtime files if a future evaluator needs them as part of the workspace. The current problem bank does not actively rely on this role, but the loader allows it.

### `runtime`

Use this for evaluator-side runtime support files that should exist in the workspace but are not student-editable. As with `dependency`, the role is supported by schema validation but not heavily used in the current authored examples.

### `asset`

Use this for non-code files that the evaluator needs in the workspace, such as images or static assets. The current active examples do not depend heavily on this role yet.

## 6. `includeInPrompt` behavior

`includeInPrompt` controls whether a file is eligible to appear in the model prompt.

The prompt builder in `backend/app/prompt_builder.py` uses both:

- `files[].includeInPrompt`
- `promptPolicy.showReadOnlyFiles`

The practical rules are:

- editable files with `includeInPrompt: true` are shown
- editable files with `includeInPrompt: false` are omitted
- read-only files are shown only if both:
  - the file has `includeInPrompt: true`
  - `promptPolicy.showReadOnlyFiles` is `true`

Examples:

- `starting_lineup_form.json` hides `styles.css` by setting `includeInPrompt: false`
- `tic_tac_toe_board.json` shows both `index.html` and `styles.css`
- `todo-list-pug.json` shows `views/index.pug`, `server.js`, and `public/styles.css`

Important: hidden test source must never become prompt-visible through `includeInPrompt`. Keep official test code only in `tests[].source`.

## 7. `requiredInSubmission` behavior

`requiredInSubmission` documents which files the model must return as part of its output. In the current architecture, the most important enforcement comes from:

- `submissionRules.editablePaths`
- strict submission validation in `backend/app/submission_validator.py`

In practice:

- the main editable file should usually have `requiredInSubmission: true`
- read-only files should have `requiredInSubmission: false`

Examples:

- `styles.css` is required in `tic_tac_toe_board.json`
- `views/index.pug` is required in `todo-list-pug.json`
- `server.js` is not required in `todo-list-pug.json`

## 8. `preserve` behavior

`preserve` indicates whether the original file content should remain unchanged in the evaluation workspace.

Use:

- `preserve: true` for read-only files that the evaluator should carry into the workspace unchanged
- `preserve: false` for editable files that will be replaced by the submitted content

Examples:

- `index.html` in `tic_tac_toe_board.json` is preserved
- `styles.css` in `tic_tac_toe_board.json` is not preserved because the model replaces it

## 9. `submissionRules`

The current loader requires:

- `submissionRules` must be an object
- `submissionRules.mode` must equal `"full_editable_file"`
- `submissionRules.editablePaths` must be a non-empty list
- every `editablePaths` entry must be a safe relative path
- every `editablePaths` entry must match an editable file in `files`

Right now, the active system is built around complete-file submission, not partial snippets.

Common fields already used in the problem bank include:

- `mode`
- `editablePaths`
- `allowExtraFiles`
- `allowMissingFiles`
- `strictOutput`
- `validation`
- `notes`

Example pattern:

```json
"submissionRules": {
  "mode": "full_editable_file",
  "editablePaths": ["styles.css"],
  "allowExtraFiles": false,
  "allowMissingFiles": false,
  "strictOutput": true,
  "validation": [
    "Require the complete styles.css file.",
    "Reject markdown code fences."
  ]
}
```

## 10. `promptPolicy`

The loader requires:

- `promptPolicy` must be an object
- `promptPolicy.showTests` must be `false`
- `promptPolicy.showPointValues` must be `false`
- `promptPolicy.showEvaluatorType` must be `false`

Those are hard requirements, not suggestions.

Common fields already used in active problems include:

- `showInstructions`
- `showEditableFiles`
- `showReadOnlyFiles`
- `showTests`
- `showPointValues`
- `showEvaluatorType`
- `showImages`
- `hideFromModel`

The most important authoring rule is simple: do not let hidden tests, hidden point values, evaluator internals, or the reference solution leak into prompt-visible content.

## 11. Hidden test definitions

The current universal schema stores hidden tests in the top-level `tests` array. The loader requires every test object to contain:

- `id`
- `name`
- `framework`
- `path`
- `source`
- `points`
- `visibility`
- `timeoutMs`
- `isolation`
- `async`
- `mutatesGlobals`

Additional enforced rules:

- `tests` must be a non-empty list
- `id` must be unique
- `source` must be a non-empty string
- `path` must be a safe relative path
- `points` must be greater than zero
- `visibility` must equal `"hidden"`
- `timeoutMs` must be a positive integer
- `name`, `framework`, and `isolation` must be non-empty strings
- `async` and `mutatesGlobals` must be booleans

Examples of frameworks in the current problem bank:

- `qunit`
- `jest`

## 12. Meaningful `tests[].name` values

`tests[].name` matters more than it may seem. It becomes the frontend-facing label for the saved test result breakdown.

Good names should describe what the hidden test is checking, not just its position.

Examples from the current repo:

- `Page structure and title`
- `Displays to-do list items`
- `Add-task form`
- `Clear-list link`
- `Test SuperVillain getEvilChuckle() method`

Avoid generic labels like:

- `Unit Test 1`
- `Test 3`
- `Hidden Test A`

If the frontend shows a user five failed tests, these names are what they see.

## 13. Scoring rules

The loader currently enforces:

- `scoring` must be an object
- `scoring.mode` must equal `"test_all_or_nothing"`
- `scoring.activationStatus` must be `"ready"` or `"incomplete"`
- `scoring.maximumPoints` must equal the exact sum of all `tests[].points`

This is strict. If your point totals do not add up exactly, the problem file will not validate.

The current authored problems use 10 total points, but the key requirement is that `maximumPoints` matches the test-point sum exactly.

## 14. `referenceSolution` structure

`referenceSolution` is optional, but when present it is validated strictly.

It must look like:

```json
"referenceSolution": {
  "source": "zyBooks",
  "files": [
    {
      "path": "views/index.pug",
      "language": "pug",
      "content": "..."
    }
  ]
}
```

Current enforced rules from `problem_loader.py`:

- `referenceSolution` must be an object
- `referenceSolution.source` must be a non-empty string
- `referenceSolution.files` must be a non-empty list
- each reference file must contain:
  - `path`
  - `language`
  - `content`
- every reference file path must match an editable file
- the language must match that editable file
- duplicate reference file paths are rejected
- content must be a string

Important: reference solution files must map to editable files only. You cannot attach a read-only file or nonexistent path as part of `referenceSolution`.

Also important: reference solutions are not prompt-visible and must not be exposed through student-facing problem details.

## 15. Validation rules from `problem_loader.py`

These are the most common authoring rules the loader enforces today.

### Safe paths

All file paths and test paths must be safe relative paths:

- no absolute paths
- no backslashes
- no empty path segments
- no `.` or `..`

### File entries

Every file must include:

- `path`
- `role`
- `language`
- `content`
- `includeInPrompt`
- `requiredInSubmission`
- `preserve`

And:

- `role` must be one of the allowed roles
- `content` may be `null` or a string
- `includeInPrompt`, `requiredInSubmission`, and `preserve` must be booleans
- optional `notes`, if present, must be a string or `null`

### Editable file requirements

- at least one editable file must exist
- `submissionRules.editablePaths` must match editable files

### Prompt policy requirements

- `showTests` must be `false`
- `showPointValues` must be `false`
- `showEvaluatorType` must be `false`

### Test requirements

- all tests must be hidden
- all test sources must be non-empty
- all test point values must be positive
- test ids must be unique

### Scoring requirements

- only `test_all_or_nothing` is currently accepted
- `maximumPoints` must match the sum of test points

## 16. How backend startup seeds new problems

On backend startup, the FastAPI lifespan in `backend/app/main.py` calls:

- `seed_database()`

That function:

1. creates tables
2. adds compatibility columns to older databases
3. loads every JSON file in `backend/problem_bank/`
4. validates each one
5. upserts it into the `problems` table

This means the normal workflow for adding a new problem is:

1. create the JSON file in `backend/problem_bank/`
2. restart the backend
3. confirm the new problem appears in `/problems`

You do not need a separate manual registration step for normal startup-based loading.

## 17. Admin import route

The backend also has an admin import route:

- `POST /admin/problems`

This route:

- validates the incoming definition using the same loader rules
- rejects unsafe ids
- writes the JSON into `backend/problem_bank/<id>.json`
- upserts the SQLite problem row

It also supports:

- `overwrite=true`

There is also:

- `GET /admin/problems/{problem_key}/definition`

which returns the stored definition after validation.

For day-to-day repo development, direct file authoring in `backend/problem_bank/` plus a backend restart is usually simpler. The admin route is most useful if you want to import through the API without editing the filesystem manually.

## 18. How to verify the new problem appears in `/problems` and the frontend

After adding the file:

1. restart the backend
2. call `GET /problems`
3. confirm the new title appears
4. call `GET /problems/{id}` for the new row
5. open the frontend and refresh the problem list
6. confirm the problem appears in the left-side problem browser

If it does not appear:

- the JSON may have failed validation
- backend startup may have failed before seeding completed
- the problem bank file may not be under `backend/problem_bank/`

## 19. How to verify the reference solution

The safest current workflow is:

1. author the problem JSON
2. make sure `referenceSolution.files` maps exactly to the editable file path(s)
3. run the backend
4. execute the relevant evaluation path using the reference solution content as the submitted editable file content
5. confirm it receives a perfect functional result

For browser problems, this means the reference HTML/CSS/JS should pass all hidden QUnit tests.

For the Pug problem style, the reference `views/index.pug` should pass all hidden Jest tests.

If the reference solution does not score perfectly, either:

- the reference solution content is wrong
- the test source is wrong
- the evaluator contract does not match the assignment shape

Do not mark the problem ready until the reference solution passes.

## 20. How to verify an intentionally wrong solution

After verifying the reference solution, also test a deliberately wrong submission.

The goal is not only to prove the evaluator can pass the right answer, but also that it can fail the wrong answer clearly.

Examples:

- for a CSS grid problem, remove one required declaration
- for a browser JavaScript class problem, omit one required method
- for a Pug template problem, leave out the clear link or the conditional branch

Confirm that:

- the problem evaluates through the intended evaluator
- the result is non-perfect
- the saved test breakdown identifies the failing checks
- the frontend displays meaningful test names

## 21. Common authoring mistakes

These are the mistakes most likely to cause problems with the current implementation.

### Prompt leakage

- setting `includeInPrompt: true` on files that should stay hidden
- putting official tests anywhere except `tests[].source`
- exposing point values or evaluator details in prompt-visible text

### Path mismatches

- `submissionRules.editablePaths` does not exactly match the editable file path
- `referenceSolution.files[].path` does not exactly match the editable file path
- test `path` is unsafe or malformed

### Scoring mismatches

- `scoring.maximumPoints` does not equal the sum of test points
- one test accidentally has zero or negative points

### Weak test labels

- using generic names like `Unit Test 1` instead of meaningful test names

### Wrong evaluator choice

- using a browser evaluator for a Node/Jest/Pug assignment
- using `browser_qunit_css` when the problem is really JavaScript behavior
- choosing a mocked API evaluator when the hidden tests do not actually depend on mocked browser globals

### Submission format mismatch

- writing instructions that imply a code snippet, while `submissionRules.mode` requires the complete file
- forgetting that the current system expects `full_editable_file`

### Reference solution mistakes

- attaching a reference solution for a read-only file
- mismatching the reference file language
- including duplicate reference file paths

### Hidden test quality issues

- hiding tests correctly but giving them meaningless display names
- writing tests that depend on behavior not actually described in the assignment

## 22. Checklist before considering the problem ready

Before marking a new problem as ready, verify all of the following:

- the JSON file is in `backend/problem_bank/`
- the file validates through `problem_loader.py`
- required top-level fields are present
- file roles are correct
- editable file paths match `submissionRules.editablePaths`
- `includeInPrompt` only exposes intended student-visible context
- `promptPolicy.showTests`, `showPointValues`, and `showEvaluatorType` are all `false`
- every hidden test has:
  - a unique id
  - a meaningful name
  - non-empty source
  - positive point value
- `scoring.maximumPoints` matches the sum of test points exactly
- `referenceSolution` maps only to editable files
- backend startup seeds the problem successfully
- the problem appears in `/problems`
- the problem appears in the frontend
- the reference solution passes
- an intentionally wrong solution fails
- the test breakdown shown in the frontend is understandable

## 23. Worked JSON skeleton

Use this as a starting shape for a new universal problem:

```json
{
  "schemaVersion": "1.0",
  "id": "example-problem",
  "title": "Example Problem",
  "description": "Short assignment description.",
  "course": "COSC 4398",
  "sourcePlatform": "custom",
  "assignmentType": "html-form",
  "evaluatorType": "browser_qunit_html",
  "language": "html",
  "technologies": ["HTML", "DOM", "QUnit"],
  "instructions": {
    "studentPrompt": "Return the complete index.html file."
  },
  "files": [
    {
      "path": "index.html",
      "role": "editable",
      "language": "html",
      "content": "<!DOCTYPE html>\\n<html>\\n<body>\\n<!-- TODO -->\\n</body>\\n</html>\\n",
      "includeInPrompt": true,
      "requiredInSubmission": true,
      "preserve": false
    },
    {
      "path": "styles.css",
      "role": "read_only",
      "language": "css",
      "content": "body { font-family: Arial; }\\n",
      "includeInPrompt": false,
      "requiredInSubmission": false,
      "preserve": true
    }
  ],
  "referenceSolution": {
    "source": "custom",
    "files": [
      {
        "path": "index.html",
        "language": "html",
        "content": "<!DOCTYPE html>\\n<html>\\n<body>\\n<h1>Hello</h1>\\n</body>\\n</html>\\n"
      }
    ]
  },
  "submissionRules": {
    "mode": "full_editable_file",
    "editablePaths": ["index.html"],
    "allowExtraFiles": false,
    "allowMissingFiles": false,
    "strictOutput": true,
    "validation": [
      "Require the complete index.html file.",
      "Reject markdown code fences.",
      "Reject explanatory text outside the HTML."
    ]
  },
  "runtime": {
    "environment": "browser",
    "entryFile": "index.html",
    "browserEngine": "Chromium",
    "headless": true,
    "network": "disabled",
    "processIsolation": "fresh_environment",
    "testIsolation": "fresh_page",
    "waitFor": "load",
    "setupTimeoutMs": 10000,
    "individualTestTimeoutMs": 5000,
    "totalTimeoutMs": 30000
  },
  "promptPolicy": {
    "showInstructions": true,
    "showEditableFiles": true,
    "showReadOnlyFiles": false,
    "showTests": false,
    "showPointValues": false,
    "showEvaluatorType": false,
    "hideFromModel": [
      "Official test source",
      "Test point values",
      "Evaluator type"
    ]
  },
  "tests": [
    {
      "id": "page-title",
      "name": "Page title",
      "framework": "qunit",
      "path": "tests/page-title.js",
      "source": "QUnit.test('Page title', function(assert) { /* hidden test */ });",
      "points": 10,
      "visibility": "hidden",
      "timeoutMs": 5000,
      "isolation": "fresh_page",
      "async": false,
      "mutatesGlobals": false
    }
  ],
  "scoring": {
    "mode": "test_all_or_nothing",
    "requireExplicitPoints": true,
    "maximumPoints": 10,
    "activationStatus": "ready"
  },
  "metadata": {
    "difficulty": "easy",
    "tags": ["html", "qunit"]
  }
}
```

## 24. Recommended current authoring workflow

Here is the exact practical workflow that matches the codebase today:

1. Pick the evaluator type.
2. Copy one similar active JSON file from `backend/problem_bank/`.
3. Replace assignment metadata and instructions.
4. Define the editable and read-only files.
5. Set `submissionRules.mode` to `full_editable_file`.
6. Set `submissionRules.editablePaths` to the exact editable path(s).
7. Decide which files should be prompt-visible.
8. Add hidden tests with meaningful `name` values.
9. Set points so the total matches `scoring.maximumPoints`.
10. Add a correct `referenceSolution` for the editable file(s).
11. Restart the backend so seeding re-runs.
12. Confirm the problem appears in `/problems`.
13. Run the reference solution through the evaluator.
14. Run an intentionally wrong solution.
15. Confirm the frontend displays the new problem and readable test labels.

## Summary

Files referenced:

- `backend/app/problem_loader.py`
- `backend/app/seed.py`
- `backend/app/main.py`
- `backend/app/prompt_builder.py`
- `backend/app/submission_validator.py`
- `backend/problem_bank/tic_tac_toe_board.json`
- `backend/problem_bank/starting_lineup_form.json`
- `backend/problem_bank/notable_quotes.json`
- `backend/problem_bank/super-heroes-vs-super-villains.json`
- `backend/problem_bank/todo-list-pug.json`

Gaps or rough edges in the current authoring workflow:

- there is not yet a dedicated reusable `problem-template.json` file in the repo
- some allowed file roles are schema-supported but not deeply demonstrated by active examples
- the repo still contains legacy evaluator code, so a new developer could still choose the wrong starting point without this guide
- reference-solution verification is supported by the system, but there is not yet a single dedicated authoring script that automates the full “reference pass + wrong-answer fail” workflow

What should later go into `HANDOFF.md` instead of here:

- which legacy modules are still present and why
- which docs are still outdated
- known operational caveats for provider credentials and runtime dependencies
- any temporary architectural compromises or active cleanup targets

Does the repo still need a `problem-template.json` after this guide?

Yes. This guide should make problem authoring understandable, but a safe starter template would still reduce copy-paste mistakes and make the workflow faster for the next developer.
