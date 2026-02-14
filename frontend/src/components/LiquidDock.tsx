import { motion } from 'framer-motion';
import { Home, Share2, Plus, MessageCircle, User, BookOpen } from 'lucide-react';
import type { TabType } from '../types';

interface LiquidDockProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  orientation?: 'horizontal' | 'vertical';
  className?: string;
}

interface DockItem {
  id: TabType;
  icon: any;
  label: string;
}

const dockItems: DockItem[] = [
  { id: 'feed', icon: Home, label: 'Feed' },
  { id: 'graph', icon: Share2, label: 'Graph' },
  { id: 'create', icon: Plus, label: 'Create' },
  { id: 'library', icon: BookOpen, label: 'Library' },
  { id: 'assistant', icon: MessageCircle, label: 'Assistant' },
  { id: 'profile', icon: User, label: 'Profile' },
];

export function LiquidDock({
  activeTab,
  onTabChange,
  orientation = 'horizontal',
  className = '',
}: LiquidDockProps) {
  const isVertical = orientation === 'vertical';
  const tooltipClass = isVertical
    ? 'absolute left-full top-1/2 -translate-y-1/2 ml-2 px-2 py-1 bg-black/80 rounded-md text-[10px] text-white/80 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none'
    : 'absolute -top-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-black/80 rounded-md text-[10px] text-white/80 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none';

  if (isVertical) {
    return (
      <motion.nav
        initial={{ opacity: 0, x: 50 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.5, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        className={`fixed right-4 top-1/2 -translate-y-1/2 z-50 flex justify-center ${className}`}
      >
        <div className="liquid-glass-dock rounded-3xl px-2 py-3 flex flex-col items-center gap-2 mx-2">
          {dockItems.map((item, index) => renderDockItem(item, index, activeTab, onTabChange, tooltipClass, isVertical))}
        </div>
      </motion.nav>
    );
  }

  return (
    <>
      {/* Floating glassmorphic dock — no background, just the pill */}
      <motion.nav
        initial={{ opacity: 0, y: 50 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        className={`fixed bottom-0 left-0 right-0 z-50 flex justify-center pointer-events-none ${className}`}
        style={{
          paddingBottom: 'clamp(0.75rem, env(safe-area-inset-bottom), 2.5rem)',
          marginBottom: '0.5rem',
        }}
      >
        <div className="liquid-glass-dock rounded-full px-4 py-2 flex items-center gap-4 w-fit max-w-[90vw] justify-center pointer-events-auto">
          {dockItems.map((item, index) => renderDockItem(item, index, activeTab, onTabChange, tooltipClass, isVertical))}
        </div>
      </motion.nav>
    </>
  );
}

function renderDockItem(
  item: DockItem,
  index: number,
  activeTab: TabType,
  onTabChange: (tab: TabType) => void,
  tooltipClass: string,
  isVertical: boolean,
) {
  const isActive = activeTab === item.id;
  const isCenter = index === 2;
  const Icon = item.icon;

  if (isCenter) {
    return (
      <div key={item.id} className="relative w-12 h-12 flex items-center justify-center">
        <motion.button
          onClick={() => onTabChange(item.id)}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          className={`group w-12 h-12 flex items-center justify-center rounded-full bg-gradient-to-br from-[#B6FF2E] to-[#2EFFE6] transition-all duration-300 ${!isVertical && 'shadow-[0_0_20px_rgba(182,255,46,0.3)]'}`}
        >
          <Icon
            className="w-5 h-5 text-[#07070A] relative z-10"
            strokeWidth={2.5}
          />
          <span className={tooltipClass}>
            {item.label}
          </span>
        </motion.button>
      </div>
    );
  }

  return (
    <motion.button
      key={item.id}
      onClick={() => onTabChange(item.id)}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.95 }}
      className={`
        group relative flex items-center justify-center rounded-full transition-all duration-300
        w-11 h-11
        ${isActive
          ? 'bg-[#B6FF2E]/20 neon-glow'
          : 'hover:bg-white/5'
        }
      `}
    >
      {isActive && (
        <motion.div
          layoutId="activeGlow"
          className="absolute inset-0 rounded-full bg-[#B6FF2E]/20 neon-glow"
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        />
      )}
      <Icon
        className={`
          w-5 h-5 transition-colors duration-300 relative z-10
          ${isActive ? 'text-[#B6FF2E]' : 'text-white/60'}
        `}
        strokeWidth={isActive ? 2.5 : 2}
      />
      <span className={tooltipClass}>
        {item.label}
      </span>
    </motion.button>
  );
}
