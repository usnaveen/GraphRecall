import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BookOpen, Search, X, Clock, ChevronRight, FileText,
  Layers, Hash, ArrowLeft, BookMarked, GraduationCap
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

type LibraryView = 'grid' | 'detail';

interface BookItem {
  id: string;
  title: string;
  content_text: string;
  resource_type: string;
  created_at: string;
  source_url?: string;
}

// Generate a deterministic pastel gradient from book title
function getBookGradient(title: string): string {
  const hash = title.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const hue1 = hash % 360;
  const hue2 = (hue1 + 40) % 360;
  return `linear-gradient(135deg, hsl(${hue1}, 60%, 30%) 0%, hsl(${hue2}, 50%, 20%) 100%)`;
}

// Extract chapter headings from content
function extractChapters(content: string): string[] {
  const lines = content.split('\n');
  const chapters: string[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('# ') || trimmed.startsWith('## ')) {
      const heading = trimmed.replace(/^#{1,2}\s+/, '');
      if (heading.length > 2 && heading.length < 120) {
        chapters.push(heading);
      }
    }
    if (chapters.length >= 30) break;
  }
  return chapters;
}

// Estimate word count
function estimateWords(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

// Estimate read time (200 wpm)
function estimateReadTime(text: string): string {
  const words = estimateWords(text);
  const minutes = Math.round(words / 200);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainMins = minutes % 60;
  return remainMins > 0 ? `${hours}h ${remainMins}m` : `${hours}h`;
}

export function LibraryScreen() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBook, setSelectedBook] = useState<BookItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const { libraryBooks, fetchLibrary, notesList, fetchNotes } = useAppStore();

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setIsLoading(true);
      await fetchLibrary();
      // Also fetch all notes to show non-book items in a separate section
      await fetchNotes();
      if (mounted) setIsLoading(false);
    };
    load();
    return () => { mounted = false; };
  }, []);

  // Combine: books from library + notes that look like larger content
  const allBooks = libraryBooks;

  const filtered = allBooks.filter(
    (b) =>
      b.title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      b.content_text?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (selectedBook) {
    return <BookDetailView book={selectedBook} onBack={() => setSelectedBook(null)} />;
  }

  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1 pb-10 scrollbar-hide">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <div className="flex items-center gap-3 mb-1">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[#B6FF2E]/20 to-[#2EFFE6]/20 flex items-center justify-center">
            <BookOpen className="w-5 h-5 text-[#B6FF2E]" />
          </div>
          <div>
            <h1 className="font-heading text-xl font-bold text-white">Library</h1>
            <p className="text-xs text-white/40">
              {allBooks.length} {allBooks.length === 1 ? 'book' : 'books'} ingested
            </p>
          </div>
        </div>
      </motion.div>

      {/* Search */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="relative mb-5"
      >
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search books..."
          className="w-full pl-10 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50 transition-colors"
        />
        {searchQuery && (
          <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2">
            <X className="w-4 h-4 text-white/40" />
          </button>
        )}
      </motion.div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <div className="w-8 h-8 border-2 border-[#B6FF2E] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <p className="text-sm text-white/40">Loading library...</p>
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <EmptyLibrary hasSearch={!!searchQuery} />
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15 }}
          className="space-y-3"
        >
          {filtered.map((book, i) => (
            <BookCard
              key={book.id}
              book={book}
              index={i}
              onClick={() => setSelectedBook(book)}
            />
          ))}
        </motion.div>
      )}

      {/* Info footer */}
      {!isLoading && allBooks.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          className="mt-6 text-center"
        >
          <p className="text-[10px] text-white/20">
            Books are ingested via Colab notebook backdoor
          </p>
        </motion.div>
      )}
    </div>
  );
}

