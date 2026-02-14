import { useState, useEffect } from 'react';
import { motion, useMotionValue, useTransform } from 'framer-motion';
import {
  Settings, ChevronRight, ChevronDown, BookOpen, FileText, Target,
  Flame, Download, Moon, ArrowLeft, Clock, Brain, Hash,
  Bell, Zap, LogOut, Search, X, Trash2, Image, HelpCircle
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useAuthStore } from '../store/useAuthStore';
import { authService, feedService } from '../services/api';

type ProfileView = 'main' | 'settings' | 'notes' | 'concepts' | 'uploads' | 'quizzes' | 'books';

import { AgentDeck } from '../components/geekout/AgentDeck';

export function ProfileScreen() {
  const [currentView, setCurrentView] = useState<ProfileView>('main');
  const [showGeekyFacts, setShowGeekyFacts] = useState(false);
  const [quizCount, setQuizCount] = useState(0);
  const {
    userStats, fetchStats,
    notesList, conceptsList, uploadsList, libraryBooks,
    fetchNotes, fetchConcepts, fetchUploads, fetchLibrary,
    activeRecallSchedule, fetchSchedule
  } = useAppStore();
  const { user, logout } = useAuthStore();

  useEffect(() => {
    fetchStats();
    fetchUploads();
    fetchLibrary();
    fetchSchedule();
    feedService.getQuizHistory().then(data => {
      if (data && data.quizzes) setQuizCount(data.quizzes.length);
    }).catch(err => console.error("Failed to load quiz history count", err));
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
  if (currentView === 'uploads') {
    const safeUploads = uploadsList.map(u => ({
      ...u,
      title: u.title || undefined,
      description: u.description || undefined,
      thumbnail_url: u.thumbnail_url || undefined,
      // Ensure file_url is string, though it should be from interface
    }));
    return <UploadsListView uploads={safeUploads} onBack={() => setCurrentView('main')} onFetch={fetchUploads} />;
  }

  if (currentView === 'quizzes') {
    return <QuizHistoryView onBack={() => setCurrentView('main')} />;
  }

  if (currentView === 'books') {
    return <BooksListView onBack={() => setCurrentView('main')} />;
  }



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
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1 pb-10 scrollbar-hide">
      {/* Geeky Facts Modal */}
      {showGeekyFacts && <AgentDeck onClose={() => setShowGeekyFacts(false)} />}

      {/* Profile Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center mb-6 relative"
      >
        {/* Geeky Facts Button */}
        <button
          onClick={() => setShowGeekyFacts(true)}
          className="absolute top-0 left-0 p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
          title="Geeky Facts"
        >
          <Brain className="w-5 h-5 text-[#B6FF2E]/80" />
        </button>

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

      {/* Stats Grid */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="grid grid-cols-2 gap-3 mb-6"
      >
        <StatsCard
          icon={Target}
          count={quizCount}
          label="Quizzes"
          onClick={() => setCurrentView('quizzes')}
          color="#9B59B6"
        />
        <StatsCard
          icon={BookOpen}
          count={userStats.notesAdded}
          label="Notes"
          onClick={() => setCurrentView('notes')}
          color="#B6FF2E"
        />
        <StatsCard
          icon={Brain}
          count={userStats.conceptsLearned}
          label="Concepts"
          onClick={() => setCurrentView('concepts')}
          color="#2EFFE6"
        />
        <StatsCard
          icon={Image}
          count={uploadsList.length}
          label="Resources"
          onClick={() => setCurrentView('uploads')}
          color="#FF6B6B"
        />
        <StatsCard
          icon={BookOpen}
          count={libraryBooks.length}
          label="Books"
          onClick={() => setCurrentView('books')}
          color="#F59E0B"
          className="col-span-2"
        />
      </motion.div>

      {/* Calendar Schedule */}
      <CalendarSchedule activeRecallSchedule={activeRecallSchedule} />

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

      {/* Help / Build Info */}
      <div className="text-center pb-6">
        <p className="text-xs text-white/20 font-mono">GraphRecall v0.2.1 • Built with Love</p>
      </div>
    </div >
  );
}

// Calendar Schedule Component with topic expansion
function CalendarSchedule({ activeRecallSchedule }: { activeRecallSchedule: { date: string; count: number; topics?: string[] }[] }) {
  const [expandedDate, setExpandedDate] = useState<string | null>(null);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="mb-6"
    >
      <div className="flex items-center justify-between px-1 mb-3">
        <h3 className="font-heading font-semibold text-white">Recall Schedule</h3>
        <span className="text-xs text-white/40">Next 14 Days</span>
      </div>

      <div className="glass-surface rounded-xl p-4 overflow-x-auto scrollbar-hide">
        <div className="flex gap-2 min-w-max">
          {Array.from({ length: 14 }).map((_, i) => {
            const d = new Date();
            d.setDate(d.getDate() + i);
            const dateStr = d.toISOString().split('T')[0];
            const dayName = d.toLocaleDateString('en-US', { weekday: 'short' });
            const dayNum = d.getDate();

            const scheduled = (activeRecallSchedule || []).find(s => s.date === dateStr);
            const count = scheduled ? scheduled.count : 0;
            const isToday = i === 0;
            const isExpanded = expandedDate === dateStr;

            return (
              <div
                key={i}
                onClick={() => {
                  if (count > 0) setExpandedDate(isExpanded ? null : dateStr);
                }}
                className={`
                  flex flex-col items-center justify-between w-14 h-20 rounded-lg p-2 border transition-all
                  ${isToday ? 'bg-white/10 border-white/20' : 'bg-black/20 border-white/5'}
                  ${count > 0 ? 'hover:border-[#B6FF2E]/50 cursor-pointer' : 'opacity-60'}
                  ${isExpanded ? 'border-[#B6FF2E]/60 bg-[#B6FF2E]/5' : ''}
                `}
              >
                <span className="text-[10px] text-white/40 uppercase">{dayName}</span>
                <span className={`text-sm font-bold ${isToday ? 'text-white' : 'text-white/70'}`}>{dayNum}</span>

                {count > 0 ? (
                  <div className="mt-1 px-1.5 py-0.5 rounded-full bg-[#B6FF2E]/20 border border-[#B6FF2E]/30">
                    <span className="text-[9px] font-bold text-[#B6FF2E]">{count}</span>
                  </div>
                ) : (
                  <div className="w-1 h-1 rounded-full bg-white/10 mt-2" />
                )}
              </div>
            );
          })}
        </div>

        {/* Topic chips for expanded date */}
        {expandedDate && (() => {
          const scheduled = (activeRecallSchedule || []).find(s => s.date === expandedDate);
          const topics = scheduled?.topics || [];
          if (topics.length === 0) return null;

          const dateLabel = new Date(expandedDate + 'T00:00:00').toLocaleDateString('en-US', {
            weekday: 'long', month: 'short', day: 'numeric'
          });

          return (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-3 pt-3 border-t border-white/10"
            >
              <p className="text-[10px] text-white/40 mb-2">{dateLabel} — {scheduled?.count} topics</p>
              <div className="flex flex-wrap gap-1.5">
                {topics.map((topic, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-0.5 rounded-full text-[10px] bg-[#B6FF2E]/10 text-[#B6FF2E] border border-[#B6FF2E]/20"
                  >
                    {topic}
                  </span>
                ))}
                {(scheduled?.count || 0) > topics.length && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/5 text-white/40">
                    +{(scheduled?.count || 0) - topics.length} more
                  </span>
                )}
              </div>
            </motion.div>
          );
        })()}
      </div>
    </motion.div>
  );
}

// Note Item Component for Swipe-to-Delete
function NoteItem({ note, onDelete, onOpen }: { note: any; onDelete: (id: string) => void; onOpen: (note: any) => void }) {
  const x = useMotionValue(0);
  const backgroundOpacity = useTransform(x, [-120, -60, 0], [1, 0.6, 0]);

  return (
    <div className="relative group overflow-hidden rounded-xl">
      <motion.div
        className="absolute inset-0 bg-red-500/20 rounded-xl flex items-center justify-end px-4"
        initial={{ opacity: 0 }}
        style={{ opacity: backgroundOpacity }}
      >
        <Trash2 className="w-5 h-5 text-red-500" />
      </motion.div>

      <motion.div
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0, x: 0 }}
        drag="x"
        dragConstraints={{ left: -140, right: 0 }}
        dragElastic={{ left: 0.3, right: 0.1 }}
        style={{ x }}
        onDragEnd={(_, info) => {
          if (info.offset.x < -100) {
            if (confirm("Delete this note?")) {
              onDelete(note.id);
            }
          }
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          if (confirm("Delete this note?")) {
            onDelete(note.id);
          }
        }}
        whileHover={{ scale: 1.01 }}
        whileTap={{ scale: 0.99 }}
        onClick={() => onOpen(note)}
        className="glass-surface rounded-xl p-4 hover:bg-white/5 transition-colors relative z-10 bg-[#07070A] cursor-pointer"
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
              {note.resource_type && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/40">
                  {note.resource_type}
                </span>
              )}
            </div>
          </div>

          {/* Desktop Delete Button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Delete this note?")) onDelete(note.id);
            }}
            className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 rounded-full transition-all absolute top-2 right-2"
            title="Delete Note"
          >
            <Trash2 className="w-4 h-4 text-red-400" />
          </button>
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
  notes: { id: string; title: string; content_text: string; resource_type: string; created_at: string; file_url?: string }[];
  onBack: () => void;
  onFetch: () => Promise<void>;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [selectedNote, setSelectedNote] = useState<any>(null);
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
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1">
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
          <p className="text-xs text-white/30 text-center mb-2">Tap to open &middot; Swipe left to delete</p>
          {filtered.map((note) => (
            <NoteItem key={note.id} note={note} onDelete={deleteNote} onOpen={setSelectedNote} />
          ))}
        </div>
      )}

      {/* Note Detail Modal */}
      {selectedNote && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={() => setSelectedNote(null)}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            className="bg-[#1a1a1f] border border-white/10 rounded-2xl w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between p-4 border-b border-white/10 shrink-0">
              <div className="flex-1 min-w-0 mr-3">
                <h3 className="text-lg font-semibold text-white truncate">
                  {selectedNote.title || 'Untitled Note'}
                </h3>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-white/40">
                    {new Date(selectedNote.created_at).toLocaleDateString()}
                  </span>
                  {selectedNote.resource_type && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/40">
                      {selectedNote.resource_type}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {selectedNote.file_url && (
                  <a
                    href={selectedNote.file_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 rounded-lg bg-[#2EFFE6]/10 text-[#2EFFE6] text-xs font-medium hover:bg-[#2EFFE6]/20 transition-colors"
                  >
                    Open Original
                  </a>
                )}
                <button
                  onClick={() => setSelectedNote(null)}
                  className="p-2 rounded-full hover:bg-white/10 transition-colors"
                >
                  <X className="w-5 h-5 text-white/60" />
                </button>
              </div>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto p-4">
              <div className="text-sm text-white/80 leading-relaxed whitespace-pre-wrap">
                {selectedNote.content_text || 'No content available'}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}

// Upload Item Component for Swipe-to-Delete
function UploadItem({ upload, onDelete }: { upload: any; onDelete: (id: string) => void }) {
  const displayTitle = upload.title || (upload.file_url ? upload.file_url.split('/').pop()?.split('?')[0] : 'Untitled Upload');
  const x = useMotionValue(0);
  const backgroundOpacity = useTransform(x, [-120, -60, 0], [1, 0.6, 0]);
  return (
    <div className="relative group overflow-hidden rounded-xl">
      <motion.div
        className="absolute inset-0 bg-red-500/20 rounded-xl flex items-center justify-end px-4"
        initial={{ opacity: 0 }}
        style={{ opacity: backgroundOpacity }}
      >
        <Trash2 className="w-5 h-5 text-red-500" />
      </motion.div>

      <motion.div
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0, x: 0 }}
        drag="x"
        dragConstraints={{ left: -140, right: 0 }}
        dragElastic={{ left: 0.3, right: 0.1 }}
        style={{ x }}
        onDragEnd={(_, info) => {
          if (info.offset.x < -100) {
            if (confirm("Delete this upload?")) {
              onDelete(upload.id);
            }
          }
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          if (confirm("Delete this upload?")) {
            onDelete(upload.id);
          }
        }}
        className="glass-surface rounded-xl p-4 hover:bg-white/5 transition-colors cursor-pointer relative z-10 bg-[#07070A]"
      >
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#FF6B6B]/10 flex items-center justify-center flex-shrink-0 mt-0.5">
            <Image className="w-4 h-4 text-[#FF6B6B]" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-medium text-white truncate">{displayTitle}</h4>
              <ChevronRight className="w-3 h-3 text-white/20 flex-shrink-0" />
            </div>
            {upload.description && (
              <p className="text-xs text-white/40 mt-1 line-clamp-2">
                {upload.description}
              </p>
            )}
            <div className="flex items-center gap-3 mt-2">
              <span className="text-[10px] text-white/30 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {new Date(upload.created_at).toLocaleDateString()}
              </span>
              {upload.upload_type && (
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/40">
                  {upload.upload_type}
                </span>
              )}
            </div>
          </div>

          {/* Desktop Delete Button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Delete this upload?")) onDelete(upload.id);
            }}
            className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 rounded-full transition-all absolute top-2 right-2"
            title="Delete Upload"
          >
            <Trash2 className="w-4 h-4 text-red-400" />
          </button>
        </div>
      </motion.div>
    </div>
  );
}

// Uploads List View
function UploadsListView({
  uploads,
  onBack,
  onFetch,
}: {
  uploads: { id: string; title?: string; description?: string; file_url: string; upload_type: string; created_at: string }[];
  onBack: () => void;
  onFetch: () => Promise<void>;
}) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const { deleteUpload } = useAppStore();

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

  const filtered = uploads.filter(
    (u) =>
      u.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      u.file_url?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-white/60" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white">My Uploads</h2>
        <span className="ml-auto text-sm text-white/40">{uploads.length} total</span>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search uploads..."
          className="w-full pl-10 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#FF6B6B]/50"
        />
        {searchQuery && (
          <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="w-4 h-4 text-white/40" />
          </button>
        )}
      </div>

      {/* Uploads List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-[#FF6B6B] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12">
          <Image className="w-10 h-10 text-white/20 mx-auto mb-3" />
          <p className="text-white/40 text-sm">
            {searchQuery ? 'No uploads matching your search' : 'No uploads yet. Add a screenshot!'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-white/30 text-center mb-2">Swipe left to delete</p>
          {filtered.map((upload) => (
            <UploadItem key={upload.id} upload={upload} onDelete={deleteUpload} />
          ))}
        </div>
      )}
    </div>
  );
}

// Concept Item Component for Swipe-to-Delete
function ConceptItem({ concept, color, onTap, onDelete }: { concept: any; color: string; onTap: (name: string) => void; onDelete: (id: string) => void }) {
  const x = useMotionValue(0);
  const backgroundOpacity = useTransform(x, [-120, -60, 0], [1, 0.6, 0]);
  return (
    <div className="relative group overflow-hidden rounded-xl">
      <motion.div
        className="absolute inset-0 bg-red-500/20 rounded-xl flex items-center justify-end px-4"
        initial={{ opacity: 0 }}
        style={{ opacity: backgroundOpacity }}
      >
        <Trash2 className="w-5 h-5 text-red-500" />
      </motion.div>

      <motion.div
        layout
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0, x: 0 }}
        drag="x"
        dragConstraints={{ left: -140, right: 0 }}
        dragElastic={{ left: 0.3, right: 0.1 }}
        style={{ x }}
        onDragEnd={(_, info) => {
          if (info.offset.x < -100) {
            if (confirm("Delete this concept?")) {
              onDelete(concept.id);
            }
          }
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          if (confirm("Delete this concept?")) {
            onDelete(concept.id);
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

          {/* Desktop Delete Button */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm("Delete this concept?")) onDelete(concept.id);
            }}
            className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 rounded-full transition-all absolute top-2 right-2"
            title="Delete Concept"
          >
            <Trash2 className="w-4 h-4 text-red-400" />
          </button>
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
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1">
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
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1">
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
        {/* Spaced Repetition Algorithm */}
        <SettingsGroup title="Recall Algorithm">
          <div className="p-4 space-y-3">
            <p className="text-xs text-white/50 mb-2">
              Choose the spaced repetition algorithm used for scheduling your reviews.
            </p>
            <div className="flex gap-2">
              {[
                { key: 'sm2', label: 'SM-2', desc: 'Classic SuperMemo algorithm' },
                { key: 'fsrs', label: 'FSRS', desc: 'Modern free scheduler' },
              ].map((algo) => {
                const active = (settings.sr_algorithm || 'sm2') === algo.key;
                return (
                  <button
                    key={algo.key}
                    onClick={() => updateSetting('sr_algorithm', algo.key)}
                    className={`flex-1 p-3 rounded-xl border transition-all text-left ${
                      active
                        ? 'border-[#B6FF2E]/60 bg-[#B6FF2E]/10'
                        : 'border-white/10 bg-white/5 hover:border-white/20'
                    }`}
                  >
                    <span className={`text-sm font-semibold block ${active ? 'text-[#B6FF2E]' : 'text-white/70'}`}>
                      {algo.label}
                    </span>
                    <span className="text-[10px] text-white/40 mt-0.5 block">{algo.desc}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </SettingsGroup>

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
  icon: any;
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

// Quiz History View
function QuizHistoryView({
  onBack,
}: {
  onBack: () => void;
}) {
  const [quizzes, setQuizzes] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [openTopic, setOpenTopic] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await feedService.getQuizHistory();
        setQuizzes(data.quizzes || []);
      } catch (err) {
        console.error(err);
      } finally {
        setIsLoading(false);
      }
    };
    load();
  }, []);

  // Group by topic
  const grouped: Record<string, any[]> = {};
  quizzes.forEach(q => {
    const topic = q.topic || 'General';
    if (!grouped[topic]) grouped[topic] = [];
    grouped[topic].push(q);
  });

  const topics = Object.keys(grouped).sort();

  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-white/60" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white">Quiz History</h2>
        <span className="ml-auto text-sm text-white/40">{quizzes.length} Questions</span>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-[#B6FF2E] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : topics.length === 0 ? (
        <div className="text-center py-12">
          <HelpCircle className="w-10 h-10 text-white/20 mx-auto mb-3" />
          <p className="text-white/40 text-sm">No quizzes taken yet.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {topics.map(topic => (
            <div key={topic} className="glass-surface rounded-xl overflow-hidden">
              <button
                onClick={() => setOpenTopic(openTopic === topic ? null : topic)}
                className="w-full flex items-center justify-between p-4 bg-white/5 hover:bg-white/10 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-[#B6FF2E]/10 flex items-center justify-center">
                    <Brain className="w-4 h-4 text-[#B6FF2E]" />
                  </div>
                  <span className="font-medium text-white">{topic}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-white/40">{grouped[topic].length} Qs</span>
                  <ChevronDown className={`w-4 h-4 text-white/40 transition-transform ${openTopic === topic ? 'rotate-180' : ''}`} />
                </div>
              </button>

              {openTopic === topic && (
                <div className="p-4 space-y-3 bg-[#07070A]/50">
                  {grouped[topic].map((q, i) => (
                    <div key={i} className="p-3 rounded-lg border border-white/5 bg-white/5">
                      <p className="text-sm text-white/80 mb-2">{q.question_text}</p>
                      <div className="text-xs text-[#B6FF2E]">
                        Answer: {q.correct_answer || 'Check options'}
                      </div>
                      <div className="text-[10px] text-white/30 mt-2 text-right">
                        {new Date(q.created_at).toLocaleDateString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Books List View
function BooksListView({ onBack }: { onBack: () => void }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [selectedBook, setSelectedBook] = useState<any>(null);
  const { libraryBooks, fetchLibrary } = useAppStore();

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setIsLoading(true);
      await fetchLibrary();
      if (mounted) setIsLoading(false);
    };
    load();
    return () => { mounted = false; };
  }, []);

  const filtered = libraryBooks.filter(
    (b) =>
      b.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.content_text?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (selectedBook) {
    return (
      <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1 pb-10 scrollbar-hide">
        <div className="flex items-center gap-3 mb-4">
          <button
            onClick={() => setSelectedBook(null)}
            className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-white/60" />
          </button>
          <h2 className="font-heading text-lg font-bold text-white truncate flex-1">
            {selectedBook.title || 'Untitled Book'}
          </h2>
        </div>
        <div className="glass-surface rounded-xl p-4">
          <div className="flex items-center gap-3 mb-3 flex-wrap">
            <span className="text-[10px] text-white/30 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(selectedBook.created_at).toLocaleDateString()}
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/40">
              {selectedBook.resource_type || 'book'}
            </span>
            <span className="text-[10px] text-white/30">
              {selectedBook.content_text?.split(/\s+/).filter(Boolean).length.toLocaleString()} words
            </span>
          </div>
          <div className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap max-h-[60vh] overflow-y-auto scrollbar-hide">
            {selectedBook.content_text || 'No content available'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-white/60" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white">My Books</h2>
        <span className="ml-auto text-sm text-white/40">{libraryBooks.length} total</span>
      </div>

      {/* Search */}
      <div className="relative mb-4">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search books..."
          className="w-full pl-10 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#F59E0B]/50"
        />
        {searchQuery && (
          <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="w-4 h-4 text-white/40" />
          </button>
        )}
      </div>

      {/* Books List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-[#F59E0B] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12">
          <BookOpen className="w-10 h-10 text-white/20 mx-auto mb-3" />
          <p className="text-white/40 text-sm">
            {searchQuery ? 'No books matching your search' : 'No books yet. Ingest a PDF to get started!'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((book) => (
            <motion.button
              key={book.id}
              layout
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              onClick={() => setSelectedBook(book)}
              className="w-full glass-surface rounded-xl p-4 hover:bg-white/5 transition-all group text-left"
            >
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-[#F59E0B]/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <BookOpen className="w-4 h-4 text-[#F59E0B]" />
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="text-sm font-medium text-white truncate">
                    {book.title || 'Untitled Book'}
                  </h4>
                  <p className="text-xs text-white/40 mt-1 line-clamp-2">
                    {book.content_text?.slice(0, 120) || 'No content'}
                  </p>
                  <div className="flex items-center gap-3 mt-2">
                    <span className="text-[10px] text-white/30 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {new Date(book.created_at).toLocaleDateString()}
                    </span>
                    <span className="text-[10px] text-white/30">
                      {book.content_text?.split(/\s+/).filter(Boolean).length.toLocaleString()} words
                    </span>
                  </div>
                </div>
              </div>
            </motion.button>
          ))}
        </div>
      )}
    </div>
  );
}

// Stats Card
function StatsCard({
  icon: Icon,
  count,
  label,
  onClick,
  color,
  className = '',
}: {
  icon: any;
  count: number;
  label: string;
  onClick: () => void;
  color: string;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`glass-surface rounded-xl p-4 flex flex-col items-center justify-center gap-2 hover:bg-white/5 transition-colors group ${className}`}
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110"
        style={{ backgroundColor: `${color}20` }}
      >
        <Icon className="w-5 h-5" style={{ color }} />
      </div>
      <div className="text-center">
        <h3 className="font-heading font-bold text-white text-xl">{count}</h3>
        <p className="text-xs text-white/50">{label}</p>
      </div>
    </button>
  );
}
