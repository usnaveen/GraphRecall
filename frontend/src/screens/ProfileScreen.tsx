import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Settings, ChevronRight, BookOpen, FileText, Target,
  Flame, Download, Upload, Trash2, HelpCircle, Moon,
  Bell, Zap, Database, LogOut
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useAuthStore } from '../store/useAuthStore';
import { authService } from '../services/api';

export function ProfileScreen() {
  const [showSettings, setShowSettings] = useState(false);
  const { userStats } = useAppStore();
  const { user, logout } = useAuthStore();

  if (showSettings) {
    return <SettingsScreen onBack={() => setShowSettings(false)} onLogout={logout} />;
  }

  // Mock domain progress data (will be replaced with real API data)
  const mockDomainProgress = [
    { name: 'Machine Learning', progress: 68, color: '#B6FF2E' },
    { name: 'Deep Learning', progress: 45, color: '#2EFFE6' },
    { name: 'NLP', progress: 32, color: '#FF6B6B' },
    { name: 'Computer Vision', progress: 25, color: '#9B59B6' },
  ];

  // Simplified heatmap data generation
  const heatmapDots = Array.from({ length: 80 }).map(() => Math.floor(Math.random() * 5));


  return (
    <div className="h-[calc(100vh-180px)] overflow-y-auto pr-1 pb-10">
      {/* Profile Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-6 relative"
      >
        {/* Settings Button */}
        <button
          onClick={() => setShowSettings(true)}
          className="absolute top-0 right-0 p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <Settings className="w-5 h-5 text-white/60" />
        </button>

        {/* Avatar */}
        <div className="relative inline-block mb-3">
          <div className="w-24 h-24 rounded-full bg-gradient-to-br from-[#B6FF2E] to-[#2EFFE6] p-[2px]">
            {user?.picture ? (
              <img
                src={user.picture}
                alt={user.name}
                className="w-full h-full rounded-full object-cover"
              />
            ) : (
              <div className="w-full h-full rounded-full bg-[#07070A] flex items-center justify-center">
                <span className="font-heading text-3xl font-bold text-white">
                  {user?.name?.charAt(0) || 'U'}
                </span>
              </div>
            )}
          </div>
          <div className="absolute bottom-0 right-0 w-7 h-7 rounded-full bg-[#B6FF2E] flex items-center justify-center">
            <Flame className="w-4 h-4 text-[#07070A]" />
          </div>
        </div>

        <h2 className="font-heading text-xl font-bold text-white">{user?.name || 'User'}</h2>
        <p className="text-sm text-white/50">{user?.email || 'Learning since Jan 2026'}</p>
      </motion.div>

      {/* Weekly Stats */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-3 gap-3 mb-6"
      >
        <StatCard
          icon={BookOpen}
          value={userStats.conceptsLearned}
          label="Concepts"
          color="#B6FF2E"
        />
        <StatCard
          icon={FileText}
          value={userStats.notesAdded}
          label="Notes"
          color="#2EFFE6"
        />
        <StatCard
          icon={Target}
          value={`${Math.round(userStats.accuracy)}%`}
          label="Accuracy"
          color="#FF6B6B"
        />
      </motion.div>

      {/* Domain Progress - Keeping mock for now as backend enrichment is Phase 6 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mb-6"
      >
        <h3 className="font-heading font-semibold text-white mb-3 px-1">Learning Progress</h3>
        <div className="space-y-3">
          {mockDomainProgress.map((domain, i) => (
            <div key={domain.name} className="glass-surface rounded-xl p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-white/80">{domain.name}</span>
                <span className="text-sm font-mono" style={{ color: domain.color }}>
                  {domain.progress}%
                </span>
              </div>
              <div className="flex gap-1">
                {Array.from({ length: 10 }).map((_, j) => (
                  <motion.div
                    key={j}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ delay: i * 0.1 + j * 0.02, duration: 0.3 }}
                    className={`flex-1 h-2 rounded-full ${j < Math.ceil(domain.progress / 10)
                      ? ''
                      : 'bg-white/10'
                      }`}
                    style={
                      j < Math.ceil(domain.progress / 10)
                        ? { backgroundColor: domain.color }
                        : {}
                    }
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </motion.div>

      {/* Activity Heatmap */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="mb-6"
      >
        <h3 className="font-heading font-semibold text-white mb-3 px-1">Activity</h3>
        <div className="glass-surface rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs text-white/40">Recent History</span>
          </div>
          {/* Fix: Use flex-wrap instead of non-standard grid-cols-16 */}
          <div className="flex flex-wrap gap-1">
            {heatmapDots.map((level, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, scale: 0 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.005 }}
                className={`w-[calc(6.25%-4px)] aspect-square rounded-sm heatmap-${level}`}
              />
            ))}
          </div>
          <div className="flex items-center justify-end gap-2 mt-3">
            <span className="text-xs text-white/40">Less</span>
            {[0, 1, 2, 3, 4].map((level) => (
              <div key={level} className={`w-3 h-3 rounded-sm heatmap-${level}`} />
            ))}
            <span className="text-xs text-white/40">More</span>
          </div>
        </div>
      </motion.div>

      {/* Action Buttons */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="flex gap-3"
      >
        <button className="flex-1 py-3 rounded-xl bg-white/5 text-white/70 text-sm font-medium hover:bg-white/10 transition-colors flex items-center justify-center gap-2">
          <Target className="w-4 h-4" />
          View All Stats
        </button>
        <button className="flex-1 py-3 rounded-xl bg-white/5 text-white/70 text-sm font-medium hover:bg-white/10 transition-colors flex items-center justify-center gap-2">
          <Download className="w-4 h-4" />
          Export Data
        </button>
      </motion.div>
    </div>
  );
}

// Stat Card Component
function StatCard({
  icon: Icon,
  value,
  label,
  color
}: {
  icon: React.ElementType;
  value: string | number;
  label: string;
  color: string;
}) {
  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      className="glass-surface rounded-xl p-4 text-center"
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mx-auto mb-2"
        style={{ backgroundColor: `${color}20` }}
      >
        <Icon className="w-5 h-5" style={{ color }} />
      </div>
      <p className="font-heading text-2xl font-bold text-white mb-1">{value}</p>
      <p className="text-xs text-white/50">{label}</p>
    </motion.div>
  );
}