// Book Card Component
function BookCard({ book, index, onClick }: { book: BookItem; index: number; onClick: () => void }) {
  const gradient = getBookGradient(book.title || 'Untitled');
  const words = estimateWords(book.content_text || '');
  const readTime = estimateReadTime(book.content_text || '');
  const chapters = extractChapters(book.content_text || '');

  return (
    <motion.button
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      onClick={onClick}
      className="w-full glass-surface rounded-xl p-4 hover:bg-white/5 transition-all group text-left"
    >
      <div className="flex gap-4">
        {/* Book Cover */}
        <div
          className="w-16 h-22 rounded-lg flex-shrink-0 flex items-end justify-center overflow-hidden relative"
          style={{
            background: gradient,
            minHeight: '5.5rem',
          }}
        >
          <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent" />
          <BookMarked className="w-6 h-6 text-white/40 relative z-10 mb-2" />
          {/* Spine effect */}
          <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-white/10" />
        </div>

        {/* Book Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold text-white line-clamp-2 group-hover:text-[#B6FF2E] transition-colors">
              {book.title || 'Untitled Book'}
            </h3>
            <ChevronRight className="w-4 h-4 text-white/20 flex-shrink-0 mt-0.5 group-hover:text-white/40 transition-colors" />
          </div>

          {/* Preview text */}
          <p className="text-xs text-white/40 mt-1.5 line-clamp-2">
            {book.content_text?.slice(0, 150) || 'No content preview'}
          </p>

          {/* Meta info */}
          <div className="flex items-center gap-3 mt-2.5 flex-wrap">
            <span className="text-[10px] text-white/30 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(book.created_at).toLocaleDateString()}
            </span>
            <span className="text-[10px] text-white/30 flex items-center gap-1">
              <FileText className="w-3 h-3" />
              {words.toLocaleString()} words
            </span>
            <span className="text-[10px] text-white/30 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              ~{readTime}
            </span>
            {chapters.length > 0 && (
              <span className="text-[10px] text-white/30 flex items-center gap-1">
                <Layers className="w-3 h-3" />
                {chapters.length} sections
              </span>
            )}
          </div>
        </div>
      </div>
    </motion.button>
  );
}

