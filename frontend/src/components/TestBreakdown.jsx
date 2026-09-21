import React from "react";

import { statusClass } from "../utils";

function TestResultCard({ testResult }) {
  return (
    <details className="test-card">
      <summary>
        <div className="test-summary">
          <span className="test-title">{testResult.name || testResult.test_id}</span>
          <span
            className={statusClass(
              testResult.status === "passed" ? "Accepted" : testResult.status,
            )}
          >
            {testResult.status}
          </span>
        </div>
        <div className="test-meta">
          <span>
            POINTS={testResult.points_earned ?? "—"}/{testResult.points_possible ?? "—"}
          </span>
          <span>
            DURATION={testResult.duration_ms != null ? `${testResult.duration_ms}ms` : "—"}
          </span>
        </div>
      </summary>

      {testResult.message && (
        <div className="details-block padded">
          <h4>$ MESSAGE</h4>
          <pre>{testResult.message}</pre>
        </div>
      )}

      <div className="details-grid">
        <div className="details-block">
          <h4>$ ASSERTIONS</h4>
          <pre>{JSON.stringify(testResult.assertions || [], null, 2)}</pre>
        </div>
        <div className="details-block">
          <h4>$ DIAGNOSTICS</h4>
          <pre>{JSON.stringify(testResult.diagnostics || {}, null, 2)}</pre>
        </div>
        <div className="details-block">
          <h4>$ CONSOLE_ERRORS</h4>
          <pre>{JSON.stringify(testResult.console_errors || [], null, 2)}</pre>
        </div>
        <div className="details-block">
          <h4>$ PAGE_ERRORS</h4>
          <pre>{JSON.stringify(testResult.page_errors || [], null, 2)}</pre>
        </div>
      </div>
    </details>
  );
}

export default function TestBreakdown({ testResults, title = "TEST_BREAKDOWN" }) {
  if (!testResults?.length) return null;

  return (
    <section className="content-section">
      <p className="eyebrow">$ inspect --tests</p>
      <h3>{title}</h3>
      <div className="test-list">
        {testResults.map((testResult, index) => (
          <TestResultCard
            key={`${testResult.test_id || testResult.name || "test"}-${index}`}
            testResult={testResult}
          />
        ))}
      </div>
    </section>
  );
}
