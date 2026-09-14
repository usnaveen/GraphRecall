import Foundation
import Speech
import AVFoundation
import Observation

/// On-device dictation for concept dumps, voice notes and Assistant questions.
@MainActor
@Observable
final class GRDictation {
    private(set) var isRecording = false
    private(set) var transcript = ""
    var errorMessage: String?

    @ObservationIgnored private let recognizer = SFSpeechRecognizer(locale: Locale.current) ?? SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    @ObservationIgnored private var audioEngine: AVAudioEngine?
    @ObservationIgnored private var request: SFSpeechAudioBufferRecognitionRequest?
    @ObservationIgnored private var task: SFSpeechRecognitionTask?

    func start(onUpdate: @escaping @MainActor (String) -> Void) async {
        guard !isRecording else { return }
        errorMessage = nil

        let speechStatus = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        guard speechStatus == .authorized else {
            errorMessage = "Allow speech recognition in Settings to dictate."
            return
        }
        guard await AVAudioApplication.requestRecordPermission() else {
            errorMessage = "Allow microphone access in Settings to dictate."
            return
        }
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Dictation isn’t available right now."
            return
        }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let engine = AVAudioEngine()
            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            Self.installTap(on: engine.inputNode, feeding: request)
            engine.prepare()
            try engine.start()

            audioEngine = engine
            self.request = request
            transcript = ""
            isRecording = true

            task = Self.recognize(with: recognizer, request: request) { [weak self] text, finished in
                Task { @MainActor in
                    guard let self, self.isRecording else { return }
                    if let text {
                        self.transcript = text
                        onUpdate(text)
                    }
                    if finished { self.stop() }
                }
            }
        } catch {
            errorMessage = "Couldn’t start dictation."
            stop()
        }
    }

    func stop() {
        audioEngine?.stop()
        audioEngine?.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.finish()
        audioEngine = nil
        request = nil
        task = nil
        if isRecording {
            isRecording = false
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    // Audio + recognition callbacks run off the main actor; keep them out of its isolation.
    nonisolated private static func installTap(on input: AVAudioInputNode, feeding request: SFSpeechAudioBufferRecognitionRequest) {
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            request.append(buffer)
        }
    }

    nonisolated private static func recognize(
        with recognizer: SFSpeechRecognizer,
        request: SFSpeechAudioBufferRecognitionRequest,
        handler: @escaping @Sendable (String?, Bool) -> Void
    ) -> SFSpeechRecognitionTask {
        recognizer.recognitionTask(with: request) { result, error in
            handler(result?.bestTranscription.formattedString, (result?.isFinal ?? false) || error != nil)
        }
    }
}
