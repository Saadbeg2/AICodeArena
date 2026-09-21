import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

vi.mock("./api", () => ({
  API_BASE_URL: "http://127.0.0.1:8000",
  getCompetitionRun: vi.fn(),
  getLeaderboard: vi.fn(),
  getLatestCompetitionRun: vi.fn(),
  getModels: vi.fn(),
  getProblem: vi.fn(),
  getProblems: vi.fn(),
  getPrompt: vi.fn(),
  getResultComparison: vi.fn(),
  runAiAnalysis: vi.fn(),
  runCompetition: vi.fn(),
  runModel: vi.fn(),
}));

import {
  getCompetitionRun,
  getLeaderboard,
  getLatestCompetitionRun,
  getModels,
  getProblem,
  getProblems,
  getPrompt,
  runAiAnalysis,
  runCompetition,
} from "./api";

const problems = [
  {
    id: 1,
    title: "Two Sum",
    description: "Return indices.",
    language: "python",
    difficulty: "easy",
    category: "arrays",
    required_file: "solution.py",
    required_function: "two_sum",
  },
];

const models = [
  {
    id: "gemini-flash-latest",
    display_name: "Gemini Flash Latest",
    provider: "gemini",
    model_creator: "Google DeepMind",
    api_provider: "Google AI Studio",
    description: "Fast Gemini model for general code generation and evaluation demos.",
    provider_type: "direct_provider",
  },
  {
    id: "groq:llama-3.3-70b-versatile",
    display_name: "Groq Llama 3.3 70B Versatile",
    provider: "groq",
    model_creator: "Meta",
    api_provider: "Groq",
    description: "Meta Llama 3.3 70B served through Groq's low-latency inference API.",
    provider_type: "direct_provider",
  },
];

const runningCompetitionResponse = {
  problem_id: 1,
  competition_run_id: "run-123",
  status: "running",
  model_names: models.map((model) => model.id),
  expected_model_count: 2,
  completed_model_count: 0,
  total_models: 2,
  results: [],
};

const partialCompetitionResponse = {
  ...runningCompetitionResponse,
  completed_model_count: 1,
  results: [
    {
      rank: 1,
      model_name: "gemini-flash-latest",
      competition_run_id: "run-123",
      status: "Accepted",
      stdout: "PASS",
      stderr: "",
      time: "0.032",
      passed_tests: 1,
      failed_tests: 0,
      total_tests: 1,
      score_earned: 10,
      score_possible: 10,
      score_percentage: 100,
      quality_status: "evaluated",
      quality_score: 95,
      competition_score: 99.5,
      quality_breakdown: null,
      quality_reason: null,
      ai_analysis_available: true,
      test_results: [],
      result_id: 1,
    },
  ],
};

const completedCompetitionResponse = {
  ...runningCompetitionResponse,
  status: "completed_with_errors",
  completed_model_count: 2,
  results: [
    partialCompetitionResponse.results[0],
    {
      rank: 2,
      model_name: "groq:llama-3.3-70b-versatile",
      competition_run_id: "run-123",
      status: "Timed Out",
      stdout: null,
      stderr: "The model exceeded the allowed execution time.",
      time: "120",
      passed_tests: null,
      failed_tests: null,
      total_tests: null,
      score_earned: null,
      score_possible: null,
      score_percentage: null,
      quality_status: "unavailable",
      quality_score: null,
      competition_score: null,
      quality_breakdown: null,
      quality_reason: null,
      test_results: null,
      result_id: 2,
    },
  ],
};

const wrongAnswerCompetitionResponse = {
  ...runningCompetitionResponse,
  status: "completed_with_errors",
  completed_model_count: 2,
  results: [
    partialCompetitionResponse.results[0],
    {
      rank: 2,
      model_name: "groq:llama-3.3-70b-versatile",
      competition_run_id: "run-123",
      status: "Wrong Answer",
      stdout: "",
      stderr: "One or more hidden tests failed.",
      time: "0.051",
      passed_tests: 3,
      failed_tests: 1,
      total_tests: 4,
      score_earned: 6,
      score_possible: 10,
      score_percentage: 60,
      quality_status: "unavailable",
      quality_score: null,
      competition_score: null,
      quality_breakdown: null,
      quality_reason: null,
      ai_analysis_available: true,
      test_results: [],
      result_id: 21,
    },
  ],
};

const recoveredInterruptedCompetitionResponse = {
  ...runningCompetitionResponse,
  status: "completed_with_errors",
  completed_model_count: 2,
  results: [
    partialCompetitionResponse.results[0],
    {
      rank: 2,
      model_name: "groq:llama-3.3-70b-versatile",
      competition_run_id: "run-123",
      status: "Interrupted",
      stdout: null,
      stderr: "This model did not finish because the competition worker was interrupted before it could persist a terminal result.",
      time: null,
      passed_tests: null,
      failed_tests: null,
      total_tests: null,
      score_earned: null,
      score_possible: null,
      score_percentage: null,
      quality_status: "unavailable",
      quality_score: null,
      competition_score: null,
      quality_breakdown: null,
      quality_reason: null,
      test_results: null,
      result_id: 3,
    },
  ],
};

