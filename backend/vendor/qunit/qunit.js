(function () {
  const callbacks = {};
  const tests = [];

  function emit(eventName, payload) {
    (callbacks[eventName] || []).forEach(function (handler) {
      handler(payload);
    });
  }

  function normalizeValue(value) {
    try {
      return JSON.parse(JSON.stringify(value));
    } catch (error) {
      return String(value);
    }
  }

  function createAssert(testState) {
    function record(result) {
      testState.assertions.push(result);
      emit("assertion", result);
    }

    return {
      ok(value, message) {
        record({
          result: Boolean(value),
          message: message || "Expected value to be truthy.",
          actual: normalizeValue(value),
          expected: true,
        });
      },
      equal(actual, expected, message) {
        record({
          result: actual == expected,
          message: message || "Expected values to be equal.",
          actual: normalizeValue(actual),
          expected: normalizeValue(expected),
        });
      },
      strictEqual(actual, expected, message) {
        record({
          result: actual === expected,
          message: message || "Expected values to be strictly equal.",
          actual: normalizeValue(actual),
          expected: normalizeValue(expected),
        });
      },
      deepEqual(actual, expected, message) {
        const actualJson = JSON.stringify(actual);
        const expectedJson = JSON.stringify(expected);
        record({
          result: actualJson === expectedJson,
          message: message || "Expected values to be deeply equal.",
          actual: normalizeValue(actual),
          expected: normalizeValue(expected),
        });
      },
    };
  }

  async function runTest(testDefinition) {
    const startedAt = Date.now();
    const testState = {
      assertions: [],
      runtimeError: null,
    };

    try {
      const maybePromise = testDefinition.callback(createAssert(testState));
      if (maybePromise && typeof maybePromise.then === "function") {
        await maybePromise;
      }
    } catch (error) {
      testState.runtimeError = {
        name: error && error.name ? error.name : "Error",
        message: error && error.message ? error.message : String(error),
      };
    }

    const failedAssertions = testState.assertions.filter(function (assertion) {
      return !assertion.result;
    });
    const testResult = {
      name: testDefinition.name,
      total: testState.assertions.length,
      failed: failedAssertions.length,
      passed: testState.assertions.length - failedAssertions.length,
      runtimeError: testState.runtimeError,
      assertions: testState.assertions,
      duration: Date.now() - startedAt,
    };
    emit("testEnd", testResult);
    return testResult;
  }

  const QUnit = {
    config: {
      autostart: false,
    },
    on(eventName, handler) {
      callbacks[eventName] = callbacks[eventName] || [];
      callbacks[eventName].push(handler);
    },
    test(name, callback) {
      tests.push({ name: name, callback: callback });
    },
    async start() {
      const results = [];
      for (const testDefinition of tests) {
        results.push(await runTest(testDefinition));
      }

      emit("runEnd", {
        testCounts: {
          total: results.length,
          failed: results.filter(function (result) {
            return result.failed > 0 || result.runtimeError !== null;
          }).length,
          passed: results.filter(function (result) {
            return result.failed === 0 && result.runtimeError === null;
          }).length,
        },
        results: results,
      });
    },
  };

  window.QUnit = QUnit;
})();
