import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Settings, ChevronRight, BookOpen, FileText, Target,
  Flame, Download, Moon, ArrowLeft, Clock, Brain, Hash,
  Bell, Zap, LogOut, Search, X, Trash2
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useAuthStore } from '../store/useAuthStore';
import { authService } from '../services/api';

type ProfileView = 'main' | 'settings' | 'notes' | 'concepts';

export function ProfileScreen() {
  const [currentView, setCurrentView] = useState<ProfileView>('main');
  const { userStats, fetchStats, notesList, conceptsList, fetchNotes, fetchConcepts } = useAppStore();
  const { user, logout } = useAuthStore();

  useEffect(() => {
    fetchStats();
  }, []);

  if (currentView === 'settings') {
    return <SettingsScreen onBack={() => setCurrentView('main')} onLogout={logout} />;
  }

  if (currentView === 'notes') {
    return <NotesListView notes={notesList} onBack={() => setCurrentView('main')} onFetch={fetchNotes} />;
  }

  if (currentView === 'concepts') {
    return <ConceptsListView concepts={conceptsList} onBack={() => setCurrentView('main')} onFetch={fetchConcepts} />;
  }

  // Domain Progress from real data
  const domainColors: Record<string, string> = {
    "Machine Learning": "#7C3AED",
    "Mathematics": "#3B82F6",
    "Computer Science": "#10B981",
    "Database Systems": "#F59E0B",
    "System Design": "#EF4444",
    "Programming": "#06B6D4",
    "General": "#6B7280",
  };

  const domainProgress = userStats.domainProgress
    ? Object.entries(userStats.domainProgress).map(([name, progress]) => ({
      name,
      progress: Math.round(progress), // Ensure integer
      color: domainColors[name] || '#6B7280' // Default gray
    })).sort((a, b) => b.progress - a.progress)
    : [];

  // Heatmap generation from real activity
  const generateHeatmap = () => {
    // Actually, UI shows flex wrap. Let's generic last 90 days.
    const today = new Date();
    const dots = [];

    // Create map of date string -> activity level
    const activityMap = new Map();
    if (userStats.dailyActivity) {
      userStats.dailyActivity.forEach(day => {
        const count = day.reviews_completed;
        let level = 0;
        if (count > 0) level = 1;
        if (count > 5) level = 2;
        if (count > 15) level = 3;
        if (count > 30) level = 4;
        activityMap.set(day.date.split('T')[0], level); // Handle potential ISO timestamp
      });
    }

    // Generate last 80 days to match UI grid
    for (let i = 79; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const dateStr = d.toISOString().split('T')[0];
      dots.push({
        date: dateStr,
        level: activityMap.get(dateStr) || 0
      });
    }
    return dots;
  };

  const heatmapDots = generateHeatmap();


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
          onClick={() => setCurrentView('settings')}
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
        className="grid grid-cols-2 gap-3 mb-6"
      >
        <StatCard
          icon={BookOpen}
          value={userStats.conceptsLearned}
          label="Concepts"
          color="#B6FF2E"
          onClick={() => { fetchConcepts(); setCurrentView('concepts'); }}
        />
        <StatCard
          icon={FileText}
          value={userStats.notesAdded}
          label="Notes"
          color="#2EFFE6"
          onClick={() => { fetchNotes(); setCurrentView('notes'); }}
        />
      </motion.div>

      {/* Cost & Usage Stats (Estimated) */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="grid grid-cols-2 gap-3 mb-6"
      >
        <StatCard
          icon={Zap}
          value={`${((userStats.conceptsLearned * 1500 + userStats.notesAdded * 500) / 1000).toFixed(1)}k`}
          label="Est. Tokens"
          color="#FF6B6B"
        />
        <StatCard
          icon={Target} // Dollar Sign would be better but Lucide Target is imported
          value={`$${((userStats.conceptsLearned * 1500 + userStats.notesAdded * 500) / 1000000 * 0.50).toFixed(4)}`}
          label="Est. Cost"
          color="#F59E0B"
        />
      </motion.div>

      {/* Domain Progress */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mb-6"
      >
        <h3 className="font-heading font-semibold text-white mb-3 px-1">Learning Progress</h3>

        {domainProgress.length > 0 ? (
          <div className="space-y-3">
            {domainProgress.map((domain, i) => (
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
        ) : (
          <div className="glass-surface rounded-xl p-6 text-center">
            <p className="text-white/40 text-sm">No progress data yet. Start adding notes!</p>
          </div>
        )}
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
            <span className="text-xs text-white/40">Last 80 Days</span>
          </div>
          {/* Fix: Use flex-wrap instead of non-standard grid-cols-16 */}
          <div className="flex flex-wrap gap-1">
            {heatmapDots.map((dot, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, scale: 0 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.005 }}
                title={`${dot.date}: Level ${dot.level}`}
                className={`w-[calc(6.25%-4px)] aspect-square rounded-sm heatmap-${dot.level}`}
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
          View Detailed Stats
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
  color,
  onClick
}: {
  icon: React.ElementType;
  value: string | number;
  label: string;
  color: string;
  onClick?: () => void;
}) {
  return (
    <motion.div
      whileHover={{ scale: 1.02 }}
      whileTap={onClick ? { scale: 0.97 } : undefined}
      onClick={onClick}
      className={`glass-surface rounded-xl p-4 text-center ${onClick ? 'cursor-pointer active:bg-white/10' : ''}`}
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center mx-auto mb-2"
        style={{ backgroundColor: `${color}20` }}
      >
        <Icon className="w-5 h-5" style={{ color }} />
      </div>
      <p className="font-heading text-2xl font-bold text-white mb-1">{value}</p>
      <div className="flex items-center justify-center gap-1">
        <p className="text-xs text-white/50">{label}</p>
        {onClick && <ChevronRight className="w-3 h-3 text-white/30" />}
      </div>
    </motion.div>
  );
}

// Note Item Component for Swipe-to-Delete
function NoteItem({ note, onDelete }: { note: any; onDelete: (id: string) => void }) {
  const [showConfirm, setShowConfirm] = useState(false);

  return (
    <div className="relative group">
      {/* Background Action Layer */}
      <div className="absolute inset-0 bg-red-500/20 rounded-xl flex items-center justify-end px-4 mb-2">
        <Trash2 className="w-5 h-5 text-red-500" />
      </div>

      <motion.div
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0, x: 0 }}
        drag="x"
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={{ left: 0.5, right: 0.1 }}
        onDragEnd={(_, info) => {
          if (info.offset.x < -100) {
            // Swipe left threshold met
            if (confirm("Delete this note?")) {
              onDelete(note.id);
            }
          }
        }}
        whileHover={{ scale: 1.01 }}
        whileTap={{ scale: 0.99 }}
        className="glass-surface rounded-xl p-4 hover:bg-white/5 transition-colors relative z-10 bg-[#07070A]" // Added bg to cover trash icon
      >
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#2EFFE6]/10 flex items-center justify-center flex-shrink-0 mt-0.5">
            <FileText className="w-4 h-4 text-[#2EFFE6]" />
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="text-sm font-medium text-white truncate">
              {note.title || 'Untitled Note'}
            </h4>
            <p className="text-xs text-white/40 mt-1 line-clamp-2">
              {note.content_text?.slice(0, 120) || 'No content'}
            </p>
            <div className="flex items-center gap-3 mt-2">
              <span className="text-[10px] text-white/30 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {new Date(note.created_at).toLocaleDateString()}
              </span>
              {note.source_type && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/40">
                  {note.source_type}
                </span>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

// Notes List View
function NotesListView({
  notes,
  onBack,
  onFetch,
}: {
  notes: { id: string; title: string; content_text: string; source_type: string; created_at: string }[];
  onBack: () => void;
  onFetch: () => Promise<void>;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const { deleteNote } = useAppStore();

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setIsLoading(true);
      await onFetch();
      if (mounted) setIsLoading(false);
    };
    load();
    return () => { mounted = false; };
  }, []);

  const filtered = notes.filter(
    (n) =>
      n.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.content_text?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="h-[calc(100vh-180px)] overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-white/60" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white">My Notes</h2>
        <span className="ml-auto text-sm text-white/40">{notes.length} total</span>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search notes..."
          className="w-full pl-10 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#2EFFE6]/50"
        />
        {searchQuery && (
          <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="w-4 h-4 text-white/40" />
          </button>
        )}
      </div>

      {/* Notes List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-[#2EFFE6] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12">
          <FileText className="w-10 h-10 text-white/20 mx-auto mb-3" />
          <p className="text-white/40 text-sm">
            {searchQuery ? 'No notes matching your search' : 'No notes yet. Start adding some!'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-white/30 text-center mb-2">Swipe left to delete</p>
          {filtered.map((note) => (
            <NoteItem key={note.id} note={note} onDelete={deleteNote} />
          ))}
        </div>
      )}
    </div>
  );
}

// Concept Item Component for Swipe-to-Delete
function ConceptItem({ concept, color, onTap, onDelete }: { concept: any; color: string; onTap: (name: string) => void; onDelete: (id: string) => void }) {
  return (
    <div className="relative group">
      <div className="absolute inset-0 bg-red-500/20 rounded-xl flex items-center justify-end px-4 mb-2">
        <Trash2 className="w-5 h-5 text-red-500" />
      </div>

      <motion.div
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0, x: 0 }}
        drag="x"
        dragConstraints={{ left: 0, right: 0 }}
        dragElastic={{ left: 0.5, right: 0.1 }}
        onDragEnd={(_, info) => {
          if (info.offset.x < -100) {
            if (confirm("Delete this concept?")) {
              onDelete(concept.id);
            }
          }
        }}
        onClick={() => onTap(concept.name)}
        whileHover={{ scale: 1.01 }}
        whileTap={{ scale: 0.99 }}
        className="glass-surface rounded-xl p-4 hover:bg-white/5 transition-colors cursor-pointer relative z-10 bg-[#07070A]"
      >
        <div className="flex items-start gap-3">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
            style={{ backgroundColor: `${color}20` }}
          >
            <Brain className="w-4 h-4" style={{ color }} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-medium text-white truncate">{concept.name}</h4>
              <ChevronRight className="w-3 h-3 text-white/20 flex-shrink-0" />
            </div>
            <p className="text-xs text-white/40 mt-1 line-clamp-2">
              {concept.definition || 'No definition'}
            </p>
            <div className="flex items-center gap-3 mt-2">
              <span
                className="text-[10px] px-2 py-0.5 rounded-full"
                style={{ backgroundColor: `${color}15`, color }}
              >
                {concept.domain}
              </span>
              <span className="text-[10px] text-white/30 flex items-center gap-1">
                <Hash className="w-3 h-3" />
                Complexity: {concept.complexity_score}/10
              </span>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

// Concepts List View
function ConceptsListView({
  concepts,
  onBack,
  onFetch,
}: {
  concepts: { id: string; name: string; definition: string; domain: string; complexity_score: number }[];
  onBack: () => void;
  onFetch: () => Promise<void>;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { navigateToFeedWithTopic, deleteConcept } = useAppStore();

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setIsLoading(true);
      await onFetch();
      if (mounted) setIsLoading(false);
    };
    load();
    return () => { mounted = false; };
  }, []);

  const domains = [...new Set(concepts.map((c) => c.domain).filter(Boolean))].sort();

  const filtered = concepts.filter((c) => {
    const matchesSearch =
      c.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.definition?.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesDomain = !selectedDomain || c.domain === selectedDomain;
    return matchesSearch && matchesDomain;
  });

  const domainColors: Record<string, string> = {
    "Machine Learning": "#7C3AED",
    "Mathematics": "#3B82F6",
    "Computer Science": "#10B981",
    "Database Systems": "#F59E0B",
    "System Design": "#EF4444",
    "Programming": "#06B6D4",
    "General": "#6B7280",
  };

  return (
    <div className="h-[calc(100vh-180px)] overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-white/60" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white">My Concepts</h2>
        <span className="ml-auto text-sm text-white/40">{concepts.length} total</span>
      </div>

      {/* Search */}
      <div className="relative mb-3">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search concepts..."
          className="w-full pl-10 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50"
        />
        {searchQuery && (
          <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="w-4 h-4 text-white/40" />
          </button>
        )}
      </div>

      {/* Domain Filter Chips */}
      {domains.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-3 mb-3 scrollbar-hide">
          <button
            onClick={() => setSelectedDomain(null)}
            className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors ${!selectedDomain ? 'bg-[#B6FF2E] text-black font-medium' : 'bg-white/5 text-white/60 hover:bg-white/10'
              }`}
          >
            All
          </button>
          {domains.map((domain) => (
            <button
              key={domain}
              onClick={() => setSelectedDomain(selectedDomain === domain ? null : domain)}
              className={`px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors ${selectedDomain === domain
                  ? 'bg-[#B6FF2E] text-black font-medium'
                  : 'bg-white/5 text-white/60 hover:bg-white/10'
                }`}
            >
              {domain}
            </button>
          ))}
        </div>
      )}

      {/* Concepts List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-[#B6FF2E] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12">
          <Brain className="w-10 h-10 text-white/20 mx-auto mb-3" />
          <p className="text-white/40 text-sm">
            {searchQuery || selectedDomain ? 'No concepts matching your filter' : 'No concepts yet. Ingest some notes!'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-white/30 text-center mb-2">Swipe left to delete</p>
          {filtered.map((concept) => {
            const color = domainColors[concept.domain] || '#6B7280';
            return (
              <ConceptItem
                key={concept.id}
                concept={concept}
                color={color}
                onTap={navigateToFeedWithTopic}
                onDelete={deleteConcept}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// Settings Screen
function SettingsScreen({ onBack, onLogout }: { onBack: () => void; onLogout: () => void }) {
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

        {/* About App (Placeholder) */}
        <SettingsGroup title="General">
          <SettingItem
            icon={BookOpen}
            label="About App"
            onClick={() => alert("GraphRecall v2.1\n\nThe intelligent active recall system powered by Knowledge Graphs and LLMs.\n\n© 2026 GraphRecall Team")}
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
