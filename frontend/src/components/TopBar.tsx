import { motion } from 'framer-motion';
import { Flame, Wifi, WifiOff } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useEffect, useState } from 'react';
import { BackendStatusPanel } from './BackendStatusPanel';

export function TopBar() {
  const { itemsReviewedToday, dailyItemLimit, userStats } = useAppStore();
  const [backendStatus, setBackendStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking');
  const [statusPanelOpen, setStatusPanelOpen] = useState(false);
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
      } catch (error) {
        setBackendStatus('disconnected');
      }
    };

    checkBackend();
    // Re-check every 30 seconds
    const interval = setInterval(checkBackend, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.header
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="fixed top-0 left-0 right-0 z-50 px-4 py-3"
    >
      <div className="max-w-lg mx-auto flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 flex items-center justify-center rounded-lg overflow-hidden">
            <img src="/logo.png" alt="GraphRecall Logo" className="w-full h-full object-contain" />
          </div>
          <span className="font-heading font-semibold text-white text-sm hidden sm:block">
            GraphRecall
          </span>
        </div>

        {/* Progress Pill & Backend Status */}
        <div className="flex items-center gap-2">
          {/* Backend Connection Indicator — click to open status panel */}
          <button
            onClick={() => setStatusPanelOpen(true)}
            className="flex items-center gap-1.5 px-2 py-1 rounded-full glass-surface-highlight cursor-pointer hover:bg-white/15 transition-colors"
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

          {/* Progress Pill */}
          <div className="glass-surface-highlight rounded-full px-4 py-1.5 flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-20 h-1.5 bg-white/10 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${progressPercent}%` }}
                  transition={{ duration: 0.8, delay: 0.3 }}
                  className="h-full bg-gradient-to-r from-[#B6FF2E] to-[#2EFFE6] rounded-full"
                />
              </div>
            </div>
            <span className="text-xs font-mono text-white/80">
              {itemsReviewedToday}/{dailyItemLimit}
            </span>
          </div>
        </div>

        {/* Streak */}
        <div className="flex items-center gap-1.5">
          <Flame className="w-5 h-5 text-orange-400 flame-animate" />
          <span className="font-heading font-bold text-white text-sm">
            {userStats.streakDays}
          </span>
        </div>
      </div>

      {/* Backend Status Panel */}
      <BackendStatusPanel open={statusPanelOpen} onOpenChange={setStatusPanelOpen} />
    </motion.header>
  );
}
