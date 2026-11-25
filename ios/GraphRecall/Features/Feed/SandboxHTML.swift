import Foundation

/// Test case payload sent into the offline WKWebView JavaScript runner.
struct SandboxTestCase: Identifiable, Hashable, Codable, Sendable {
    var id: String { "\(name)::\(expression)" }
    let name: String
    let expression: String
    let expectedRepr: String

    enum CodingKeys: String, CodingKey {
        case name
        case expression
        case expectedRepr = "expected_repr"
    }
}

/// Structured execution outcome posted back from `WKWebView` via `sandboxResult`.
struct SandboxExecutionResult: Hashable, Codable, Sendable {
    struct TestResult: Identifiable, Hashable, Codable, Sendable {
        var id: String { "\(name)::\(expected)" }
        let name: String
        let passed: Bool
        let actual: String
        let expected: String
        let error: String?
    }

    let passed: Int
    let total: Int
    let results: [TestResult]
    let stdout: String
    let error: String?
    let elapsedMs: Int
}

/// Builds a locked-down, 100% offline HTML/JS runner string for `WKWebView`.
/// User code and test cases are Base64-UTF8 encoded so `</script>`, backticks,
/// quotes, and Unicode separators can never break out of the script context.
enum SandboxHTML {
    static let messageHandlerName = "sandboxResult"

    private struct RunnerPayload: Encodable {
        let code: String
        let tests: [SandboxTestCase]
    }

    static func render(code: String, testCases: [SandboxTestCase]) -> String {
        let payload = RunnerPayload(code: code, tests: testCases)
        let jsonData = (try? JSONEncoder().encode(payload)) ?? Data("{\"code\":\"\",\"tests\":[]}".utf8)
        let base64Payload = jsonData.base64EncodedString()

        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline';">
        <style>
          :root { color-scheme: dark; }
          html, body {
            margin: 0;
            padding: 8px;
            background: #07070A;
            color: #F5F7FA;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 12px;
            line-height: 1.45;
          }
          .ok { color: #B6FF2E; }
          .err { color: #F87171; }
          .dim { color: #2EFFE6; }
        </style>
        </head>
        <body>
        <div id="status" class="dim">Running sandbox...</div>
        <script>
        (function () {
          "use strict";

          function decodeBase64Utf8(b64) {
            var binary = atob(b64);
            var bytes = new Uint8Array(binary.length);
            for (var i = 0; i < binary.length; i++) {
              bytes[i] = binary.charCodeAt(i);
            }
            return new TextDecoder("utf-8").decode(bytes);
          }

          function normalizeForCompare(value) {
            if (Object.is(value, -0)) return 0;
            if (typeof value === "number") {
              if (Number.isNaN(value)) return "__NaN__";
              if (!Number.isFinite(value)) return value > 0 ? "__Infinity__" : "__-Infinity__";
              return value;
            }
            if (Array.isArray(value)) {
              return value.map(normalizeForCompare);
            }
            if (value && typeof value === "object") {
              var out = {};
              var keys = Object.keys(value).sort();
              for (var i = 0; i < keys.length; i++) {
                var k = keys[i];
                out[k] = normalizeForCompare(value[k]);
              }
              return out;
            }
            return value;
          }

          function safeStringify(value) {
            if (value === undefined) return "undefined";
            try {
              return JSON.stringify(normalizeForCompare(value));
            } catch (e) {
              return String(value);
            }
          }

          function deepEqual(actual, expected) {
            return safeStringify(actual) === safeStringify(expected);
          }

          function formatLogArg(arg) {
            if (typeof arg === "string") return arg;
            if (arg === undefined) return "undefined";
            try {
              return JSON.stringify(arg);
            } catch (e) {
              return String(arg);
            }
          }

          var payload = JSON.parse(decodeBase64Utf8("\(base64Payload)"));
          var tests = Array.isArray(payload.tests) ? payload.tests : [];
          var logs = [];
          var origLog = console.log;
          var origWarn = console.warn;
          var origError = console.error;
          var started = Date.now();
          var passed = 0;
          var results = [];
          var topError = null;

          console.log = function () {
            var parts = [];
            for (var i = 0; i < arguments.length; i++) parts.push(formatLogArg(arguments[i]));
            logs.push(parts.join(" "));
          };
          console.warn = console.log;
          console.error = console.log;

          try {
            var sandboxFactory = new Function(
              "fetch",
              "XMLHttpRequest",
              "WebSocket",
              "importScripts",
              payload.code + "\\n;return function(__expr__) { return eval(__expr__); };"
            );
            var blockedApi = function () {
              throw new Error("Network and worker APIs are disabled in the offline sandbox.");
            };
            var evaluateExpr = sandboxFactory(blockedApi, blockedApi, blockedApi, blockedApi);

            for (var i = 0; i < tests.length; i++) {
              var tc = tests[i];
              var expectedVal;
              try {
                expectedVal = JSON.parse(tc.expected_repr);
              } catch (_) {
                expectedVal = tc.expected_repr;
              }

              try {
                var actualVal = evaluateExpr(tc.expression);
                var ok = deepEqual(actualVal, expectedVal);
                if (ok) passed += 1;
                results.push({
                  name: tc.name,
                  passed: ok,
                  actual: safeStringify(actualVal),
                  expected: tc.expected_repr,
                  error: null
                });
              } catch (testErr) {
                results.push({
                  name: tc.name,
                  passed: false,
                  actual: "error",
                  expected: tc.expected_repr,
                  error: testErr && testErr.message ? String(testErr.message) : String(testErr)
                });
              }
            }
          } catch (err) {
            topError = err && err.message ? String(err.message) : String(err);
            for (var j = 0; j < tests.length; j++) {
              results.push({
                name: tests[j].name,
                passed: false,
                actual: "error",
                expected: tests[j].expected_repr,
                error: topError
              });
            }
          } finally {
            console.log = origLog;
            console.warn = origWarn;
            console.error = origError;
          }

          var elapsedMs = Math.max(0, Date.now() - started);
          var summary = {
            passed: passed,
            total: tests.length,
            results: results,
            stdout: logs.join("\\n"),
            error: topError,
            elapsedMs: elapsedMs
          };

          var statusEl = document.getElementById("status");
          if (statusEl) {
            statusEl.className = topError ? "err" : (passed === tests.length ? "ok" : "dim");
            statusEl.textContent = topError
              ? ("Error: " + topError)
              : ("Passed " + passed + "/" + tests.length + " (" + elapsedMs + " ms)");
          }

          if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.\(messageHandlerName)) {
            window.webkit.messageHandlers.\(messageHandlerName).postMessage(summary);
          }
        })();
        </script>
        </body>
        </html>
        """
    }
}
