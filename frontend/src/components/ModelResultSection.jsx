import React from "react";

import {
  displayModelName,
  formatExecutionTime,
  formatPercentage,
  formatScore,
  statusClass,
} from "../utils";
import ActionButton from "./ActionButton";
import TestBreakdown from "./TestBreakdown";

function formatAssessmentLabel(assessment) {
  if (!assessment) return "—";
  return String(assessment).replaceAll("_", " ").toUpperCase();
}

function isPlainTextAnalysis(payload) {
  return Boolean(
    payload &&
      payload.format === "plain_text" &&
      typeof payload.review_text === "string" &&
      payload.review_text.trim(),
  );
}

function isAiReviewEligible(result) {
  return Boolean(
    result?.result_id &&
      result?.ai_analysis_available
  );
}

function getAiReviewMode(result, aiAnalysisState) {
  return (
    aiAnalysisState?.payload?.review_mode ||
    aiAnalysisState?.payload?.analysis?.review_mode ||
    (result?.status === "Wrong Answer" ? "wrong_answer_diagnosis" : "accepted_review")
  );
}

function SummaryGrid({ result }) {
  return (
    <div className="summary-grid">
      <div><dt>STATUS</dt><dd>{result?.status || "—"}</dd></div>
      <div><dt>FUNCTIONAL SCORE</dt><dd>{formatScore(result)}</dd></div>
      <div><dt>FUNCTIONAL %</dt><dd>{formatPercentage(result?.score_percentage)}</dd></div>
      <div><dt>PASSED</dt><dd>{result?.passed_tests ?? "—"}</dd></div>
      <div><dt>FAILED</dt><dd>{result?.failed_tests ?? "—"}</dd></div>
      <div><dt>TOTAL</dt><dd>{result?.total_tests ?? "—"}</dd></div>
      <div><dt>TIME</dt><dd>{formatExecutionTime(result?.time)}</dd></div>
      <div><dt>RESULT_ID</dt><dd>{result?.result_id ?? result?.id ?? "—"}</dd></div>
    </div>
  );
}

