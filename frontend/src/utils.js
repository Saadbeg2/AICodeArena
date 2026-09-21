export function parseFiles(prompt) {
  if (!prompt) return [];

  const filePattern = /^- (.+?) \(editable: (yes|no)\)(?: \[(.+?)\])?$/gm;
  return Array.from(prompt.matchAll(filePattern), (match) => ({
    filename: match[1],
    editable: match[2] === "yes",
    status: match[3] || (match[2] === "yes" ? "editable" : "locked"),
  }));
}

export function statusClass(status = "") {
  if (status === "Accepted") return "status accepted";
  if (status === "Running") return "status running";
  if (status === "Time Limit Exceeded" || status === "Timed Out") return "status timeout";
  if (status === "Interrupted") return "status timeout";
  return "status failed";
}

export function terminalName(value = "") {
  return value.trim().replace(/[^a-zA-Z0-9]+/g, "_").toUpperCase();
}

export function displayModelName(modelId, catalog = []) {
  const match = catalog.find((model) => model.id === modelId);
  return match?.display_name || modelId;
}

export function formatScore(result) {
  if (result?.score_earned == null || result?.score_possible == null) {
    return "—";
  }

  return `${result.score_earned}/${result.score_possible}`;
}

export function formatPercentage(value) {
  if (value == null) return "—";
  return `${Number(value).toFixed(1)}%`;
}

export function formatExecutionTime(value) {
  if (value == null || value === "") return "—";
  return `${value}s`;
}

export function isFunctionallyPerfectResult(result) {
  if (!result) return false;
  if (result.status !== "Accepted") return false;
  if (
    result.score_earned == null ||
    result.score_possible == null ||
    result.score_percentage == null
  ) {
    return false;
  }

  return (
    Number(result.score_possible) > 0 &&
    Math.abs(Number(result.score_earned) - Number(result.score_possible)) < 1e-9 &&
    Math.abs(Number(result.score_percentage) - 100) < 1e-6
  );
}

export function sortLeaderboardEntries(entries) {
  return [...entries].sort((left, right) => left.rank - right.rank);
}
