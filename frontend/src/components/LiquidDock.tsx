import { motion } from 'framer-motion';
import { Home, Share2, Plus, MessageCircle, User } from 'lucide-react';
import type { TabType } from '../types';

interface LiquidDockProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
}

interface DockItem {
  id: TabType;
  icon: React.ElementType;
  label: string;
}

const dockItems: DockItem[] = [
  { id: 'feed', icon: Home, label: 'Feed' },
  { id: 'graph', icon: Share2, label: 'Graph' },
  { id: 'create', icon: Plus, label: 'Create' },
  { id: 'assistant', icon: MessageCircle, label: 'Assistant' },
  { id: 'profile', icon: User, label: 'Profile' },
];

export function LiquidDock({ activeTab, onTabChange }: LiquidDockProps) {
  return (
    <motion.nav
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="fixed bottom-0 left-0 right-0 z-50 flex justify-center pb-safe-area"
      style={{
        paddingBottom: 'clamp(1rem, env(safe-area-inset-bottom), 3rem)',
        marginBottom: '0.5rem'
      }}
    >
      <div className="liquid-glass-dock rounded-full px-3 py-2 flex items-center gap-1 mx-4 w-fit max-w-[90vw] justify-center">
        {dockItems.map((item, index) => {
          const isActive = activeTab === item.id;
          const isCenter = index === 2; // Create button
          const Icon = item.icon;

          return (
            <motion.button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className={`
                relative flex items-center justify-center rounded-full transition-all duration-300
                ${isCenter
                  ? 'w-12 h-12 -mt-4 bg-gradient-to-br from-[#B6FF2E] to-[#2EFFE6]'
                  : 'w-11 h-11'
                }
                ${isActive && !isCenter
                  ? 'bg-[#B6FF2E]/20 neon-glow'
                  : 'hover:bg-white/5'
                }
              `}
            >
              {/* Active indicator glow */}
              {isActive && !isCenter && (
                <motion.div
                  layoutId="activeGlow"
                  className="absolute inset-0 rounded-full bg-[#B6FF2E]/20 neon-glow"
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}

              {/* Icon */}
              <Icon
                className={`
                  w-5 h-5 transition-colors duration-300 relative z-10
                  ${isCenter
                    ? 'text-[#07070A]'
                    : isActive
                      ? 'text-[#B6FF2E]'
                      : 'text-white/60'
                  }
                `}
                strokeWidth={isActive || isCenter ? 2.5 : 2}
              />

              {/* Label tooltip */}
              <span className="absolute -top-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-black/80 rounded-md text-[10px] text-white/80 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
                {item.label}
              </span>
            </motion.button>
          );
        })}
      </div>
    </motion.nav>
  );
}
