/**
 * Login Screen Component
 * Google OAuth sign-in with a beautiful, branded UI.
 */
import { GoogleLogin } from '@react-oauth/google';
import type { CredentialResponse } from '@react-oauth/google';
import { motion } from 'framer-motion';
import { useState, useRef } from 'react';
import { useAuthStore } from '../store/useAuthStore';

export function LoginScreen() {
    const { login, isLoading } = useAuthStore();
    const [loginError, setLoginError] = useState<string | null>(null);
    const loginAttemptRef = useRef(false); // prevent One Tap re-triggering

    const handleSuccess = async (credentialResponse: CredentialResponse) => {
        // Prevent duplicate attempts from One Tap auto-retry
        if (loginAttemptRef.current) return;
        loginAttemptRef.current = true;

        if (credentialResponse.credential) {
            try {
                setLoginError(null);
                await login(credentialResponse.credential);
            } catch (error) {
                console.error('Login failed:', error);
                setLoginError('Login failed. Please try again.');
            } finally {
                // Allow retry after a short delay to prevent rapid loops
                setTimeout(() => { loginAttemptRef.current = false; }, 3000);
            }
        } else {
            loginAttemptRef.current = false;
        }
    };

    const handleError = () => {
        console.error('Google Sign-In failed');
        setLoginError('Google Sign-In failed. Please try again.');
    };

    return (
        <div className="fixed inset-0 bg-[#07070A] flex items-center justify-center">
            {/* Background Gradient */}
            <div
                className="fixed inset-0 pointer-events-none"
                style={{
                    background: 'radial-gradient(ellipse at 50% 30%, rgba(182, 255, 46, 0.05) 0%, transparent 60%)'
                }}
            />

            {/* Noise Overlay */}
            <div className="noise-overlay" />

            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                className="relative z-10 text-center px-8"
            >
                {/* Logo */}
                <motion.div
                    initial={{ scale: 0.8 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: 0.2, duration: 0.5 }}
                    className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[#B6FF2E] to-[#2EFFE6] flex items-center justify-center mb-6 mx-auto shadow-lg shadow-[#B6FF2E]/20"
                >
                    <span className="text-3xl font-bold text-[#07070A]">G</span>
                </motion.div>

                {/* Title */}
                <h1 className="font-heading text-4xl font-bold text-white mb-2">
                    GraphRecall
                </h1>
                <p className="text-[#A6A8B1] text-lg mb-10 max-w-xs mx-auto">
                    Your lifetime active recall learning companion
                </p>

                {/* Google Sign-In Button */}
                <div className="flex justify-center">
                    {isLoading ? (
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="flex items-center gap-2 text-[#A6A8B1]"
                        >
                            <div className="h-5 w-5 rounded-full border-2 border-[#B6FF2E] border-t-transparent animate-spin" />
                            <span>Signing in...</span>
                        </motion.div>
                    ) : (
                        <GoogleLogin
                            onSuccess={handleSuccess}
                            onError={handleError}
                            theme="filled_black"
                            size="large"
                            shape="pill"
                            text="continue_with"
                        />
                    )}
                </div>

                {/* Error Message */}
                {loginError && (
                    <motion.p
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="text-red-400 text-sm mt-4"
                    >
                        {loginError}
                    </motion.p>
                )}

                {/* Footer */}
                <p className="text-[#5A5C66] text-xs mt-12">
                    By continuing, you agree to our Terms of Service
                </p>
            </motion.div>
        </div>
    );
}