const mockAiAnalysisResponse = {
  result_id: 1,
  problem_id: 1,
  analysis_status: "completed",
  analysis_score: null,
  analysis: {
    format: "plain_text",
    review_text:
      "Overall assessment\nThe candidate is functionally correct, clearly scoped, and maintainable for the assignment.\n\nStrengths\n- Focused on the requested behavior.\n\nFinal takeaway\nSolid work.",
  },
  reviewer: {
    provider: "openrouter",
    requested_model: "openai/gpt-oss-20b:free",
    used_model: "openai/gpt-oss-20b:free",
    prompt_version: "ai-code-review-v2",
  },
  created_at: "2026-08-04T18:00:00",
  cached: false,
};

const wrongAnswerAiAnalysisResponse = {
  result_id: 21,
  problem_id: 1,
  analysis_status: "completed",
  analysis_score: null,
  review_mode: "wrong_answer_diagnosis",
  analysis: {
    format: "plain_text",
    review_mode: "wrong_answer_diagnosis",
    review_text:
      "Failure Diagnosis\nA required structure is missing.\n\nFinal Takeaway\nThe submission is close but still fails one requirement.",
  },
  reviewer: {
    provider: "openrouter",
    requested_model: "openai/gpt-oss-20b:free",
    used_model: "openai/gpt-oss-20b:free",
    prompt_version: "ai-code-review-wrong-answer-v1",
  },
  created_at: "2026-08-04T18:00:00",
  cached: false,
};

function installTimeoutHarness() {
  const timeoutCallbacks = [];
  const originalSetTimeout = window.setTimeout.bind(window);
  const setTimeoutSpy = vi
    .spyOn(window, "setTimeout")
    .mockImplementation((callback, delay, ...args) => {
      if (delay === 2000 && typeof callback === "function") {
        timeoutCallbacks.push(() => callback(...args));
        return timeoutCallbacks.length;
      }
      return originalSetTimeout(callback, delay, ...args);
    });
  const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");
  return { timeoutCallbacks, setTimeoutSpy, clearTimeoutSpy };
}

