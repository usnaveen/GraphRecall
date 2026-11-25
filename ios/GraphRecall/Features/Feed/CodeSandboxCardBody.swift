import SwiftUI
import UIKit
import WebKit

/// Interactive on-device JavaScript code-completion card body.
/// Executes user code 100% offline inside a locked-down WKWebView and surfaces
/// per-test pass/fail results, console output, and a collapsible hint.
struct CodeSandboxCardBody: View {
    let item: FeedItem
    var onReveal: (() -> Void)? = nil
    var onComplete: ((Int, Int, Int) -> Void)? = nil

    @State private var code = ""
    @State private var showHint = false
    @State private var showSolution = false
    @State private var isRunning = false
    @State private var runToken = 0
    @State private var executionResult: SandboxExecutionResult?
    @FocusState private var editorFocused: Bool

    private var payload: SandboxChallengePayload { item.sandboxPayload }

    private var titleText: String { payload.title }
    private var promptText: String { payload.prompt }
    private var starterCode: String { payload.starterCode }
    private var solutionCode: String? { payload.solutionCode }
    private var hintText: String? { payload.hint }
    private var difficultyLabel: String { payload.difficulty.uppercased() }

    private var difficultyTone: GRTone {
        switch difficultyLabel.lowercased() {
        case "easy": return .success
        case "hard": return .coral
        default: return .amber
        }
    }

    private var languageLabel: String { payload.language.uppercased() }
    private var testCases: [SandboxTestCase] { payload.testCases }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            headerView
            promptView
            editorView
            controlsRow

            if showHint, let hintText {
                hintBox(hintText)
            }

            if showSolution, let solutionCode {
                solutionBox(solutionCode)
            }

            if let result = executionResult {
                resultsPanel(result)
            }

