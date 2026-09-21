import React from "react";

import { terminalName } from "../utils";

export default function ProblemList({
  loading,
  problems,
  selectedId,
  onSelect,
  disabled = false,
}) {
  return (
    <aside className="panel problem-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">$ ls ./problem_bank</p>
          <h2>PROBLEMS</h2>
        </div>
        <span className="count-pill">{problems.length}</span>
      </div>

      <div className="problem-list">
        {loading && <p className="loading-message">Loading problems…</p>}
        {!loading && !problems.length && (
          <p className="muted">No problems are available.</p>
        )}
        {problems.map((problem) => (
          <button
            className={`problem-card ${selectedId === problem.id ? "selected" : ""}`}
            key={problem.id}
            onClick={() => onSelect(problem.id)}
            type="button"
            disabled={disabled}
          >
            <span className="problem-title">
              &gt; [{String(problem.id).padStart(2, "0")}] {terminalName(problem.title)}
            </span>
            <span className="problem-meta">
              {(problem.language || "UNKNOWN").toUpperCase()} / {(problem.difficulty || "UNKNOWN").toUpperCase()} / {(problem.category || "UNKNOWN").toUpperCase()}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
