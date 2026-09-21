import React, { useEffect, useMemo, useRef, useState } from "react";

import {
  API_BASE_URL,
  getCompetitionRun,
  getLeaderboard,
  getLatestCompetitionRun,
  getModels,
  getProblem,
  getProblems,
  getPrompt,
  getResultComparison,
  runAiAnalysis,
  runCompetition,
} from "./api";
import ActionButton from "./components/ActionButton";
import ComparisonSection from "./components/ComparisonSection";
import LeaderboardSection from "./components/LeaderboardSection";
import LoadingPanel from "./components/LoadingPanel";
import ModelCatalogSection from "./components/ModelCatalogSection";
import ModelResultSection from "./components/ModelResultSection";
import ProblemList from "./components/ProblemList";
import ProblemOverview from "./components/ProblemOverview";
import PromptModal from "./components/PromptModal";
import { parseFiles } from "./utils";

const COMPETITION_PHASE = {
  IDLE: "idle",
  RUNNING: "running",
  COMPLETED: "completed",
  ERROR: "error",
};

const TOP_LEVEL_VIEW = {
  COMPETITION: "competition",
  MODEL_INFO: "modelInfo",
};

function buildSelectedModelResult(
  selectedResultId,
  selectedModelName,
  competitionResults,
  leaderboardEntries,
) {
  if (selectedResultId != null) {
    const competitionMatch = competitionResults.find(
      (result) => result.result_id === selectedResultId,
    );
    if (competitionMatch) return competitionMatch;

    const leaderboardMatch = leaderboardEntries.find(
      (result) => result.result_id === selectedResultId,
    );
    if (leaderboardMatch) return leaderboardMatch;
  }

  if (!selectedModelName) return null;
  return competitionResults.find((result) => result.model_name === selectedModelName) || null;
}

function competitionRunStorageKey(problemId) {
  return `aicodearena:competitionRun:${problemId}`;
}

function readStoredCompetitionRun(problemId) {
  const rawValue = window.localStorage.getItem(competitionRunStorageKey(problemId));
  if (!rawValue) return null;

  try {
    const parsedValue = JSON.parse(rawValue);
    if (typeof parsedValue === "string") {
      return { competition_run_id: parsedValue, model_names: [] };
    }
    return {
      competition_run_id: parsedValue?.competition_run_id || null,
      model_names: Array.isArray(parsedValue?.model_names) ? parsedValue.model_names : [],
    };
  } catch (_error) {
    return { competition_run_id: rawValue, model_names: [] };
  }
}

function writeStoredCompetitionRun(problemId, competitionRunId, modelNames = []) {
  if (!competitionRunId) return;
  window.localStorage.setItem(
    competitionRunStorageKey(problemId),
    JSON.stringify({
      competition_run_id: competitionRunId,
      model_names: modelNames,
    }),
  );
}

function buildPlaceholderEntry(modelName, competitionRunId, rank) {
  return {
    rank,
    model_name: modelName,
    competition_run_id: competitionRunId,
    status: "Running",
    stdout: null,
    stderr: null,
    time: null,
    passed_tests: null,
    failed_tests: null,
    total_tests: null,
    score_earned: null,
    score_possible: null,
    score_percentage: null,
    test_results: null,
    result_id: null,
  };
}

function mergeCompetitionEntries(runData, fallbackModelNames = [], previousEntries = []) {
  const resultEntries = Array.isArray(runData?.results) ? runData.results : [];
  const modelNames = Array.isArray(runData?.model_names) && runData.model_names.length
    ? runData.model_names
    : fallbackModelNames.length
      ? fallbackModelNames
      : previousEntries.map((entry) => entry.model_name);
  const resultMap = new Map(
    resultEntries.map((result) => [result.model_name, result]),
  );
  const mergedEntries = modelNames.map((modelName, index) => {
    const savedResult = resultMap.get(modelName);
    return savedResult || buildPlaceholderEntry(modelName, runData?.competition_run_id || null, index + 1);
  });
  const knownModelNames = new Set(modelNames);
  const extraResults = resultEntries.filter((result) => !knownModelNames.has(result.model_name));

  return [...mergedEntries, ...extraResults].map((entry, index) => ({
    ...entry,
    rank: index + 1,
  }));
}