// Book Detail View
function BookDetailView({ book, onBack }: { book: BookItem; onBack: () => void }) {
  const [activeSection, setActiveSection] = useState<'overview' | 'chapters' | 'content'>('overview');
  const chapters = extractChapters(book.content_text || '');
  const words = estimateWords(book.content_text || '');
  const readTime = estimateReadTime(book.content_text || '');
  const gradient = getBookGradient(book.title || 'Untitled');
  const { setActiveTab } = useAppStore();

  return (
    <div className="h-[calc(100vh-120px)] overflow-y-auto pr-1 pb-10 scrollbar-hide">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={onBack}
          className="p-2 rounded-full bg-white/5 hover:bg-white/10 transition-colors"
        >
          <ArrowLeft className="w-5 h-5 text-white/60" />
        </button>
        <h2 className="font-heading text-lg font-bold text-white truncate flex-1">
          {book.title || 'Untitled Book'}
        </h2>
      </div>

      {/* Book Hero */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-surface rounded-2xl p-5 mb-4"
      >
        <div className="flex gap-4">
          {/* Large Cover */}
          <div
            className="w-24 rounded-xl flex-shrink-0 flex items-end justify-center overflow-hidden relative"
            style={{
              background: gradient,
              minHeight: '8rem',
            }}
          >
            <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
            <BookMarked className="w-8 h-8 text-white/40 relative z-10 mb-3" />
            <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-white/10" />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <h2 className="font-heading text-lg font-bold text-white mb-2">
              {book.title || 'Untitled Book'}
            </h2>

            <div className="grid grid-cols-2 gap-2 mb-3">
              <div className="text-center p-2 rounded-lg bg-white/5">
                <p className="text-xs text-white/40">Words</p>
                <p className="text-sm font-semibold text-white">{words.toLocaleString()}</p>
              </div>
              <div className="text-center p-2 rounded-lg bg-white/5">
                <p className="text-xs text-white/40">Read Time</p>
                <p className="text-sm font-semibold text-white">~{readTime}</p>
              </div>
              <div className="text-center p-2 rounded-lg bg-white/5">
                <p className="text-xs text-white/40">Sections</p>
                <p className="text-sm font-semibold text-white">{chapters.length}</p>
              </div>
              <div className="text-center p-2 rounded-lg bg-white/5">
                <p className="text-xs text-white/40">Added</p>
                <p className="text-sm font-semibold text-white">
                  {new Date(book.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </p>
              </div>
            </div>

            {/* Quick actions */}
            <div className="flex gap-2">
              <button
                onClick={() => setActiveTab('assistant')}
                className="flex-1 py-2 rounded-lg bg-[#B6FF2E]/10 border border-[#B6FF2E]/20 text-[#B6FF2E] text-xs font-medium hover:bg-[#B6FF2E]/20 transition-colors flex items-center justify-center gap-1.5"
              >
                <GraduationCap className="w-3.5 h-3.5" />
                Ask AI
              </button>
              <button
                onClick={() => setActiveTab('feed')}
                className="flex-1 py-2 rounded-lg bg-[#2EFFE6]/10 border border-[#2EFFE6]/20 text-[#2EFFE6] text-xs font-medium hover:bg-[#2EFFE6]/20 transition-colors flex items-center justify-center gap-1.5"
              >
                <Hash className="w-3.5 h-3.5" />
                Study
              </button>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Tab Switcher */}
      <div className="flex gap-1 mb-4 bg-white/5 rounded-xl p-1">
        {(['overview', 'chapters', 'content'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveSection(tab)}
            className={`flex-1 py-2 rounded-lg text-xs font-medium transition-all capitalize ${
              activeSection === tab
                ? 'bg-[#B6FF2E]/20 text-[#B6FF2E]'
                : 'text-white/50 hover:text-white/70'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <AnimatePresence mode="wait">
        {activeSection === 'overview' && (
          <motion.div
            key="overview"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="space-y-3"
          >
            {/* Content preview */}
            <div className="glass-surface rounded-xl p-4">
              <h4 className="text-xs font-mono text-white/40 uppercase tracking-wider mb-2">Preview</h4>
              <p className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap">
                {book.content_text?.slice(0, 800) || 'No content available'}
                {(book.content_text?.length || 0) > 800 && (
                  <span className="text-white/30">...</span>
                )}
              </p>
            </div>

            {/* Resource type badge */}
            <div className="glass-surface rounded-xl p-4">
              <h4 className="text-xs font-mono text-white/40 uppercase tracking-wider mb-2">Details</h4>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="px-2 py-1 rounded-full text-[10px] bg-[#B6FF2E]/10 text-[#B6FF2E] border border-[#B6FF2E]/20">
                  {book.resource_type || 'book'}
                </span>
                <span className="px-2 py-1 rounded-full text-[10px] bg-white/5 text-white/40">
                  {(book.content_text?.length || 0).toLocaleString()} characters
                </span>
                {book.source_url && (
                  <a
                    href={book.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-2 py-1 rounded-full text-[10px] bg-[#2EFFE6]/10 text-[#2EFFE6] border border-[#2EFFE6]/20 hover:bg-[#2EFFE6]/20 transition-colors"
                  >
                    Source Link
                  </a>
                )}
              </div>
            </div>
          </motion.div>
        )}

        {activeSection === 'chapters' && (
          <motion.div
            key="chapters"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            {chapters.length === 0 ? (
              <div className="text-center py-12">
                <Layers className="w-10 h-10 text-white/20 mx-auto mb-3" />
                <p className="text-white/40 text-sm">No chapters/headings detected in this book</p>
              </div>
            ) : (
              <div className="glass-surface rounded-xl overflow-hidden">
                {chapters.map((chapter, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-3 p-3 border-b border-white/5 last:border-b-0 hover:bg-white/5 transition-colors"
                  >
                    <span className="text-[10px] text-white/30 font-mono w-6 text-right flex-shrink-0">
                      {i + 1}
                    </span>
                    <span className="text-sm text-white/70 flex-1 truncate">
                      {chapter}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}

        {activeSection === 'content' && (
          <motion.div
            key="content"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <div className="glass-surface rounded-xl p-4 max-h-[60vh] overflow-y-auto scrollbar-hide">
              <div className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap font-mono">
                {book.content_text || 'No content available'}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Empty Library Component
function EmptyLibrary({ hasSearch }: { hasSearch: boolean }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="text-center py-16"
    >
      <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[#B6FF2E]/10 to-[#2EFFE6]/10 flex items-center justify-center mx-auto mb-4">
        <BookOpen className="w-10 h-10 text-white/20" />
      </div>
      {hasSearch ? (
        <>
          <h3 className="font-heading text-lg font-semibold text-white/60 mb-2">No results</h3>
          <p className="text-sm text-white/30 max-w-xs mx-auto">
            No books match your search. Try a different query.
          </p>
        </>
      ) : (
        <>
          <h3 className="font-heading text-lg font-semibold text-white/60 mb-2">Your library is empty</h3>
          <p className="text-sm text-white/30 max-w-xs mx-auto mb-4">
            Use the Colab notebook to ingest PDF textbooks into your knowledge graph.
          </p>
          <div className="glass-surface rounded-xl p-4 max-w-sm mx-auto text-left">
            <h4 className="text-xs font-mono text-[#B6FF2E] mb-2">How to add a book:</h4>
            <ol className="text-xs text-white/50 space-y-1.5 list-decimal pl-4">
              <li>Open <code className="text-[#2EFFE6] bg-white/5 px-1 rounded">notebooks/book_ingestion_colab.ipynb</code> in Google Colab</li>
              <li>Upload your PDF and configure your backend URL</li>
              <li>Run all cells to process and ingest the book</li>
              <li>Come back here to see your book!</li>
            </ol>
          </div>
        </>
      )}
    </motion.div>
  );
}
