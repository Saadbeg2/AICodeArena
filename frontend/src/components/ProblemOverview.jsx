import React from "react";

import ActionButton from "./ActionButton";

export default function ProblemOverview({
  problem,
  files,
  running,
  disabled,
  onViewPrompt,
  onRunCompetition,
}) {
  return (
    <section className="panel detail-panel">
      <div className="detail-header">
        <div>
          <p className="eyebrow">$ cat problem_{problem.id}.details</p>
          <h2>{problem.title}</h2>
          <p className="detail-meta">
            {(problem.language || "unknown").toUpperCase()} / {(problem.difficulty || "unknown").toUpperCase()} / {(problem.category || "unknown").toUpperCase()}
          </p>
        </div>
        <span className="problem-kind large">
          [{files.some((file) => !file.editable) ? "MULTI-FILE" : "SINGLE-FILE"}]
        </span>
      </div>

      <p className="description">{problem.description}</p>

      <dl className="detail-facts">
        <div>
          <dt>REQUIRED_FUNCTION</dt>
          <dd>{problem.required_function || "NULL"}</dd>
        </div>
        <div>
          <dt>PRIMARY_FILE</dt>
          <dd>{problem.required_file || "NULL"}</dd>
        </div>
        <div>
          <dt>PROBLEM_ID</dt>
          <dd>{problem.id}</dd>
        </div>
      </dl>

      {!!files.length && (
        <div className="file-list">
          <h3>$ ls -l ./files</h3>
          {files.map((file) => (
            <div className="file-row" key={file.filename}>
              <code>- {file.filename}</code>
              <span className={`file-state ${file.editable ? "editable" : "locked"}`}>
                [{file.editable ? "RW" : "RO"}]
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="actions">
        <ActionButton
          loading={false}
          onClick={onViewPrompt}
          variant="ghost"
          disabled={disabled}
        >
          [ VIEW PROMPT ]
        </ActionButton>
        <ActionButton
          loading={running}
          onClick={onRunCompetition}
          variant="primary"
          disabled={disabled}
        >
          [ RUN ALL MODELS ]
        </ActionButton>
      </div>
    </section>
  );
}