export default function App() {
  const [problems, setProblems] = useState([]);
  const [models, setModels] = useState([]);
  const [activeView, setActiveView] = useState(TOP_LEVEL_VIEW.COMPETITION);
  const [selectedId, setSelectedId] = useState(null);
  const [problem, setProblem] = useState(null);
  const [prompt, setPrompt] = useState("");
  const [showPrompt, setShowPrompt] = useState(false);
  const [competitionResults, setCompetitionResults] = useState([]);
  const [competitionRunId, setCompetitionRunId] = useState(null);
  const [competitionModelNames, setCompetitionModelNames] = useState([]);
  const [expectedModelCount, setExpectedModelCount] = useState(0);
  const [completedModelCount, setCompletedModelCount] = useState(0);
  const [leaderboard, setLeaderboard] = useState([]);
  const [showAllTimeBest, setShowAllTimeBest] = useState(false);
  const [selectedModelName, setSelectedModelName] = useState("");
  const [selectedResultId, setSelectedResultId] = useState(null);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonData, setComparisonData] = useState(null);
  const [aiAnalysisByResultId, setAiAnalysisByResultId] = useState({});
  const [aiAnalysisExpandedByResultId, setAiAnalysisExpandedByResultId] = useState(
    {},
  );
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState("");
  const [competitionPhase, setCompetitionPhase] = useState(COMPETITION_PHASE.IDLE);
  const [competitionError, setCompetitionError] = useState("");
  const [competitionNotice, setCompetitionNotice] = useState("");
  const [loadingProblems, setLoadingProblems] = useState(true);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [loadingLeaderboard, setLoadingLeaderboard] = useState(false);
  const competitionAbortRef = useRef(null);
  const competitionPollRef = useRef(null);
  const competitionPollInFlightRef = useRef(false);

  const files = useMemo(() => parseFiles(prompt), [prompt]);
  const selectedResult = useMemo(
    () =>
      buildSelectedModelResult(
        selectedResultId,
        selectedModelName,
        competitionResults,
        leaderboard,
      ),
    [selectedResultId, selectedModelName, leaderboard, competitionResults],
  );
  const competitionRunning = competitionPhase === COMPETITION_PHASE.RUNNING;
  const competitionVisible =
    competitionPhase === COMPETITION_PHASE.RUNNING ||
    competitionPhase === COMPETITION_PHASE.COMPLETED;
  const selectedAiAnalysisState = selectedResult?.result_id
    ? aiAnalysisByResultId[selectedResult.result_id] || { status: "idle" }
    : { status: "idle" };
  const selectedAiAnalysisExpanded = Boolean(
    selectedResult?.result_id &&
      aiAnalysisExpandedByResultId[selectedResult.result_id],
  );

  useEffect(() => () => {
    if (competitionAbortRef.current) {
      competitionAbortRef.current.abort();
      competitionAbortRef.current = null;
    }
    if (competitionPollRef.current) {
      window.clearTimeout(competitionPollRef.current);
      competitionPollRef.current = null;
    }
  }, []);

  useEffect(() => {
    Promise.all([getProblems(), getModels()])
      .then(([problemData, modelData]) => {
        setProblems(problemData);
        setModels(modelData);
        setConnected(true);
        if (problemData.length) setSelectedId(problemData[0].id);
      })
      .catch((requestError) => {
        setConnected(false);
        setError(requestError.message);
      })
      .finally(() => setLoadingProblems(false));
  }, []);

  useEffect(() => {
    if (!selectedId) return undefined;
    let cancelled = false;

    setError("");
    setShowPrompt(false);
    setCompetitionResults([]);
    setCompetitionRunId(null);
    setCompetitionModelNames([]);
    setExpectedModelCount(0);
    setCompletedModelCount(0);
    setLeaderboard([]);
    setShowAllTimeBest(false);
    setSelectedModelName("");
    setSelectedResultId(null);
    setComparisonOpen(false);
    setComparisonLoading(false);
    setComparisonError("");
    setComparisonData(null);
    setAiAnalysisByResultId({});
    setAiAnalysisExpandedByResultId({});
    setCompetitionPhase(COMPETITION_PHASE.IDLE);
    setCompetitionError("");
    setCompetitionNotice("");
    setLoadingDetails(true);
    setLoadingLeaderboard(true);
    if (competitionPollRef.current) {
      window.clearTimeout(competitionPollRef.current);
      competitionPollRef.current = null;
    }

    const storedRun = readStoredCompetitionRun(selectedId);

    Promise.all([
      getProblem(selectedId),
      getPrompt(selectedId),
      getLeaderboard(selectedId, "best").catch(() => ({ leaderboard: [] })),
      (
        storedRun?.competition_run_id
          ? getCompetitionRun(selectedId, storedRun.competition_run_id).catch(() => null)
          : Promise.resolve(null)
      ).then((storedRun) => storedRun || getLatestCompetitionRun(selectedId).catch(() => null)),
    ])
      .then(([problemData, promptData, leaderboardData, latestRun]) => {
        if (cancelled) return;
        setProblem(problemData);
        setPrompt(promptData.prompt);
        setLeaderboard(leaderboardData.leaderboard || []);

        if (latestRun?.competition_run_id) {
          applyCompetitionRunData(
            latestRun,
            storedRun?.model_names || latestRun.model_names || [],
          );
          setCompetitionPhase(
            latestRun.status === "running"
              ? COMPETITION_PHASE.RUNNING
              : COMPETITION_PHASE.COMPLETED,
          );
          if (latestRun.status === "running") {
            setCompetitionNotice(
              "Competition is running. Results appear automatically as each model finishes.",
            );
            startCompetitionPolling(
              selectedId,
              latestRun.competition_run_id,
              storedRun?.model_names || latestRun.model_names || [],
            );
          } else if ((latestRun.results || []).some((result) => result.status !== "Accepted")) {
            setCompetitionNotice(
              "Competition completed with one or more model errors. Open a model result to view details.",
            );
          }
        }
      })
      .catch((requestError) => {
        if (!cancelled) setError(requestError.message);
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingDetails(false);
          setLoadingLeaderboard(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  async function refreshLeaderboard() {
    setLoadingLeaderboard(true);
    try {
      const data = await getLeaderboard(selectedId, "best");
      setLeaderboard(data.leaderboard);
      return data.leaderboard;
    } finally {
      setLoadingLeaderboard(false);
    }
  }

  function applyCompetitionRunData(runData, fallbackModelNames = []) {
    if (!runData) return;

    const nextModelNames =
      Array.isArray(runData.model_names) && runData.model_names.length
        ? runData.model_names
        : fallbackModelNames;
    const mergedEntries = mergeCompetitionEntries(
      runData,
      nextModelNames,
      competitionResults,
    );

    setCompetitionRunId(runData.competition_run_id || null);
    setCompetitionModelNames(nextModelNames);
    setExpectedModelCount(runData.expected_model_count ?? nextModelNames.length);
    setCompletedModelCount(runData.completed_model_count ?? runData.results?.length ?? 0);
    setCompetitionResults(mergedEntries);
    if (runData.competition_run_id) {
      writeStoredCompetitionRun(
        selectedId,
        runData.competition_run_id,
        nextModelNames,
      );
    }

    setSelectedResultId((currentResultId) => {
      if (
        currentResultId != null &&
        mergedEntries.some((result) => result.result_id === currentResultId)
      ) {
        return currentResultId;
      }
      return mergedEntries[0]?.result_id || null;
    });

    setSelectedModelName((currentModelName) => {
      if (
        currentModelName &&
        mergedEntries.some((result) => result.model_name === currentModelName)
      ) {
        return currentModelName;
      }
      return mergedEntries[0]?.model_name || "";
    });
  }

  function stopCompetitionPolling() {
    if (competitionPollRef.current) {
      window.clearTimeout(competitionPollRef.current);
      competitionPollRef.current = null;
    }
    competitionPollInFlightRef.current = false;
  }

  function scheduleCompetitionPoll(problemId, competitionRunId, fallbackModelNames = []) {
    if (!competitionRunId) return;
    if (competitionPollRef.current) {
      window.clearTimeout(competitionPollRef.current);
    }
    competitionPollRef.current = window.setTimeout(() => {
      pollCompetitionRun(problemId, competitionRunId, fallbackModelNames);
    }, 2000);
  }

  async function pollCompetitionRun(problemId, competitionRunId, fallbackModelNames = []) {
    if (!competitionRunId || competitionPollInFlightRef.current) {
      return;
    }
    competitionPollInFlightRef.current = true;
    let shouldContinuePolling = true;

    try {
      const runData = await getCompetitionRun(problemId, competitionRunId);
      applyCompetitionRunData(runData, fallbackModelNames);

      if (runData.status === "running") {
        setCompetitionPhase(COMPETITION_PHASE.RUNNING);
        setCompetitionNotice("Competition is running. Results appear automatically as each model finishes.");
        return;
      }

      shouldContinuePolling = false;
      stopCompetitionPolling();
      await refreshLeaderboard().catch(() => {
        setCompetitionNotice(
          "Competition finished, but the leaderboard could not be refreshed automatically.",
        );
      });
      if ((runData.results || []).some((result) => result.status !== "Accepted")) {
        setCompetitionNotice(
          "Competition completed with one or more model errors. Open a model result to view details.",
        );
      } else {
        setCompetitionNotice("Competition completed successfully.");
      }
      setCompetitionPhase(COMPETITION_PHASE.COMPLETED);
    } catch (_requestError) {
      setCompetitionNotice(
        "Unable to refresh competition status right now. Showing the last loaded results and retrying automatically.",
      );
    } finally {
      competitionPollInFlightRef.current = false;
      if (shouldContinuePolling) {
        scheduleCompetitionPoll(problemId, competitionRunId, fallbackModelNames);
      }
    }
  }

  function startCompetitionPolling(problemId, competitionRunId, fallbackModelNames = []) {
    stopCompetitionPolling();
    scheduleCompetitionPoll(problemId, competitionRunId, fallbackModelNames);
  }

  async function handleCompetition() {
    if (competitionRunning || !selectedId) return;

    if (competitionAbortRef.current) {
      competitionAbortRef.current.abort();
    }

    const controller = new AbortController();
    competitionAbortRef.current = controller;

    setComparisonOpen(false);
    setSelectedModelName("");
    setSelectedResultId(null);
    setCompetitionResults([]);
    setCompetitionRunId(null);
    setCompetitionModelNames([]);
    setExpectedModelCount(0);
    setCompletedModelCount(0);
    setLeaderboard([]);
    setComparisonData(null);
    setComparisonError("");
    setCompetitionNotice("");
    setCompetitionError("");
    setError("");
    setCompetitionPhase(COMPETITION_PHASE.RUNNING);
    stopCompetitionPolling();

    try {
      const competitionModelIds = models.map((model) => model.id);
      setCompetitionModelNames(competitionModelIds);
      const data = await runCompetition(selectedId, competitionModelIds, {
        signal: controller.signal,
      });
      applyCompetitionRunData(data, competitionModelIds);
      setCompetitionNotice("Competition is running. Results appear automatically as each model finishes.");
      setCompetitionPhase(
        data.status === "running"
          ? COMPETITION_PHASE.RUNNING
          : COMPETITION_PHASE.COMPLETED,
      );
      if (data.status === "running") {
        startCompetitionPolling(
          selectedId,
          data.competition_run_id,
          competitionModelIds,
        );
      } else {
        await refreshLeaderboard().catch(() => null);
      }
    } catch (requestError) {
      if (controller.signal.aborted) {
        return;
      }
      setCompetitionError(requestError.message);
      setCompetitionPhase(COMPETITION_PHASE.ERROR);
    } finally {
      if (competitionAbortRef.current === controller) {
        competitionAbortRef.current = null;
      }
    }
  }

  async function handleToggleComparison() {
    if (comparisonOpen) {
      setComparisonOpen(false);
      return;
    }

    if (!selectedResult || !problem || !selectedResult.result_id) return;

    setComparisonOpen(true);
    setComparisonLoading(true);
    setComparisonError("");

    try {
      const comparisonResponse = await getResultComparison(selectedResult.result_id);
      setComparisonData(comparisonResponse);
    } catch (requestError) {
      setComparisonError(requestError.message);
    } finally {
      setComparisonLoading(false);
    }
  }

  async function handleRunAiAnalysis() {
    if (!selectedResult?.result_id) return;

    const resultId = selectedResult.result_id;
    const existingState = aiAnalysisByResultId[resultId];
    if (existingState?.status === "completed" && existingState?.payload) {
      return;
    }

    setAiAnalysisByResultId((currentValue) => ({
      ...currentValue,
      [resultId]: {
        status: "loading",
        payload: existingState?.payload || null,
        error: "",
      },
    }));

    try {
      const response = await runAiAnalysis(resultId);
      setAiAnalysisByResultId((currentValue) => ({
        ...currentValue,
        [resultId]: {
          status: "completed",
          payload: response,
          error: "",
        },
      }));
    } catch (requestError) {
      setAiAnalysisByResultId((currentValue) => ({
        ...currentValue,
        [resultId]: {
          status: "error",
          payload: null,
          error: requestError.message,
        },
      }));
    }
  }

  function handleToggleAiAnalysisBreakdown() {
    if (!selectedResult?.result_id) return;
    setAiAnalysisExpandedByResultId((currentValue) => ({
      ...currentValue,
      [selectedResult.result_id]: !currentValue[selectedResult.result_id],
    }));
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">root@arena:~/evaluation$ ./start_dashboard</p>
          <h1>
            AICodeArena<span className="terminal-cursor" aria-hidden="true">_</span>
          </h1>
          <p className="subtitle">
            Controlled evaluation framework for AI-generated code
          </p>
        </div>
        <div className="header-badges">
          <span className={`badge ${connected ? "online" : "offline"}`}>
            {connected ? "[OK] BACKEND CONNECTED" : "[ERR] BACKEND DISCONNECTED"}
          </span>
          <span className="badge neutral">[API] {API_BASE_URL}</span>
          <span className="badge neutral">[PROBLEMS] {problems.length}</span>
        </div>
      </header>

      {error && (
        <div className="error-banner" role="alert">
          <strong>[REQUEST_FAILED]</strong> {error}
          <span className="api-hint">API: {API_BASE_URL}</span>
        </div>
      )}

      <PromptModal
        open={showPrompt}
        prompt={prompt}
        onClose={() => setShowPrompt(false)}
      />

      <section className="content-section view-switcher">
        <p className="eyebrow">$ select view</p>
        <div className="actions">
          <ActionButton
            loading={false}
            onClick={() => setActiveView(TOP_LEVEL_VIEW.COMPETITION)}
            variant={activeView === TOP_LEVEL_VIEW.COMPETITION ? "primary" : "ghost"}
            disabled={false}
          >
            [ COMPETITION ]
          </ActionButton>
          <ActionButton
            loading={false}
            onClick={() => setActiveView(TOP_LEVEL_VIEW.MODEL_INFO)}
            variant={activeView === TOP_LEVEL_VIEW.MODEL_INFO ? "primary" : "ghost"}
            disabled={false}
          >
            [ MODEL INFO ]
          </ActionButton>
        </div>
      </section>

      {activeView === TOP_LEVEL_VIEW.MODEL_INFO ? (
        <main className="model-info-layout">
          <ModelCatalogSection loading={loadingProblems} models={models} />
        </main>
      ) : (
      <main className="dashboard-grid">
        <ProblemList
          loading={loadingProblems}
          problems={problems}
          selectedId={selectedId}
          onSelect={setSelectedId}
          disabled={competitionRunning}
        />

        <div className="detail-column">
          {loadingProblems ? (
            <LoadingPanel
              title="Loading problems"
              message={`Connecting to ${API_BASE_URL}…`}
            />
          ) : loadingDetails ? (
            <LoadingPanel
              title="Loading problem details"
              message="Fetching prompt and problem overview…"
            />
          ) : problem ? (
            <>
              <ProblemOverview
                problem={problem}
                files={files}
                running={competitionRunning}
                disabled={competitionRunning}
                onViewPrompt={() => setShowPrompt(true)}
                onRunCompetition={handleCompetition}
              />

              {competitionPhase === COMPETITION_PHASE.ERROR ? (
                <section className="content-section empty-state">
                  <h3>COMPETITION_ERROR</h3>
                  <p>&gt; {competitionError}</p>
                  <div className="actions top-gap">
                    <ActionButton
                      loading={false}
                      onClick={handleCompetition}
                      variant="primary"
                      disabled={false}
                    >
                      [ RETRY COMPETITION ]
                    </ActionButton>
                  </div>
                </section>
              ) : competitionVisible ? (
                <>
                  <section className="content-section">
                    <p className="eyebrow">$ competition --status</p>
                    <h3>COMPETITION STATUS</h3>
                    <p>
                      {competitionPhase === COMPETITION_PHASE.RUNNING
                        ? "Competition is running."
                        : "Competition finished."}
                    </p>
                    <p>
                      Completed: {completedModelCount} / {expectedModelCount || competitionModelNames.length}
                    </p>
                    <p className="muted">
                      {competitionNotice ||
                        "Results appear automatically as each model finishes."}
                    </p>
                  </section>

                  <LeaderboardSection
                    entries={competitionResults}
                    loading={false}
                    selectedModelName={selectedResult?.model_name || selectedModelName}
                    onSelectModel={(entry) => {
                      setSelectedModelName(entry.model_name);
                      setSelectedResultId(entry.result_id);
                      setComparisonOpen(false);
                      setComparisonData(null);
                      setComparisonError("");
                    }}
                    modelCatalog={models}
                    title="CURRENT RUN"
                    eyebrow={
                      competitionRunId
                        ? `$ competition --run ${competitionRunId}`
                        : "$ competition --current-run"
                    }
                    emptyMessage="> No current run results are loaded yet."
                  />

                  <section className="content-section">
                    <div className="section-heading compact">
                      <div>
                        <p className="eyebrow">$ leaderboard --mode best</p>
                        <h3>ALL-TIME BEST</h3>
                      </div>
                      <ActionButton
                        loading={false}
                        onClick={() => setShowAllTimeBest((currentValue) => !currentValue)}
                        variant="ghost"
                        aria-expanded={showAllTimeBest}
                        aria-controls="all-time-best-panel"
                      >
                        {showAllTimeBest
                          ? "[ HIDE ALL-TIME BEST ]"
                          : "[ SHOW ALL-TIME BEST ]"}
                      </ActionButton>
                    </div>

                    {showAllTimeBest ? (
                      <div id="all-time-best-panel">
                        <LeaderboardSection
                          entries={leaderboard}
                          loading={loadingLeaderboard}
                          selectedModelName={selectedResult?.model_name || selectedModelName}
                          onSelectModel={(entry) => {
                            setSelectedModelName(entry.model_name);
                            setSelectedResultId(entry.result_id);
                            setComparisonOpen(false);
                            setComparisonData(null);
                            setComparisonError("");
                          }}
                          modelCatalog={models}
                          emptyMessage="> No historical best results are available yet."
                          showHeader={false}
                        />
                      </div>
                    ) : null}
                  </section>

                  <ModelResultSection
                    result={selectedResult}
                    comparisonOpen={comparisonOpen}
                    comparisonLoading={comparisonLoading}
                    onToggleComparison={handleToggleComparison}
                    aiAnalysisState={selectedAiAnalysisState}
                    aiAnalysisExpanded={selectedAiAnalysisExpanded}
                    onRunAiAnalysis={handleRunAiAnalysis}
                    onToggleAiAnalysisBreakdown={handleToggleAiAnalysisBreakdown}
                    modelCatalog={models}
                  />

                  <ComparisonSection
                    open={comparisonOpen}
                    loading={comparisonLoading}
                    error={comparisonError}
                    comparison={comparisonData}
                  />
                </>
              ) : (
                <section className="content-section empty-state">
                  <h3>READY_TO_RUN</h3>
                  <p>
                    &gt; Review the problem overview, open the prompt if needed,
                    then run all models to generate the leaderboard and model diagnostics.
                  </p>
                </section>
              )}
            </>
          ) : (
            <section className="panel detail-panel empty-state">
              <h2>SELECT_A_PROBLEM</h2>
              <p>&gt; Choose an entry from ./problem_bank to begin.</p>
            </section>
          )}
        </div>
      </main>
      )}
    </div>
  );
}
