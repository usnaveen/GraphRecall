import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TopBar } from './components/TopBar';
import { LiquidDock } from './components/LiquidDock';
import { FeedScreen } from './screens/FeedScreen';
import { GraphScreen } from './screens/GraphScreen';
import { CreateScreen } from './screens/CreateScreen';
import { AssistantScreen } from './screens/AssistantScreen';
import { ProfileScreen } from './screens/ProfileScreen';
import type { TabType } from './types';

function App() {
  const [activeTab, setActiveTab] = useState<TabType>('feed');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Simulate initial load
    const timer = setTimeout(() => setIsLoading(false), 800);
    return () => clearTimeout(timer);
  }, []);

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
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[#B6FF2E] to-[#2EFFE6] flex items-center justify-center mb-4 mx-auto">
            <span className="text-2xl font-bold text-[#07070A]">G</span>
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
      <main className="pt-16 pb-28 px-4 min-h-screen">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-lg mx-auto"
          >
            {renderScreen()}
          </motion.div>
        </AnimatePresence>
      </main>

      {/* Bottom Liquid Glass Dock */}
      <LiquidDock activeTab={activeTab} onTabChange={setActiveTab} />
    </div>
  );
}

export default App;