export default function ModelResultSection({
  result,
  comparisonOpen,
  comparisonLoading,
  onToggleComparison,
  aiAnalysisState,
  aiAnalysisExpanded,
  onRunAiAnalysis,
  onToggleAiAnalysisBreakdown,
  modelCatalog,
}) {
  const [technicalDetailsOpen, setTechnicalDetailsOpen] = React.useState(false);

  React.useEffect(() => {
    setTechnicalDetailsOpen(false);
  }, [result?.result_id, aiAnalysisExpanded]);

  if (!result) {
    return (
      <section className="content-section empty-state">
        <h3>SELECTED_MODEL_RESULTS</h3>
        <p>&gt; Select one model from the leaderboard to inspect its output.</p>
      </section>
    );
  }

  const comparisonDisabled = !result?.result_id || result?.status === "Running";
  const aiAnalysisEligible = isAiReviewEligible(result);
  const analysisStatus = aiAnalysisState?.status || "idle";
  const analysisPayload = aiAnalysisState?.payload?.analysis || null;
  const analysisReviewer = aiAnalysisState?.payload?.reviewer || analysisPayload?.reviewer || null;
  const analysisCompleted = analysisStatus === "completed" && Boolean(analysisPayload);
  const analysisError = aiAnalysisState?.error || "";
  const analysisSectionId = `ai-analysis-breakdown-${result?.result_id ?? "none"}`;
  const technicalDetailsId = `ai-analysis-technical-${result?.result_id ?? "none"}`;
  const plainTextAnalysis = isPlainTextAnalysis(analysisPayload);
  const reviewMode = getAiReviewMode(result, aiAnalysisState);
  const isWrongAnswerDiagnosis = reviewMode === "wrong_answer_diagnosis";

  function renderAiAnalysisSection() {
    if (!aiAnalysisEligible) return null;

    return (
      <section className="content-section ai-analysis-section">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">$ review solution --ai-code-review</p>
            <h3>
              {isWrongAnswerDiagnosis
                ? "AI CODE REVIEW — FAILURE DIAGNOSIS"
                : "AI CODE REVIEW"}
            </h3>
          </div>
          <span className="status running">AI-GENERATED</span>
        </div>

        {!analysisCompleted && analysisStatus !== "error" ? (
          <>
            <p className="muted">No analysis has been generated for this result.</p>
            <div className="actions top-gap">
              <ActionButton
                loading={analysisStatus === "loading"}
                onClick={onRunAiAnalysis}
                variant="primary"
                disabled={analysisStatus === "loading"}
              >
                [ RUN AI CODE REVIEW ]
              </ActionButton>
            </div>
          </>
        ) : null}

        {analysisStatus === "error" ? (
          <>
            <h4>AI CODE REVIEW UNAVAILABLE</h4>
            <p className="muted">{analysisError || "The review could not be generated."}</p>
            <div className="actions top-gap">
              <ActionButton
                loading={false}
                onClick={onRunAiAnalysis}
                variant="primary"
                disabled={false}
              >
                [ RETRY AI CODE REVIEW ]
              </ActionButton>
            </div>
          </>
        ) : null}

        {analysisCompleted ? (
          <>
            {plainTextAnalysis ? (
              <div className="analysis-summary-block">
                <h4>
                  {isWrongAnswerDiagnosis
                    ? "AI CODE REVIEW — FAILURE DIAGNOSIS"
                    : "AI CODE REVIEW"}
                </h4>
                <pre className="plain-text-review">{analysisPayload.review_text}</pre>
              </div>
            ) : (
              <>
                <div className="summary-grid">
                  <div><dt>OVERALL ASSESSMENT</dt><dd>{formatAssessmentLabel(analysisPayload.overall_assessment)}</dd></div>
                  <div><dt>REVIEWER</dt><dd>{analysisReviewer?.provider === "mock" ? "Mock AI Reviewer" : (analysisReviewer?.used_model || "AI Reviewer")}</dd></div>
                </div>

                <div className="analysis-summary-block">
                  <h4>SUMMARY</h4>
                  <p>{analysisPayload.summary}</p>
                </div>
              </>
            )}

            <p className="muted review-disclaimer">
              &gt; This AI-generated code review is informational, may contain mistakes, and does not affect the functional score or competition standing.
            </p>

            {!plainTextAnalysis ? (
              <>
                <div className="actions top-gap">
                  <ActionButton
                    loading={false}
                    onClick={onToggleAiAnalysisBreakdown}
                    variant="ghost"
                    disabled={false}
                    aria-expanded={aiAnalysisExpanded}
                    aria-controls={analysisSectionId}
                  >
                    {aiAnalysisExpanded
                      ? "[ HIDE FULL REVIEW ]"
                      : "[ VIEW FULL REVIEW ]"}
                  </ActionButton>
                </div>
              </>
            ) : null}

            {plainTextAnalysis || aiAnalysisExpanded ? (
              <div id={analysisSectionId} className="ai-analysis-breakdown">
                {!plainTextAnalysis ? (
                  <>
                    {analysisPayload.categories?.map((category) => (
                      <div key={category.id} className="analysis-category">
                        <h4>{String(category.name || "").toUpperCase()}</h4>
                        <p>{formatAssessmentLabel(category.assessment)}</p>
                        <p>{category.explanation}</p>
                      </div>
                    ))}

                    {analysisPayload.strengths?.length ? (
                      <div className="analysis-list-block">
                        <h4>STRENGTHS</h4>
                        <ul>
                          {analysisPayload.strengths.map((strength) => (
                            <li key={strength.title}>
                              <strong>{strength.title}</strong>
                              <p>{strength.explanation}</p>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    {analysisPayload.improvements?.length ? (
                      <div className="analysis-list-block">
                        <h4>IMPROVEMENTS</h4>
                        {analysisPayload.improvements.map((item) => (
                          <div key={`${item.file}-${item.issue}`} className="analysis-improvement">
                            <strong>{item.issue}</strong>
                            <p>{item.explanation}</p>
                            <p><span>File:</span> {item.file}</p>
                            <p><span>Evidence:</span> {item.evidence}</p>
                            <p><span>Suggestion:</span> {item.suggestion}</p>
                          </div>
                        ))}
                      </div>
                    ) : null}

                    <div className="analysis-list-block">
                      <h4>REFERENCE COMPARISON</h4>
                      <p>{analysisPayload.reference_comparison?.summary || "No reference comparison was provided."}</p>
                      {analysisPayload.reference_comparison?.meaningful_differences?.length ? (
                        analysisPayload.reference_comparison.meaningful_differences.map((difference, index) => (
                          <div key={`${difference.candidate_evidence}-${index}`} className="analysis-improvement">
                            <p><span>Candidate evidence:</span> {difference.candidate_evidence}</p>
                            <p><span>Reference evidence:</span> {difference.reference_evidence}</p>
                            <p>{difference.explanation}</p>
                          </div>
                        ))
                      ) : (
                        <p className="muted">No meaningful reference differences were identified.</p>
                      )}
                    </div>
                  </>
                ) : null}

                <div className="actions top-gap">
                  <ActionButton
                    loading={false}
                    onClick={() => setTechnicalDetailsOpen((current) => !current)}
                    variant="ghost"
                    disabled={false}
                    aria-expanded={technicalDetailsOpen}
                    aria-controls={technicalDetailsId}
                  >
                    {technicalDetailsOpen
                      ? "[ HIDE TECHNICAL DETAILS ]"
                      : "[ SHOW TECHNICAL DETAILS ]"}
                  </ActionButton>
                </div>

                {technicalDetailsOpen ? (
                  <div id={technicalDetailsId} className="analysis-list-block">
                    <h4>TECHNICAL DETAILS</h4>
                    <p>Provider: {analysisReviewer?.provider || "—"}</p>
                    <p>Requested model: {analysisReviewer?.requested_model || "—"}</p>
                    <p>Used model: {analysisReviewer?.used_model || "—"}</p>
                    <p>Prompt version: {analysisReviewer?.prompt_version || "—"}</p>
                    <p>Rubric version: {analysisReviewer?.rubric_version || "—"}</p>
                    <p>Review timestamp: {aiAnalysisState?.payload?.created_at || aiAnalysisState?.payload?.analysis_created_at || aiAnalysisState?.payload?.createdAt || aiAnalysisState?.created_at || "—"}</p>
                    <p>Candidate hash: {analysisPayload.audit?.candidate_content_hash || "—"}</p>
                    <p>Reference hash: {analysisPayload.audit?.reference_content_hash || "—"}</p>
                    <p>Output hash: {analysisPayload.audit?.reviewer_output_hash || "—"}</p>
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </section>
    );
  }

  return (
    <>
      <section className="content-section">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">$ inspect model --details</p>
            <h3>{displayModelName(result.model_name, modelCatalog).toUpperCase()}</h3>
          </div>
          <span className={statusClass(result.status)}>{result.status}</span>
        </div>

        <SummaryGrid result={result} />

        {result.status === "Running" ? (
          <p className="muted">
            &gt; This model is still running. Results and scores will appear automatically when execution finishes.
          </p>
        ) : null}

        {result.status === "Timed Out" ? (
          <p className="muted">
            &gt; This model exceeded the allowed execution time. No additional review score is available.
          </p>
        ) : null}

        {result.status === "Interrupted" ? (
          <p className="muted">
            &gt; This model did not finish because the backend recovered an abandoned competition run after the timeout window elapsed.
          </p>
        ) : null}

        <div className="output-grid">
          <div>
            <h4>$ STDOUT</h4>
            <pre>{result.stdout || "No output"}</pre>
          </div>
          <div>
            <h4>$ STDERR</h4>
            <pre className={result.stderr ? "error-output" : ""}>
              {result.stderr || "No errors"}
            </pre>
          </div>
        </div>

        <div className="actions top-gap">
          <ActionButton
            loading={comparisonLoading}
            onClick={onToggleComparison}
            variant="ghost"
            disabled={comparisonDisabled}
          >
            {comparisonOpen
              ? "[ HIDE COMPARISON ]"
              : "[ COMPARE WITH OFFICIAL SOLUTION ]"}
          </ActionButton>
        </div>
      </section>

      {renderAiAnalysisSection()}

      <TestBreakdown
        testResults={result.test_results}
        title="SELECTED_MODEL_TEST_BREAKDOWN"
      />
    </>
  );
}