// Settings Screen
function SettingsScreen({ onBack, onLogout }: { onBack: () => void; onLogout: () => void }) {
  const [loading, setLoading] = useState(false);
  const { user } = useAuthStore();
  // Initialize from user object or defaults
  // Note: backend needs to return settings in user object for this to persist across reloads properly
  // For now we just mock the local state toggling
  const [settings, setSettings] = useState(user?.settings_json || {});

  const updateSetting = async (key: string, value: any) => {
    const newSettings = { ...settings, [key]: value };
    setSettings(newSettings);

    // Persist to backend
    try {
      await authService.updateProfile(newSettings);
    } catch (err) {
      console.error("Failed to save setting", err);
    }
  };

  return (
    <div className="h-[calc(100vh-180px)] overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ChevronRight className="w-5 h-5 text-white/60 rotate-180" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white">Settings</h2>
      </div>

      {/* Settings Groups */}
      <div className="space-y-6">
        {/* Daily Learning */}
        <SettingsGroup title="Daily Learning">
          <SettingItem
            icon={Target}
            label="Daily item limit"
            value={(settings.daily_limit || 20).toString()}
            onClick={() => {
              const limit = prompt("Enter daily item limit:", settings.daily_limit || 20);
              if (limit) updateSetting('daily_limit', parseInt(limit));
            }}
            action
          />
          <SettingItem
            icon={Bell}
            label="Notification time"
            value={settings.notification_time || "9:00 AM"}
            onClick={() => {
              const time = prompt("Enter notification time:", settings.notification_time || "9:00 AM");
              if (time) updateSetting('notification_time', time);
            }}
            action
          />
        </SettingsGroup>

        {/* Appearance */}
        <SettingsGroup title="Appearance">
          <SettingItem
            icon={Moon}
            label="Theme"
            value={settings.theme || "Dark"}
            onClick={() => updateSetting('theme', settings.theme === 'Light' ? 'Dark' : 'Light')}
            action
          />
          <SettingItem
            icon={Zap}
            label="Animations"
            value={settings.animations === false ? "Off" : "On"}
            toggle
            checked={settings.animations !== false}
            onToggle={() => updateSetting('animations', settings.animations === false)}
          />
        </SettingsGroup>

        {/* Data */}
        <SettingsGroup title="Data">
          <SettingItem
            icon={Trash2}
            label="Clear all data"
            danger
            action
            onClick={() => {
              if (confirm("Are you sure? This cannot be undone.")) {
                alert("Data cleared (simulated)");
              }
            }}
          />
        </SettingsGroup>

        {/* Account */}
        <SettingsGroup title="Account">
          <button
            onClick={onLogout}
            className="w-full flex items-center justify-between p-4 hover:bg-red-500/10 transition-colors"
          >
            <div className="flex items-center gap-3">
              <LogOut className="w-4 h-4 text-red-400" />
              <span className="text-sm text-red-400">Sign Out</span>
            </div>
            <ChevronRight className="w-4 h-4 text-red-400/50" />
          </button>
        </SettingsGroup>
      </div>
    </div>
  );
}

// Settings Group
function SettingsGroup({
  title,
  children
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="text-xs font-mono text-white/40 uppercase tracking-wider mb-3">
        {title}
      </h3>
      <div className="glass-surface rounded-xl overflow-hidden">
        {children}
      </div>
    </div>
  );
}

// Setting Item
function SettingItem({
  icon: Icon,
  label,
  value,
  action,
  toggle,
  checked,
  danger,
  onToggle,
  onClick
}: {
  icon: React.ElementType;
  label: string;
  value?: string;
  action?: boolean;
  toggle?: boolean;
  checked?: boolean;
  danger?: boolean;
  onToggle?: () => void;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={toggle ? onToggle : onClick}
      className={`
        w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors
        border-b border-white/5 last:border-b-0
      `}
    >
      <div className="flex items-center gap-3">
        <Icon className={`w-4 h-4 ${danger ? 'text-red-400' : 'text-white/50'}`} />
        <span className={`text-sm ${danger ? 'text-red-400' : 'text-white/80'}`}>
          {label}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {value && (
          <span className="text-sm text-white/50">{value}</span>
        )}
        {action && (
          <ChevronRight className="w-4 h-4 text-white/30" />
        )}
        {toggle && (
          <div className={`w-10 h-5 rounded-full relative transition-colors ${checked ? 'bg-[#B6FF2E]' : 'bg-white/10'}`}>
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${checked ? 'right-0.5' : 'left-0.5'}`} />
          </div>
        )}
      </div>
    </button>
  );
}
