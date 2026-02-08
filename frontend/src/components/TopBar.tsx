import { motion, AnimatePresence } from 'framer-motion';
import { Flame, Wifi, WifiOff, Layers, ChevronDown, Bookmark } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useEffect, useState } from 'react';
import { BackendStatusPanel } from './BackendStatusPanel';

export function TopBar() {
  const { itemsReviewedToday, dailyItemLimit, userStats, setActiveTab, feedMode, setFeedMode } = useAppStore();
  const [backendStatus, setBackendStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking');
  const [statusPanelOpen, setStatusPanelOpen] = useState(false);
  const [feedMenuOpen, setFeedMenuOpen] = useState(false);
  const progressPercent = (itemsReviewedToday / dailyItemLimit) * 100;

  // Check backend connection on mount
  useEffect(() => {
    const checkBackend = async () => {
      try {
        const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
        const healthUrl = API_BASE.replace('/api', '/health');
        const response = await fetch(healthUrl, { method: 'GET' });
        if (response.ok) {
          setBackendStatus('connected');
        } else {
          setBackendStatus('disconnected');
        }
      } catch {
        setBackendStatus('disconnected');
      }
    };

    checkBackend();
    const interval = setInterval(checkBackend, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <>
      {/* Edge frost gradient — purely decorative, behind everything */}
      <div className="fixed top-0 left-0 right-0 z-40 h-20 topbar-frost-edge" />

      {/* Floating top bar elements */}
      <motion.header
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        className="fixed top-0 left-0 right-0 z-50 px-4 py-3"
      >
        <div className="max-w-lg mx-auto flex items-center justify-between">
          {/* Logo Pill — glassmorphic */}
          <div className="glass-pill rounded-full px-3 py-1.5 flex items-center gap-2">
            <div className="w-6 h-6 flex items-center justify-center rounded-md overflow-hidden">
              <img src="/logo.png" alt="GraphRecall Logo" className="w-full h-full object-contain" />
            </div>
            <span className="font-heading font-semibold text-white text-sm hidden sm:block">
              GraphRecall
            </span>
          </div>

          {/* Center: WiFi + Daily Goal Pill */}
          <div className="flex items-center gap-2">
            {/* Backend Connection — glassmorphic circle */}
            <button
              onClick={() => setStatusPanelOpen(true)}
              className="glass-pill w-8 h-8 rounded-full flex items-center justify-center cursor-pointer hover:bg-white/15 transition-colors"
              aria-label="Backend status"
              title={backendStatus === 'connected' ? 'Backend connected' : backendStatus === 'disconnected' ? 'Backend disconnected' : 'Checking...'}
            >
              {backendStatus === 'connected' ? (
                <Wifi className="w-3.5 h-3.5 text-green-400" />
              ) : backendStatus === 'disconnected' ? (
                <WifiOff className="w-3.5 h-3.5 text-red-400" />
              ) : (
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                >
                  <Wifi className="w-3.5 h-3.5 text-yellow-400" />
                </motion.div>
              )}
            </button>

            {/* Feed Toggle Pill — glassmorphic */}
            <div className="relative">
              <button
                onClick={() => setFeedMenuOpen(!feedMenuOpen)}
                className="glass-pill rounded-full px-4 py-1.5 flex items-center gap-2 cursor-pointer hover:bg-white/12 transition-colors"
              >
                <div className="flex flex-col items-end mr-1">
                  <span className="text-[9px] text-white/40 uppercase font-bold tracking-wider leading-none mb-0.5">
                    {feedMode === 'daily' ? 'Daily Goal' : 'Card Feed'}
                  </span>
                  <div className="w-16 h-1 bg-white/10 rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${progressPercent}%` }}
                      className="h-full bg-gradient-to-r from-[#B6FF2E] to-[#2EFFE6] rounded-full"
                    />
                  </div>
                </div>
                <ChevronDown className={`w-3 h-3 text-white/40 transition-transform ${feedMenuOpen ? 'rotate-180' : ''}`} />
              </button>

              {/* Dropdown Menu — glassmorphic */}
              <AnimatePresence>
                {feedMenuOpen && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setFeedMenuOpen(false)} />
                    <motion.div
                      initial={{ opacity: 0, y: -5, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -5, scale: 0.95 }}
                      transition={{ duration: 0.15, ease: [0.22, 1, 0.36, 1] }}
                      className="absolute top-full mt-2 right-0 w-48 glass-pill rounded-xl overflow-hidden z-50 flex flex-col p-1"
                    >
                      <button
                        onClick={() => {
                          setFeedMode('daily');
                          setActiveTab('feed');
                          setFeedMenuOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2.5 text-xs font-medium rounded-lg flex items-center gap-3 transition-colors ${feedMode === 'daily' ? 'bg-white/10 text-white' : 'text-white/60 hover:bg-white/5'}`}
                      >
                        <Flame className="w-3.5 h-3.5 text-[#B6FF2E]" />
                        Today's Cards
                      </button>
                      <button
                        onClick={() => {
                          setFeedMode('history');
                          setActiveTab('feed');
                          setFeedMenuOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2.5 text-xs font-medium rounded-lg flex items-center gap-3 transition-colors ${feedMode === 'history' ? 'bg-white/10 text-white' : 'text-white/60 hover:bg-white/5'}`}
                      >
                        <Layers className="w-3.5 h-3.5 text-[#2EFFE6]" />
                        Card Feed
                      </button>
                      <button
                        onClick={() => {
                          setFeedMode('saved');
                          setActiveTab('feed');
                          setFeedMenuOpen(false);
                        }}
                        className={`w-full text-left px-3 py-2.5 text-xs font-medium rounded-lg flex items-center gap-3 transition-colors ${feedMode === 'saved' ? 'bg-white/10 text-white' : 'text-white/60 hover:bg-white/5'}`}
                      >
                        <Bookmark className="w-3.5 h-3.5 text-[#B6FF2E]" />
                        Saved Cards
                      </button>
                    </motion.div>
                  </>
                )}
              </AnimatePresence>
            </div>
          </div>

          {/* Streak — glassmorphic circle */}
          <div className="glass-pill rounded-full px-3 py-1.5 flex items-center gap-1.5">
            <Flame className="w-4 h-4 text-orange-400 flame-animate" />
            <span className="font-heading font-bold text-white text-sm">
              {userStats.streakDays}
            </span>
          </div>
        </div>

        {/* Backend Status Panel */}
        <BackendStatusPanel open={statusPanelOpen} onOpenChange={setStatusPanelOpen} />
      </motion.header>
    </>
  );
}