beforeEach(() => {
  window.localStorage.clear();
  getProblems.mockResolvedValue(problems);
  getModels.mockResolvedValue(models);
  getProblem.mockResolvedValue(problems[0]);
  getPrompt.mockResolvedValue({ problem_id: 1, prompt: "Prompt" });
  getLeaderboard.mockResolvedValue({
    leaderboard: [
      {
        rank: 1,
        model_name: "gemini-flash-latest",
        result_id: 11,
        latest_status: "Accepted",
        passed_tests: 1,
        total_tests: 1,
        score_earned: 10,
        score_possible: 10,
        score_percentage: 100,
        time: "0.032",
      },
      {
        rank: 2,
        model_name: "groq:llama-3.3-70b-versatile",
        result_id: 12,
        latest_status: "Timed Out",
        passed_tests: 0,
        total_tests: 1,
        score_earned: 0,
        score_possible: 10,
        score_percentage: 0,
        time: "120",
      },
    ],
  });
  getLatestCompetitionRun.mockRejectedValue(new Error("No competition run found"));
  getCompetitionRun.mockResolvedValue(partialCompetitionResponse);
  runCompetition.mockResolvedValue(runningCompetitionResponse);
  runAiAnalysis.mockResolvedValue(mockAiAnalysisResponse);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("competition workflow", () => {
  it("shows CURRENT RUN immediately after the run is created with running placeholders", async () => {
    render(<App />);

    fireEvent.click(
      await screen.findByRole("button", { name: /\[ run all models \]/i }),
    );

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(screen.getByText("COMPETITION STATUS")).toBeInTheDocument();
    expect(screen.getByText("Competition is running.")).toBeInTheDocument();
    expect(screen.getByText("Completed: 0 / 2")).toBeInTheDocument();
    expect(screen.getAllByText("Running").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("COMPETITION_ERROR")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /\[ show results \]/i }),
    ).not.toBeInTheDocument();
  });

  it("polls the exact competition_run_id and replaces placeholders with partial results", async () => {
    const { timeoutCallbacks } = installTimeoutHarness();
    getCompetitionRun.mockResolvedValueOnce(partialCompetitionResponse);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /\[ run all models \]/i }),
    );

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(timeoutCallbacks.length).toBeGreaterThan(0);

    await timeoutCallbacks[timeoutCallbacks.length - 1]();

    expect(getCompetitionRun).toHaveBeenCalledWith(1, "run-123");
    expect(await screen.findByText("Completed: 1 / 2")).toBeInTheDocument();
    expect(screen.getAllByText("Accepted").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Running").length).toBeGreaterThanOrEqual(1);
  });

  it("preserves visible rows during a temporary polling failure and retries", async () => {
    const { timeoutCallbacks } = installTimeoutHarness();
    getCompetitionRun
      .mockRejectedValueOnce(new Error("Temporary polling failure"))
      .mockResolvedValueOnce(partialCompetitionResponse);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /\[ run all models \]/i }),
    );

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();

    await timeoutCallbacks[timeoutCallbacks.length - 1]();

    expect(
      await screen.findByText(/Unable to refresh competition status right now/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Running").length).toBeGreaterThanOrEqual(2);

    await timeoutCallbacks[timeoutCallbacks.length - 1]();

    expect(await screen.findByText("Completed: 1 / 2")).toBeInTheDocument();
    expect(screen.getAllByText("Accepted").length).toBeGreaterThan(0);
  });

  it("stops polling at terminal status and keeps completed results visible", async () => {
    const { timeoutCallbacks, clearTimeoutSpy } = installTimeoutHarness();
    getCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /\[ run all models \]/i }),
    );

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();

    await timeoutCallbacks[timeoutCallbacks.length - 1]();

    expect(await screen.findByText("Competition finished.")).toBeInTheDocument();
    expect(screen.getByText("Completed: 2 / 2")).toBeInTheDocument();
    expect(screen.getByText("Timed Out")).toBeInTheDocument();
    expect(clearTimeoutSpy).toHaveBeenCalled();
  });

  it("renders timed-out model details without classifying them as adapter errors", async () => {
    const { timeoutCallbacks } = installTimeoutHarness();
    getCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /\[ run all models \]/i }),
    );
    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(timeoutCallbacks.length).toBeGreaterThan(0);
    await timeoutCallbacks[timeoutCallbacks.length - 1]();

    fireEvent.click(screen.getByText("Groq Llama 3.3 70B Versatile"));

    expect(
      await screen.findByText(/This model exceeded the allowed execution time\./i),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Timed Out").length).toBeGreaterThan(0);
    expect(screen.queryByText("Adapter Error")).not.toBeInTheDocument();
  });

  it("resumes a stored running competition on page reload", async () => {
    const { setTimeoutSpy } = installTimeoutHarness();
    window.localStorage.setItem(
      "aicodearena:competitionRun:1",
      JSON.stringify({
        competition_run_id: "run-123",
        model_names: models.map((model) => model.id),
      }),
    );
    getCompetitionRun.mockResolvedValueOnce(partialCompetitionResponse);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(screen.getByText("Competition is running.")).toBeInTheDocument();
    expect(screen.getByText("Completed: 1 / 2")).toBeInTheDocument();
    expect(getCompetitionRun).toHaveBeenCalledWith(1, "run-123");
    expect(setTimeoutSpy).toHaveBeenCalled();
  });

  it("stops polling when a stored running competition is recovered as completed_with_errors", async () => {
    const { setTimeoutSpy, clearTimeoutSpy } = installTimeoutHarness();
    window.localStorage.setItem(
      "aicodearena:competitionRun:1",
      JSON.stringify({
        competition_run_id: "run-123",
        model_names: models.map((model) => model.id),
      }),
    );
    getCompetitionRun.mockResolvedValueOnce(recoveredInterruptedCompetitionResponse);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(await screen.findByText("Competition finished.")).toBeInTheDocument();
    expect(screen.getByText("Interrupted")).toBeInTheDocument();
    expect(getCompetitionRun).toHaveBeenCalledWith(1, "run-123");
    expect(clearTimeoutSpy).toHaveBeenCalled();
    expect(setTimeoutSpy).not.toHaveBeenCalledWith(expect.any(Function), 2000);
  });

  it("keeps ALL-TIME BEST collapsed by default while the current run stays visible", async () => {
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: /\[ run all models \]/i }),
    );

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(screen.getByText("ALL-TIME BEST")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /model #/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: /rank/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("#2")).toBeInTheDocument();
    const toggleButton = screen.getByRole("button", {
      name: /\[ show all-time best \]/i,
    });
    expect(toggleButton).toHaveAttribute("aria-expanded", "false");
  });

  it("shows MODEL # in both current run and expanded all-time best and keeps row selection working", async () => {
    getLatestCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);
    getCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /model #/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("columnheader", { name: /rank/i }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /\[ show all-time best \]/i }),
    );

    expect(
      screen.getByRole("button", { name: /\[ hide all-time best \]/i }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getAllByRole("columnheader", { name: /model #/i }).length,
    ).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getAllByText("Groq Llama 3.3 70B Versatile")[0]);

    expect(
      await screen.findByRole("heading", {
        name: /groq llama 3\.3 70b versatile/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Timed Out").length).toBeGreaterThan(0);
  });

  it("switches to model info and renders model metadata from the backend", async () => {
    render(<App />);

    fireEvent.click(
      await screen.findByRole("button", { name: /\[ model info \]/i }),
    );

    expect(await screen.findByText("MODEL INFO")).toBeInTheDocument();
    expect(screen.getByText("Gemini Flash Latest")).toBeInTheDocument();
    expect(screen.getByText("Google DeepMind")).toBeInTheDocument();
    expect(screen.getByText("Google AI Studio")).toBeInTheDocument();
  });

  it("runs AI code review once for a perfect result and expands stored review without extra requests", async () => {
    getLatestCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);
    getCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    const runButton = screen.getByRole("button", { name: /\[ run ai code review \]/i });
    fireEvent.click(runButton);

    expect(await screen.findByText(/Overall assessment/)).toBeInTheDocument();
    expect(screen.getByText(/Solid work\./)).toBeInTheDocument();
    expect(runAiAnalysis).toHaveBeenCalledTimes(1);
    expect(runAiAnalysis).toHaveBeenCalledWith(1);

    fireEvent.click(screen.getByRole("button", { name: /\[ show technical details \]/i }));
    expect(await screen.findByText(/Requested model:/)).toBeInTheDocument();
    expect(screen.getAllByText(/openai\/gpt-oss-20b:free/).length).toBeGreaterThanOrEqual(1);
    expect(runAiAnalysis).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /\[ hide technical details \]/i }));
    expect(screen.queryByText("TECHNICAL DETAILS")).not.toBeInTheDocument();
    expect(runAiAnalysis).toHaveBeenCalledTimes(1);
  });

  it("shows AI code review for a wrong-answer result", async () => {
    getLatestCompetitionRun.mockResolvedValueOnce(wrongAnswerCompetitionResponse);
    getCompetitionRun.mockResolvedValueOnce(wrongAnswerCompetitionResponse);
    runAiAnalysis.mockResolvedValueOnce(wrongAnswerAiAnalysisResponse);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Groq Llama 3.3 70B Versatile")[0]);

    expect(
      screen.getByText("AI CODE REVIEW — FAILURE DIAGNOSIS"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /\[ run ai code review \]/i }));
    expect(await screen.findByText(/Failure Diagnosis/)).toBeInTheDocument();
    expect(screen.getByText(/close but still fails one requirement/i)).toBeInTheDocument();
  });

  it("does not show AI code review for infrastructure failures", async () => {
    getLatestCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);
    getCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Groq Llama 3.3 70B Versatile")[0]);

    expect(screen.queryByText("AI CODE REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\[ run ai code review \]/i })).not.toBeInTheDocument();
  });

  it("shows an AI code review error and allows retry without removing the functional result", async () => {
    getLatestCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);
    getCompetitionRun.mockResolvedValueOnce(completedCompetitionResponse);
    runAiAnalysis
      .mockRejectedValueOnce(new Error("The review could not be generated."))
      .mockResolvedValueOnce({ ...mockAiAnalysisResponse, cached: true });

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /\[ run ai code review \]/i }));

    expect(await screen.findByText("AI CODE REVIEW UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("FUNCTIONAL SCORE")).toBeInTheDocument();
    expect(screen.getAllByText("10/10").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /\[ retry ai code review \]/i }));
    expect(await screen.findByText(/Overall assessment/)).toBeInTheDocument();
    expect(runAiAnalysis).toHaveBeenCalledTimes(2);
  });

  it("keeps analysis state isolated per result when switching models", async () => {
    const twoPerfectResults = {
      ...runningCompetitionResponse,
      status: "completed",
      completed_model_count: 2,
      results: [
        partialCompetitionResponse.results[0],
        {
          ...partialCompetitionResponse.results[0],
          rank: 2,
          model_name: "groq:llama-3.3-70b-versatile",
          result_id: 22,
          stdout: "PASS",
        },
      ],
    };
    getLatestCompetitionRun.mockResolvedValueOnce(twoPerfectResults);
    getCompetitionRun.mockResolvedValueOnce(twoPerfectResults);

    render(<App />);

    expect(await screen.findByText("CURRENT RUN")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /\[ run ai code review \]/i }));
    expect(await screen.findByText(/Overall assessment/)).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Groq Llama 3.3 70B Versatile")[0]);
    expect(screen.getByText("AI CODE REVIEW")).toBeInTheDocument();
    expect(screen.queryByText("Overall assessment")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\[ run ai code review \]/i })).toBeInTheDocument();

    fireEvent.click(screen.getAllByText("Gemini Flash Latest")[0]);
    expect(await screen.findByText(/Overall assessment/)).toBeInTheDocument();
    expect(runAiAnalysis).toHaveBeenCalledTimes(1);
  });
});
