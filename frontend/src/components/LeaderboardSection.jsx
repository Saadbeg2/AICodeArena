import React from "react";

import {
  displayModelName,
  formatPercentage,
  formatScore,
  sortLeaderboardEntries,
  statusClass,
} from "../utils";

export default function LeaderboardSection({
  entries,
  loading,
  selectedModelName,
  onSelectModel,
  modelCatalog,
  title = "LEADERBOARD",
  eyebrow = "$ leaderboard --sort rank",
  emptyMessage = "> No leaderboard data for this run yet.",
  showHeader = true,
}) {
  return (
    <section className="content-section">
      {showHeader ? (
        <>
          <p className="eyebrow">{eyebrow}</p>
          <h3>{title}</h3>
        </>
      ) : null}
      {loading ? (
        <p className="muted">Refreshing leaderboard…</p>
      ) : entries.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Model #</th>
                <th>Model</th>
                <th>Score</th>
                <th>Percent</th>
                <th>Status</th>
                <th>Tests</th>
              </tr>
            </thead>
            <tbody>
              {sortLeaderboardEntries(entries).map((entry) => (
                // current-run rows use `status`; historical best rows also include `latest_status`
                // so we normalize both shapes here.
                
                <tr
                  key={entry.result_id ?? entry.model_name}
                  className={`clickable-row ${
                    selectedModelName === entry.model_name ? "selected-row" : ""
                  }`}
                  onClick={() => onSelectModel(entry)}
                >
                  <td className="rank">#{entry.rank}</td>
                  <td>{displayModelName(entry.model_name, modelCatalog)}</td>
                  <td>{formatScore(entry)}</td>
                  <td>{formatPercentage(entry.score_percentage)}</td>
                  <td>
                    <span className={statusClass(entry.latest_status || entry.status)}>
                      {entry.latest_status || entry.status}
                    </span>
                  </td>
                  <td>
                    {entry.passed_tests ?? "—"}/{entry.total_tests ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{emptyMessage}</p>
      )}
    </section>
  );
}
