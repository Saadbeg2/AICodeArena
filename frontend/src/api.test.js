import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getResultComparison,
  runAiAnalysis,
  runCompetition,
} from "./api";

describe("api competition timeout handling", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("uses the quick competition startup timeout", async () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    global.fetch = vi.fn((_, options) => (
      new Promise((_, reject) => {
        options.signal.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      })
    ));

    let capturedError = null;
    const requestPromise = runCompetition(1, ["gemini-flash-latest"]).catch((error) => {
      capturedError = error;
      return null;
    });
    expect(setTimeoutSpy).toHaveBeenCalledWith(
      expect.any(Function),
      15000,
    );

    await vi.advanceTimersByTimeAsync(15000);
    await requestPromise;

    expect(capturedError).toBeInstanceOf(Error);
    expect(capturedError.message).toBe(
      "The backend did not create a competition run in time. Please retry.",
    );
  });

  it("loads comparison data from the public results route", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ result_id: 7, comparison_available: true }),
    });

    const response = await getResultComparison(7);

    expect(response.result_id).toBe(7);
    expect(global.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/results/7/comparison",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("posts to the AI analysis route", async () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ result_id: 7, analysis_status: "completed" }),
    });

    const response = await runAiAnalysis(7);

    expect(response.result_id).toBe(7);
    expect(setTimeoutSpy).toHaveBeenCalledWith(
      expect.any(Function),
      120000,
    );
    expect(global.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/results/7/ai-analysis",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
});
