import { motion } from 'framer-motion';
import { Flame } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function TopBar() {
  const { itemsReviewedToday, dailyItemLimit, userStats } = useAppStore();
  const progressPercent = (itemsReviewedToday / dailyItemLimit) * 100;

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
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#B6FF2E] to-[#2EFFE6] flex items-center justify-center">
            <span className="text-sm font-bold text-[#07070A]">G</span>
          </div>
          <span className="font-heading font-semibold text-white text-sm hidden sm:block">
            GraphRecall
          </span>
        </div>

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

        {/* Streak */}
        <div className="flex items-center gap-1.5">
          <Flame className="w-5 h-5 text-orange-400 flame-animate" />
          <span className="font-heading font-bold text-white text-sm">
            {userStats.streakDays}
          </span>
        </div>
      </div>
    </motion.header>
  );
}
