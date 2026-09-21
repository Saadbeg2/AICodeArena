import React, { useMemo, useState } from "react";

function fileMapFromResponse(files) {
  return (files || []).reduce((map, fileDefinition) => {
    map[fileDefinition.path] = fileDefinition.content || "";
    return map;
  }, {});
}

export default function ComparisonSection({ open, loading, error, comparison }) {
  const referenceFiles = useMemo(
    () => fileMapFromResponse(comparison?.reference_files),
    [comparison],
  );
  const submittedFiles = useMemo(
    () => fileMapFromResponse(comparison?.submitted_files),
    [comparison],
  );

  const comparedPaths = comparison?.comparison?.compared_file_paths || [];
  const availablePaths = comparedPaths.length
    ? comparedPaths
    : Array.from(
        new Set([
          ...Object.keys(referenceFiles),
          ...Object.keys(submittedFiles),
        ]),
      );

  const [selectedPath, setSelectedPath] = useState("");

  React.useEffect(() => {
    if (!availablePaths.length) {
      setSelectedPath("");
      return;
    }

    if (!selectedPath || !availablePaths.includes(selectedPath)) {
      setSelectedPath(availablePaths[0]);
    }
  }, [availablePaths, selectedPath]);

  if (!open) return null;

  return (
    <section className="content-section">
      <p className="eyebrow">$ diff --side-by-side official submission</p>
      <h3>OFFICIAL_COMPARISON</h3>

      {loading ? (
        <p className="muted">Preparing comparison view…</p>
      ) : error ? (
        <p className="muted">{error}</p>
      ) : (
        <>
          {comparison?.comparison && (
            <div className="comparison-summary-grid">
              <div><dt>REFERENCE</dt><dd>{comparison.comparison.reference_available ? "AVAILABLE" : "UNAVAILABLE"}</dd></div>
              <div><dt>EXACT_MATCH</dt><dd>{comparison.comparison.overall_exact_match ? "YES" : "NO"}</dd></div>
              <div><dt>NORMALIZED_MATCH</dt><dd>{comparison.comparison.overall_normalized_match ? "YES" : "NO"}</dd></div>
              <div><dt>FILES</dt><dd>{comparison.comparison.compared_file_paths.length}</dd></div>
            </div>
          )}

          {!!availablePaths.length && (
            <div className="file-tab-row">
              {availablePaths.map((path) => (
                <button
                  key={path}
                  type="button"
                  className={`file-tab ${selectedPath === path ? "active" : ""}`}
                  onClick={() => setSelectedPath(path)}
                >
                  {path}
                </button>
              ))}
            </div>
          )}

          <div className="comparison-grid">
            <div>
              <h4>$ OFFICIAL_REFERENCE</h4>
              <pre>
                {selectedPath && referenceFiles[selectedPath]
                  ? referenceFiles[selectedPath]
                  : "Official reference source is unavailable in the current comparison view."}
              </pre>
            </div>
            <div>
              <h4>$ AI_SUBMISSION</h4>
              <pre>
                {selectedPath && submittedFiles[selectedPath]
                  ? submittedFiles[selectedPath]
                  : "AI submission source is unavailable."}
              </pre>
            </div>
          </div>

          {comparison?.comparison?.files?.length ? (
            <div className="details-block top-gap">
              <h4>$ COMPARISON_SUMMARY</h4>
              <pre>{JSON.stringify(comparison.comparison.files, null, 2)}</pre>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
