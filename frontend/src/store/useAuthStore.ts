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

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
                    const response = await fetch(`${API_BASE}/auth/google`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ token: credential }),
                    });

                    if (!response.ok) {
                        throw new Error('Authentication failed');
                    }

                    const data = await response.json();

                    set({
                        user: {
                            id: data.user.id,
                            email: data.user.email,
                            name: data.user.name,
                            picture: data.user.picture,
                        },
                        idToken: credential,
                        isAuthenticated: true,
                        isLoading: false,
                    });
                } catch (error) {
                    console.error('Login failed:', error);
                    set({ isLoading: false });
                    throw error;
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