            // Hidden locked-down WKWebView executing the sandboxed test suite.
            SandboxRunnerWebView(
                code: code,
                testCases: testCases,
                runToken: runToken
            ) { result in
                isRunning = false
                withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                    executionResult = result
                }
                if result.total > 0 && result.passed == result.total && result.error == nil {
                    GRHaptics.success()
                } else {
                    GRHaptics.warning()
                }
                onReveal?()
                onComplete?(result.passed, result.total, result.elapsedMs)
            }
            .frame(width: 1, height: 1)
            .opacity(0.01)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
        .onAppear {
            if code.isEmpty {
                code = starterCode
            }
        }
        .onChange(of: item.id) { _, _ in
            code = starterCode
            showHint = false
            showSolution = false
            isRunning = false
            executionResult = nil
        }
    }

    // MARK: - Subviews

    private var headerView: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "chevron.left.forwardslash.chevron.right")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(GRColor.accentCyan)

            Text(titleText)
                .font(GRType.title)
                .foregroundStyle(GRColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: 4)

            GRChip(title: difficultyLabel, style: .tinted(difficultyTone), compact: true)
            GRChip(title: languageLabel == "JAVASCRIPT" ? "JS" : languageLabel, style: .tinted(.cyan), compact: true)
        }
    }

    private var promptView: some View {
        Text(promptText)
            .font(GRType.body)
            .foregroundStyle(GRColor.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var editorView: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("EDITOR")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.textTertiary)
                Spacer()
                Text("\(testCases.count) test\(testCases.count == 1 ? "" : "s")")
                    .font(GRType.micro)
                    .foregroundStyle(GRColor.accentCyan)
            }

            SandboxCodeTextEditor(text: $code)
                .focused($editorFocused)
                .frame(minHeight: 155, maxHeight: 230)
                .padding(8)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(GRColor.canvas.opacity(0.92))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(editorFocused ? GRColor.accentLine : GRColor.strokeStrong, lineWidth: 1)
                )
                .accessibilityIdentifier("codeSandbox.editor")
        }
    }

    private var controlsRow: some View {
        HStack(spacing: 8) {
            Button {
                GRHaptics.tap()
                editorFocused = false
                isRunning = true
                runToken += 1
            } label: {
                if isRunning {
                    ProgressView()
                        .tint(GRColor.canvas)
                } else {
                    Label("Run", systemImage: "play.fill")
                        .font(GRType.caption.weight(.bold))
                }
            }
            .buttonStyle(.glassProminent)
            .buttonBorderShape(.capsule)
            .controlSize(.regular)
            .tint(GRColor.accent)
            .foregroundStyle(GRColor.canvas)
            .disabled(isRunning || code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityIdentifier("codeSandbox.run")

            if hintText != nil {
                Button {
                    GRHaptics.tap()
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showHint.toggle()
                    }
                } label: {
                    Label(showHint ? "Hide Hint" : "Hint", systemImage: "lightbulb")
                        .font(GRType.caption.weight(.semibold))
                }
                .buttonStyle(.glass)
                .buttonBorderShape(.capsule)
                .controlSize(.regular)
                .foregroundStyle(GRColor.accentCyan)
                .accessibilityIdentifier("codeSandbox.hint")
            }

            Spacer(minLength: 0)

            if solutionCode != nil {
                Button {
                    GRHaptics.tap()
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showSolution.toggle()
                    }
                    onReveal?()
                } label: {
                    Image(systemName: showSolution ? "eye.slash" : "eye")
                        .font(.system(size: 13, weight: .semibold))
                }
                .buttonStyle(.glass)
                .buttonBorderShape(.circle)
                .controlSize(.regular)
                .foregroundStyle(GRColor.textSecondary)
                .accessibilityLabel(showSolution ? "Hide solution" : "Show solution")
            }

            Button {
                GRHaptics.tap()
                editorFocused = false
                withAnimation(.easeInOut(duration: 0.2)) {
                    code = starterCode
                    executionResult = nil
                    showSolution = false
                }
            } label: {
                Label("Reset", systemImage: "arrow.counterclockwise")
                    .font(GRType.caption.weight(.semibold))
            }
            .buttonStyle(.glass)
            .buttonBorderShape(.capsule)
            .controlSize(.regular)
            .foregroundStyle(GRColor.textSecondary)
            .accessibilityIdentifier("codeSandbox.reset")
        }
    }

    private func hintBox(_ hint: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lightbulb.fill")
                .font(.caption)
                .foregroundStyle(GRColor.accentCyan)
                .padding(.top, 2)
            Text(hint)
                .font(GRType.caption)
                .foregroundStyle(GRColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .grGlassEffect(.clear, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(GRColor.cyanSoft, lineWidth: 1)
        )
    }

    private func solutionBox(_ solution: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("REFERENCE SOLUTION")
                .font(GRType.micro)
                .foregroundStyle(GRColor.accent)
            ScrollView(.horizontal, showsIndicators: false) {
                Text(solution)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(GRColor.accent)
                    .textSelection(.enabled)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(GRColor.accentSoft.opacity(0.45), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(GRColor.accentLine, lineWidth: 1)
        )
    }

    private func resultsPanel(_ result: SandboxExecutionResult) -> some View {
        let allPassed = result.total > 0 && result.passed == result.total && result.error == nil
        let statusTone: GRTone = allPassed ? .success : (result.passed * 2 >= max(1, result.total) && result.error == nil ? .amber : .danger)

        return GlassCard(cornerRadius: 16) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: allPassed ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                        .foregroundStyle(statusTone.color)
                    Text(allPassed ? "All Tests Passed" : "\(result.passed)/\(result.total) Tests Passed")
                        .font(GRType.headline)
                        .foregroundStyle(GRColor.textPrimary)
                    Spacer()
                    Text("\(result.elapsedMs) ms")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(GRColor.textTertiary)
                }

                if let error = result.error, !error.isEmpty {
                    Text(error)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(GRColor.danger)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(GRColor.danger.opacity(0.12), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }

                VStack(spacing: 6) {
                    ForEach(result.results) { test in
                        testRow(test)
                    }
                }

                if !result.stdout.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("CONSOLE OUTPUT")
                            .font(GRType.micro)
                            .foregroundStyle(GRColor.textTertiary)
                        Text(result.stdout)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(GRColor.textPrimary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                            .background(GRColor.canvas.opacity(0.8), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                }
            }
        }
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func testRow(_ test: SandboxExecutionResult.TestResult) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Image(systemName: test.passed ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(test.passed ? GRColor.success : GRColor.danger)
                Text(test.name)
                    .font(GRType.caption.weight(.semibold))
                    .foregroundStyle(GRColor.textPrimary)
                Spacer()
                Text(test.passed ? "PASS" : "FAIL")
                    .font(GRType.micro.weight(.bold))
                    .foregroundStyle(test.passed ? GRColor.success : GRColor.danger)
            }

            if !test.passed {
                if let err = test.error, !err.isEmpty {
                    Text(err)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(GRColor.danger)
                } else {
                    Text("Expected \(test.expected), got \(test.actual)")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(GRColor.textSecondary)
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            (test.passed ? GRColor.success : GRColor.danger).opacity(0.08),
            in: RoundedRectangle(cornerRadius: 10, style: .continuous)
        )
    }
}

// MARK: - Monospace Code Editor

/// SwiftUI `TextEditor` configured for code entry (no autocorrect, capitalization,
/// smart quotes, or smart dashes).
private struct SandboxCodeTextEditor: View {
    @Binding var text: String

    var body: some View {
        TextEditor(text: $text)
            .font(.system(.footnote, design: .monospaced))
            .foregroundStyle(GRColor.accentCyan)
            .tint(GRColor.accent)
            .scrollContentBackground(.hidden)
            .autocorrectionDisabled(true)
            .textInputAutocapitalization(.never)
            .keyboardType(.asciiCapable)
    }
}

// MARK: - Locked-down Offline WKWebView Runner

private struct SandboxRunnerWebView: UIViewRepresentable {
    let code: String
    let testCases: [SandboxTestCase]
    let runToken: Int
    let onResult: @MainActor (SandboxExecutionResult) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onResult: onResult)
    }

    func makeUIView(context: Context) -> WKWebView {
        let controller = WKUserContentController()
        let weakProxy = WeakSandboxMessageHandler(target: context.coordinator)
        controller.add(weakProxy, name: SandboxHTML.messageHandlerName)

        let config = WKWebViewConfiguration()
        config.userContentController = controller
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 7 / 255, green: 7 / 255, blue: 10 / 255, alpha: 1)
        webView.scrollView.isScrollEnabled = false
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.onResult = onResult
        guard runToken > 0, context.coordinator.lastRunToken != runToken else { return }
        context.coordinator.lastRunToken = runToken
        let html = SandboxHTML.render(code: code, testCases: testCases)
        webView.loadHTMLString(html, baseURL: nil)
    }

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: SandboxHTML.messageHandlerName)
    }

    @MainActor
    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        var onResult: @MainActor (SandboxExecutionResult) -> Void
        var lastRunToken = 0

        init(onResult: @escaping @MainActor (SandboxExecutionResult) -> Void) {
            self.onResult = onResult
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
        ) {
            // Only allow initial inline HTML load (about:blank); cancel all external or subresource navigations.
            if navigationAction.request.url?.absoluteString == "about:blank" {
                decisionHandler(.allow)
            } else {
                decisionHandler(.cancel)
            }
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == SandboxHTML.messageHandlerName,
                  let body = message.body as? [String: Any],
                  JSONSerialization.isValidJSONObject(body),
                  let data = try? JSONSerialization.data(withJSONObject: body),
                  let parsed = try? JSONDecoder().decode(SandboxExecutionResult.self, from: data)
            else { return }
            onResult(parsed)
        }
    }

    private final class WeakSandboxMessageHandler: NSObject, WKScriptMessageHandler {
        weak var target: (any WKScriptMessageHandler)?

        init(target: any WKScriptMessageHandler) {
            self.target = target
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            target?.userContentController(userContentController, didReceive: message)
        }
    }
}
