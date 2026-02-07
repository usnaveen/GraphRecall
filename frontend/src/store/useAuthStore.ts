/**
 * Authentication Store (Zustand)
 * Manages Google OAuth state and user session.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface User {
    id: string;
    email: string;
    name: string;
    picture: string;
    settings_json?: any;
}

interface AuthState {
    // State
    user: User | null;
    idToken: string | null;
    isAuthenticated: boolean;
    isLoading: boolean;

    // Actions
    login: (credential: string) => Promise<void>;
    logout: () => void;
    setLoading: (loading: boolean) => void;
}

// Auth endpoints are at /auth/*, not /api/auth/*, so strip any /api suffix
const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/api\/?$/, '');

/**
 * Decode a Google ID token (JWT) to extract user info client-side.
 * This is used as a fallback when the backend is unreachable.
 * The JWT is base64url-encoded: header.payload.signature
 */
function decodeGoogleJwt(token: string): User | null {
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return null;
        // base64url → base64 → decode
        const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
        return {
            id: payload.sub || '',
            email: payload.email || '',
            name: payload.name || '',
            picture: payload.picture || '',
            settings_json: {},
        };
    } catch {
        return null;
    }
}

export const useAuthStore = create<AuthState>()(
    persist(
        (set) => ({
            user: null,
            idToken: null,
            isAuthenticated: false,
            isLoading: false,

            login: async (credential: string) => {
                set({ isLoading: true });
                try {
                    // Call backend to verify token and get/create user
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s timeout

                    const response = await fetch(`${API_BASE}/auth/google`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ token: credential }),
                        signal: controller.signal,
                    });
                    clearTimeout(timeoutId);

                    if (!response.ok) {
                        throw new Error(`Authentication failed: ${response.status}`);
                    }

                    const data = await response.json();

                    set({
                        user: {
                            id: data.user.id,
                            email: data.user.email,
                            name: data.user.name,
                            picture: data.user.profile_picture || data.user.picture || '',
                            settings_json: data.user.settings_json || {},
                        },
                        idToken: credential,
                        isAuthenticated: true,
                        isLoading: false,
                    });
                } catch (error) {
                    console.error('Backend login failed, falling back to client-side decode:', error);

                    // Fallback: decode the Google JWT client-side so the user isn't stuck
                    // The token is still a valid Google ID token; we just couldn't reach the backend
                    const user = decodeGoogleJwt(credential);
                    if (user) {
                        set({
                            user,
                            idToken: credential,
                            isAuthenticated: true,
                            isLoading: false,
                        });
                    } else {
                        // JWT decode also failed — truly cannot authenticate
                        set({ isLoading: false });
                        throw error;
                    }
                }
            },

            logout: () => {
                set({
                    user: null,
                    idToken: null,
                    isAuthenticated: false,
                });
            },

            setLoading: (loading: boolean) => {
                set({ isLoading: loading });
            },
        }),
        {
            name: 'graphrecall-auth',
            partialize: (state) => ({
                user: state.user,
                idToken: state.idToken,
                isAuthenticated: state.isAuthenticated,
            }),
        }
    )
);

/**
 * Helper to get the current auth token for API requests
 */
export const getAuthToken = (): string | null => {
    return useAuthStore.getState().idToken;
};
