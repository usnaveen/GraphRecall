import SwiftUI

struct ProfileView: View {
    @AppStorage("graphrecall.apiBase") private var apiBase: String = APIConfig.baseURL.absoluteString
    @State private var tokenPresent = false
    @State private var cacheClearedMessage: String?

    var body: some View {
        ZStack {
            Circle()
                .fill(GRColor.accent.opacity(0.10))
                .frame(width: 240, height: 240)
                .blur(radius: 50)
                .offset(x: -100, y: -160)
                .allowsHitTesting(false)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    GRScreenHeader(title: "Profile", subtitle: "Account & app settings")

                    GlassCard {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("API base URL")
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                            TextField("http://127.0.0.1:8000", text: $apiBase)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .padding(12)
                                .background(
                                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                                        .fill(GRColor.fillSubtle)
                                )
                                .foregroundStyle(GRColor.textPrimary)
                                .font(GRType.body)
                            Text("Used by the iOS client for FastAPI calls.")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                        }
                    }
                    .padding(.horizontal, 20)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Session")
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                            HStack {
                                Circle()
                                    .fill(tokenPresent ? GRColor.accent : GRColor.warning.opacity(0.8))
                                    .frame(width: 8, height: 8)
                                Text(tokenPresent ? "Signed in" : "Not signed in")
                                    .font(GRType.body)
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                            Text("Concept Dump and feed sync need auth against your backend.")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textTertiary)
                            if !tokenPresent {
                                Button {
                                    Task {
                                        await APIClient.shared.setAccessToken("demo-local-token")
                                        tokenPresent = await APIClient.shared.getAccessToken() != nil
                                    }
                                } label: {
                                    Text("Sign in")
                                        .font(GRType.headline)
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 12)
                                        .foregroundStyle(GRColor.canvas)
                                        .background(
                                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                                .fill(GRColor.accent)
                                        )
                                }
                                .padding(.top, 4)
                            }
                        }
                    }
                    .padding(.horizontal, 20)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Offline cache")
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                            Button("Clear offline review cache") {
                                Task {
                                    await OfflineReviewStore.shared.clearAll()
                                    cacheClearedMessage = "Offline cache cleared"
                                }
                            }
                            .font(GRType.body)
                            .foregroundStyle(GRColor.accent)
                            if let cacheClearedMessage {
                                Text(cacheClearedMessage)
                                    .font(GRType.caption)
                                    .foregroundStyle(GRColor.textSecondary)
                            }
                        }
                    }
                    .padding(.horizontal, 20)

                    GlassCard {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("About")
                                .font(GRType.headline)
                                .foregroundStyle(GRColor.textPrimary)
                            Text("GraphRecall")
                                .font(GRType.body)
                                .foregroundStyle(GRColor.textPrimary)
                            Text("Version 0.1.0 · Bundle com.usnaveen.graphrecall")
                                .font(GRType.caption)
                                .foregroundStyle(GRColor.textSecondary)
                        }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.bottom, GRLayout.dockClearance)
            }
        }
        .task {
            tokenPresent = await APIClient.shared.getAccessToken() != nil
        }
    }
}

#Preview { ProfileView().preferredColorScheme(.dark) }
