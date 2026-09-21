import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ModelResultSection from "./ModelResultSection";

afterEach(() => {
  cleanup();
});

const catalog = [
  {
    id: "gemini-flash-latest",
    display_name: "Gemini Flash Latest",
    provider: "gemini",
  },
];

describe("ModelResultSection", () => {
  it("renders functional result fields and ignores legacy quality payload data", () => {
    render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Accepted",
          score_earned: 10,
          score_possible: 10,
          score_percentage: 100,
          quality_status: "evaluated",
          quality_score: 82.5,
          competition_score: 98.25,
          quality_breakdown: {
            conciseness: {
              earned: 32,
              possible: 40,
              status: "evaluated",
            },
          },
          quality_reason: null,
          passed_tests: 1,
          failed_tests: 0,
          total_tests: 1,
          time: "0.050",
          result_id: 7,
          stdout: "PASS",
          stderr: "",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{ status: "idle" }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />
    );

    expect(screen.getByText("FUNCTIONAL SCORE")).toBeInTheDocument();
    expect(screen.getByText("10/10")).toBeInTheDocument();
    expect(screen.getByText("FUNCTIONAL %")).toBeInTheDocument();
    expect(screen.getByText("100.0%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\[ compare with official solution \]/i })).toBeInTheDocument();

    expect(screen.queryByText("QUALITY SCORE")).not.toBeInTheDocument();
    expect(screen.queryByText("COMPETITION SCORE")).not.toBeInTheDocument();
    expect(screen.queryByText("QUALITY BREAKDOWN")).not.toBeInTheDocument();
  });

  it("renders test breakdown details when test results are present", () => {
    render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Accepted",
          score_earned: 10,
          score_possible: 10,
          score_percentage: 100,
          passed_tests: 1,
          failed_tests: 0,
          total_tests: 1,
          time: "0.020",
          result_id: 8,
          stdout: "PASS",
          stderr: "",
          test_results: [
            {
              test_id: "layout",
              name: "Layout",
              status: "passed",
              points_earned: 10,
              points_possible: 10,
              message: "Looks good.",
              assertions: [],
              console_errors: [],
              page_errors: [],
              diagnostics: {},
              duration_ms: 12,
            },
          ],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{ status: "idle" }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />
    );

    expect(screen.getByText("SELECTED_MODEL_TEST_BREAKDOWN")).toBeInTheDocument();
    expect(screen.getByText("Layout")).toBeInTheDocument();
    expect(screen.getByText(/POINTS=10\/10/i)).toBeInTheDocument();
  });

  it("renders timeout details without quality messaging", () => {
    render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Timed Out",
          score_earned: null,
          score_possible: null,
          score_percentage: null,
          quality_status: "disabled",
          quality_score: null,
          competition_score: null,
          quality_reason: "Deterministic quality grading is disabled.",
          passed_tests: null,
          failed_tests: null,
          total_tests: null,
          time: "120.000",
          result_id: 9,
          stdout: "",
          stderr: "The model exceeded the allowed execution time.",
          test_results: null,
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{ status: "idle" }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />
    );

    expect(
      screen.getByText(/This model exceeded the allowed execution time\./i),
    ).toBeInTheDocument();
    expect(screen.queryByText("QUALITY SCORE")).not.toBeInTheDocument();
    expect(screen.queryByText("QUALITY BREAKDOWN")).not.toBeInTheDocument();
  });

  it("shows the AI code review action for accepted perfect results and wrong answers only", () => {
    const { rerender } = render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Accepted",
          score_earned: 10,
          score_possible: 10,
          score_percentage: 100,
          ai_analysis_available: true,
          result_id: 10,
          stdout: "PASS",
          stderr: "",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{ status: "idle" }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />,
    );

    expect(screen.getByText("AI CODE REVIEW")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\[ run ai code review \]/i })).toBeInTheDocument();

    rerender(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Wrong Answer",
          score_earned: 6,
          score_possible: 10,
          score_percentage: 60,
          ai_analysis_available: true,
          result_id: 11,
          stdout: "",
          stderr: "Wrong Answer",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{ status: "idle" }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />,
    );

    expect(
      screen.getByText("AI CODE REVIEW — FAILURE DIAGNOSIS"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\[ run ai code review \]/i })).toBeInTheDocument();

    rerender(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Adapter Error",
          score_earned: null,
          score_possible: null,
          score_percentage: null,
          ai_analysis_available: false,
          result_id: 12,
          stdout: "",
          stderr: "Provider failure",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{ status: "idle" }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />,
    );

    expect(screen.queryByText("AI CODE REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\[ run ai code review \]/i })).not.toBeInTheDocument();
  });

  it("renders plain-text AI code review output with preserved line breaks", () => {
    render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Accepted",
          score_earned: 10,
          score_possible: 10,
          score_percentage: 100,
          ai_analysis_available: true,
          result_id: 12,
          stdout: "PASS",
          stderr: "",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{
          status: "completed",
          payload: {
            created_at: "2026-08-04T18:00:00",
            analysis: {
              format: "plain_text",
              review_text:
                "Overall assessment\nStrong submission.\n\nStrengths\n- Clear structure.\n\nFinal takeaway\nSolid work.\n<div>literal html</div>",
              reviewer: {
                provider: "openrouter",
                requested_model: "openai/gpt-oss-20b:free",
                used_model: "openai/gpt-oss-20b:free",
                prompt_version: "ai-code-review-v2",
              },
            },
            reviewer: {
              provider: "openrouter",
              requested_model: "openai/gpt-oss-20b:free",
              used_model: "openai/gpt-oss-20b:free",
              prompt_version: "ai-code-review-v2",
            },
          },
          error: "",
        }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />,
    );

    expect(screen.getAllByText("AI CODE REVIEW").length).toBeGreaterThan(0);
    expect(screen.getByText(/Overall assessment/)).toBeInTheDocument();
    expect(screen.getByText(/Strong submission\./)).toBeInTheDocument();
    expect(screen.getByText(/<div>literal html<\/div>/)).toBeInTheDocument();
    expect(screen.queryByText("OVERALL ASSESSMENT")).not.toBeInTheDocument();
    expect(screen.queryByText("REFERENCE COMPARISON")).not.toBeInTheDocument();
    expect(screen.getByText(/This AI-generated code review is informational/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /\[ show technical details \]/i })).toBeInTheDocument();
  });

  it("renders the failure-diagnosis label for wrong-answer reviews", () => {
    render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Wrong Answer",
          score_earned: 6,
          score_possible: 10,
          score_percentage: 60,
          ai_analysis_available: true,
          result_id: 14,
          stdout: "",
          stderr: "Wrong Answer",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{
          status: "completed",
          payload: {
            review_mode: "wrong_answer_diagnosis",
            analysis: {
              format: "plain_text",
              review_mode: "wrong_answer_diagnosis",
              review_text:
                "Failure Diagnosis\nA required DOM relationship is missing.\n\nFinal Takeaway\nThe submission is close but incomplete.",
            },
          },
          error: "",
        }}
        aiAnalysisExpanded={false}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />,
    );

    expect(
      screen.getAllByText("AI CODE REVIEW — FAILURE DIAGNOSIS").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/A required DOM relationship is missing\./)).toBeInTheDocument();
  });

  it("renders legacy structured AI code review payloads compatibly", () => {
    render(
      <ModelResultSection
        result={{
          model_name: "gemini-flash-latest",
          status: "Accepted",
          score_earned: 10,
          score_possible: 10,
          score_percentage: 100,
          ai_analysis_available: true,
          result_id: 13,
          stdout: "PASS",
          stderr: "",
          test_results: [],
        }}
        comparisonOpen={false}
        comparisonLoading={false}
        onToggleComparison={() => {}}
        aiAnalysisState={{
          status: "completed",
          payload: {
            created_at: "2026-08-04T18:00:00",
            analysis: {
              overall_assessment: "strong",
              summary: "Legacy structured review.",
              categories: [
                {
                  id: "readability_maintainability",
                  name: "Readability and Maintainability",
                  assessment: "strong",
                  explanation: "Still readable.",
                },
              ],
              strengths: [
                {
                  title: "Direct implementation",
                  explanation: "Focused on the requested behavior.",
                },
              ],
              improvements: [],
              reference_comparison: {
                summary: "Both implementations are valid.",
                meaningful_differences: [],
              },
              reviewer: {
                provider: "mock",
                requested_model: "mock-ai-reviewer",
                used_model: "mock-ai-reviewer",
                prompt_version: "ai-code-review-v1",
                rubric_version: "ai-code-review-rubric-v1",
              },
              audit: {
                candidate_content_hash: "candidate-hash",
                reference_content_hash: "reference-hash",
                reviewer_output_hash: "output-hash",
              },
            },
          },
          error: "",
        }}
        aiAnalysisExpanded={true}
        onRunAiAnalysis={() => {}}
        onToggleAiAnalysisBreakdown={() => {}}
        modelCatalog={catalog}
      />,
    );

    expect(screen.getByText("OVERALL ASSESSMENT")).toBeInTheDocument();
    expect(screen.getAllByText("STRONG").length).toBeGreaterThan(0);
    expect(screen.getByText("READABILITY AND MAINTAINABILITY")).toBeInTheDocument();
  });
});
