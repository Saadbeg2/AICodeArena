export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
export const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;
export const COMPETITION_START_TIMEOUT_MS = 15_000;
export const AI_REVIEW_REQUEST_TIMEOUT_MS = 120_000;

async function request(path, options = {}) {
  const {
    headers = {},
    timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
    timeoutMessage,
    signal: externalSignal,
    ...requestOptions
  } = options;
  const controller = new AbortController();
  const forwardAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", forwardAbort);
    }
  }
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...requestOptions,
      headers: {
        "Content-Type": "application/json",
        ...headers,
      },
      signal: controller.signal,
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(
        timeoutMessage || `Backend request timed out: ${API_BASE_URL}${path}`,
      );
    }
    throw new Error("Could not reach the AICodeArena backend.");
  } finally {
    window.clearTimeout(timeout);
    if (externalSignal) {
      externalSignal.removeEventListener("abort", forwardAbort);
    }
  }

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message = data?.detail || `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  return data;
}

export function getProblems() {
  return request("/problems");
}

export function getModels() {
  return request("/models");
}

export function getProblem(problemId) {
  return request(`/problems/${problemId}`);
}

export function getPrompt(problemId) {
  return request(`/problems/${problemId}/prompt`);
}

export function runCompetition(problemId, modelNames, options = {}) {
  return request(`/problems/${problemId}/run-competition`, {
    method: "POST",
    timeoutMs: COMPETITION_START_TIMEOUT_MS,
    timeoutMessage:
      "The backend did not create a competition run in time. Please retry.",
    body: JSON.stringify({
      model_names: modelNames,
    }),
    ...options,
  });
}

export function getLeaderboard(problemId, mode = "best") {
  return request(`/leaderboard?problem_id=${problemId}&mode=${mode}`);
}

export function getCompetitionRun(problemId, competitionRunId) {
  return request(`/problems/${problemId}/competition-runs/${competitionRunId}`);
}

export function getLatestCompetitionRun(problemId) {
  return request(`/problems/${problemId}/competition-runs/latest`);
}

export function getResultComparison(resultId) {
  return request(`/results/${resultId}/comparison`);
}

export function runAiAnalysis(resultId, options = {}) {
  return request(`/results/${resultId}/ai-analysis`, {
    method: "POST",
    timeoutMs: AI_REVIEW_REQUEST_TIMEOUT_MS,
    ...options,
  });
}
