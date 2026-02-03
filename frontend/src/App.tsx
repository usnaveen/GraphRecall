import { useEffect } from 'react';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { motion, AnimatePresence } from 'framer-motion';
import { TopBar } from './components/TopBar';
import { LiquidDock } from './components/LiquidDock';
import { FeedScreen } from './screens/FeedScreen';
import { GraphScreen } from './screens/GraphScreen';
import { CreateScreen } from './screens/CreateScreen';
import { AssistantScreen } from './screens/AssistantScreen';
import { ProfileScreen } from './screens/ProfileScreen';
import { LoginScreen } from './screens/LoginScreen';
import { useAppStore } from './store/useAppStore';
import { useAuthStore } from './store/useAuthStore';

// Get Google Client ID from environment
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

function AuthenticatedApp() {
  const { activeTab, setActiveTab, fetchFeed, fetchStats, isLoading, feedItems } = useAppStore();

  useEffect(() => {
    // Initial data fetch after authentication
    // Only fetch if we don't have items and aren't already loading
    if (feedItems.length === 0 && !isLoading) {
      fetchFeed();
      fetchStats();
    }
  }, [fetchFeed, fetchStats]); // Removed feedItems/isLoading from deps to avoid re-triggering, or keep them but trust the check

  const renderScreen = () => {
    switch (activeTab) {
      case 'feed':
        return <FeedScreen key="feed" />;
      case 'graph':
        return <GraphScreen key="graph" />;
      case 'create':
        return <CreateScreen key="create" />;
      case 'assistant':
        return <AssistantScreen key="assistant" />;
      case 'profile':
        return <ProfileScreen key="profile" />;
      default:
        return <FeedScreen key="feed" />;
    }
  };

  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-[#07070A] flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center"
        >
          <div className="w-24 h-24 flex items-center justify-center mb-4 mx-auto rounded-3xl overflow-hidden">
            <img src="/logo.png" alt="GraphRecall Logo" className="w-full h-full object-contain" />
          </div>
          <h1 className="font-heading text-2xl font-bold text-white">GraphRecall</h1>
          <p className="text-sm text-[#A6A8B1] mt-2">Loading your knowledge...</p>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#07070A] text-white relative overflow-hidden">
      {/* Background Gradient */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          background: 'radial-gradient(ellipse at 50% 0%, rgba(182, 255, 46, 0.03) 0%, transparent 50%)'
        }}
      />

      {/* Noise Overlay */}
      <div className="noise-overlay" />

      {/* Top Bar */}
      <TopBar />

      {/* Main Content */}
      <main className="pt-16 pb-28 px-4 min-h-screen lg:pb-10 lg:pr-24 lg:px-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-lg mx-auto w-full lg:max-w-[1440px]"
          >
            {renderScreen()}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Bottom Liquid Glass Dock */}
      <LiquidDock
        activeTab={activeTab}
        onTabChange={setActiveTab}
        orientation="horizontal"
        className="lg:hidden"
      />
      <LiquidDock
        activeTab={activeTab}
        onTabChange={setActiveTab}
        orientation="vertical"
        className="hidden lg:flex"
      />
    </div>
  );
}

function App() {
  const { isAuthenticated, isLoading } = useAuthStore();

  // Show loading state while checking persisted auth
  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-[#07070A] flex items-center justify-center">
        <div className="h-8 w-8 rounded-full border-2 border-[#B6FF2E] border-t-transparent animate-spin" />
      </div>
    );
  }

  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      {isAuthenticated ? <AuthenticatedApp /> : <LoginScreen />}
    </GoogleOAuthProvider>
  );
}

export default App;
