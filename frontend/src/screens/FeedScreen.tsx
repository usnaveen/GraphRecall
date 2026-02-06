import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Heart, Bookmark, Share2, ChevronRight, Lightbulb,
  CheckCircle, XCircle, Edit3, Image as ImageIcon, Map,
  Sparkles, ArrowRight, Globe, Layers, X, Filter, ExternalLink
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import type { FeedItem, QuizOption, ConceptShowcaseCard, TermCard } from '../types';

export function FeedScreen() {
  const {
    feedItems,
    currentFeedIndex,
    likedItems,
    savedItems,
    feedTopicFilter,
    clearFeedTopicFilter,
    nextFeedItem,
    prevFeedItem,
    toggleLike,
    toggleSave,
    feedMode,
    quizHistory,
    fetchQuizHistory
  } = useAppStore();

  useEffect(() => {
    if (feedMode === 'history') {
      fetchQuizHistory();
    }
  }, [feedMode]);

  // Filter feed items by topic if a topic filter is active
  const filteredItems = feedTopicFilter
    ? feedItems.filter((item) => {
      const topic = feedTopicFilter.toLowerCase();
      // Check various fields depending on item type
      if ('concept' in item && item.concept) {
        return (
          item.concept.name?.toLowerCase().includes(topic) ||
          item.concept.domain?.toLowerCase().includes(topic)
        );
      }
      if ('relatedConcept' in item) {
        return item.relatedConcept?.toLowerCase().includes(topic);
      }
      if ('conceptName' in item) {
        return (
          item.conceptName?.toLowerCase().includes(topic) ||
          item.domain?.toLowerCase().includes(topic)
        );
      }
      return false;
    })
    : feedItems;

  const displayItems = filteredItems.length > 0 ? filteredItems : feedItems;
  const adjustedIndex = Math.min(currentFeedIndex, displayItems.length - 1);
  const currentItem = displayItems[adjustedIndex];
  const isLiked = currentItem && likedItems.has(currentItem.id);
  const isSaved = currentItem && savedItems.has(currentItem.id);
  const canReact = currentItem && ['term_card', 'flashcard', 'quiz', 'fillblank', 'code_challenge', 'screenshot', 'diagram', 'concept_showcase'].includes(currentItem.type);

  const handleSwipe = (direction: 'up' | 'down') => {
    if (direction === 'up') {
      nextFeedItem();
    } else {
      prevFeedItem();
    }
  };

  const handleShare = async () => {
    if (!currentItem) return;
    let title = 'GraphRecall';
    let text = 'Check this out from my GraphRecall feed.';
    let url: string | undefined;

    switch (currentItem.type) {
      case 'flashcard':
        title = currentItem.concept.name;
        text = `${currentItem.concept.name}: ${currentItem.concept.definition}`;
        break;
      case 'quiz':
        title = 'Quiz Question';
        text = currentItem.question;
        break;
      case 'fillblank':
        title = 'Fill in the Blank';
        text = currentItem.sentence;
        break;
      case 'screenshot':
        title = currentItem.title || 'Screenshot';
        text = currentItem.description || 'Screenshot from my GraphRecall feed.';
        url = currentItem.imageUrl;
        break;
      case 'diagram':
        title = currentItem.caption || 'Concept Diagram';
        text = currentItem.caption || 'Concept diagram from my GraphRecall feed.';
        break;
      case 'concept_showcase':
        title = currentItem.conceptName;
        text = currentItem.definition;
        break;
    }

    try {
      if (navigator.share) {
        await navigator.share({ title, text, url });
      } else if (navigator.clipboard) {
        const payload = url ? `${text}\n${url}` : text;
        await navigator.clipboard.writeText(payload);
        alert('Copied to clipboard');
      }
    } catch (err) {
      console.error('Share failed:', err);
    }
  };

  // Error State
  const { error } = useAppStore();
  if (error) {
    return (
      <div className="h-[calc(100vh-180px)] flex items-center justify-center p-4">
        <div className="text-center bg-red-500/10 p-6 rounded-2xl border border-red-500/20">
          <p className="text-red-400 font-bold mb-2">Something went wrong</p>
          <p className="text-red-300/70 text-sm font-mono break-all mb-4">{error}</p>
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => useAppStore.getState().fetchFeed(true)}
            className="px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm font-medium transition-colors"
          >
            Retry
          </motion.button>
        </div>
      </div>
    );
  }

  // Empty state
  if (!feedItems.length) {
    return (
      <div className="h-[calc(100vh-180px)] flex items-center justify-center">
        <div className="text-center">
          <p className="text-white/60 text-lg mb-2">No items in your feed</p>
          <p className="text-white/40 text-sm">Start by adding some notes to your knowledge graph!</p>
        </div>
      </div>
    );
  }

  // Continuous Feed / History View
  if (feedMode === 'history') {
    return (
      <div className="h-[calc(100vh-140px)] overflow-y-auto pb-20 px-2 scrollbar-hide pt-2">
        <div className="max-w-lg mx-auto space-y-6">
          <div className="flex items-center justify-between px-2">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-[#2EFFE6]" />
              <span className="text-sm font-heading font-bold text-white">Your Quiz Feed</span>
            </div>
            <span className="text-xs text-white/30 font-mono">{quizHistory.length} Items</span>
          </div>

          {quizHistory.length === 0 ? (
            <div className="text-center py-20 bg-white/5 rounded-2xl border border-white/5">
              <Sparkles className="w-8 h-8 text-white/20 mx-auto mb-3" />
              <p className="text-white/40">No quizzes generated yet.</p>
            </div>
          ) : (
            quizHistory.map((item, i) => (
              <motion.div
                key={`${item.id}-${i}`}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: Math.min(i * 0.05, 0.5) }}
                className="recall-card p-5 relative"
              >
                <FeedCardContent item={item} />
              </motion.div>
            ))
          )}

          <div className="h-10 text-center text-xs text-white/20 font-mono uppercase tracking-widest pt-4">
            End of Feed
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* Topic Filter Banner */}
      {feedTopicFilter && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-3 flex items-center gap-2 px-1"
        >
          <div className="flex items-center gap-2 px-3 py-2 rounded-full bg-[#B6FF2E]/15 border border-[#B6FF2E]/30">
            <Filter className="w-3.5 h-3.5 text-[#B6FF2E]" />
            <span className="text-xs text-[#B6FF2E] font-medium">
              {feedTopicFilter}
            </span>
            <button
              onClick={clearFeedTopicFilter}
              className="ml-1 p-0.5 rounded-full hover:bg-white/10 transition-colors"
            >
              <X className="w-3 h-3 text-[#B6FF2E]/70" />
            </button>
          </div>
          {filteredItems.length === 0 && feedItems.length > 0 && (
            <span className="text-xs text-white/40">No exact matches — showing all cards</span>
          )}
        </motion.div>
      )}

      {/* Card Container */}
      <div className="flex-1 relative flex items-center justify-center p-4">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentItem.id}
            initial={{ opacity: 0, y: 40, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -40, scale: 0.92 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="w-full max-w-md mx-auto h-[70vh] flex flex-col"
          >
            <div className="recall-card p-5 flex flex-col overflow-hidden h-full">
              {/* Card Content - Now Scrollable */}
              <div className="flex-1 overflow-y-auto scrollbar-hide pr-1 overscroll-contain">
                <FeedCardContent item={currentItem} />
              </div>

              {/* Instagram-style Action Bar */}
              <div className="mt-4 pt-4 border-t border-white/10 shrink-0">
                <div className="flex items-center justify-between">
                  {/* Left: Like, Save, Share */}
                  <div className="flex items-center gap-4">
                    {canReact && (
                      <>
                        {/* Like Button */}
                        <motion.button
                          whileTap={{ scale: 0.85 }}
                          onClick={() => toggleLike(currentItem.id, currentItem.type)}
                          className="flex items-center gap-1.5 group"
                        >
                          <motion.div
                            className={`p-2 rounded-full transition-colors ${isLiked ? 'bg-red-500/10' : 'bg-white/5 group-hover:bg-white/10'}`}
                          >
                            <Heart
                              className={`w-5 h-5 ${isLiked ? 'fill-red-500 text-red-500' : 'text-white/40 group-hover:text-white/60'}`}
                            />
                          </motion.div>
                        </motion.button>

                        {/* Save Button */}
                        <motion.button
                          whileTap={{ scale: 0.85 }}
                          onClick={() => toggleSave(currentItem.id, currentItem.type)}
                          className="flex items-center gap- group"
                        >
                          <motion.div
                            className={`p-2 rounded-full transition-colors ${isSaved ? 'bg-[#B6FF2E]/10' : 'bg-white/5 group-hover:bg-white/10'}`}
                          >
                            <Bookmark
                              className={`w-5 h-5 ${isSaved ? 'fill-[#B6FF2E] text-[#B6FF2E]' : 'text-white/40 group-hover:text-white/60'}`}
                            />
                          </motion.div>
                        </motion.button>
                      </>
                    )}

                    <motion.button
                      whileTap={{ scale: 0.85 }}
                      onClick={handleShare}
                      className="p-2 rounded-full bg-white/5 hover:bg-white/10 text-white/40 hover:text-white/60 transition-colors"
                    >
                      <Share2 className="w-5 h-5" />
                    </motion.button>
                  </div>

                  {/* Right: Next Button */}
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={nextFeedItem}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-[#B6FF2E] text-[#07070A] font-bold text-xs uppercase tracking-wider hover:bg-[#c5ff4d] transition-all shadow-lg shadow-[#B6FF2E]/20"
                  >
                    <span>Next</span>
                    <ChevronRight className="w-4 h-4" />
                  </motion.button>
                </div>
              </div>
            </div>
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Swipe Hints */}
      <div className="flex justify-between items-center px-4 mt-4 text-white/40 text-xs">
        <button
          onClick={() => handleSwipe('down')}
          disabled={currentFeedIndex === 0}
          className="disabled:opacity-30 hover:text-white/60 transition-colors"
        >
          ↑ Previous
        </button>
        <span className="font-mono">
          {currentFeedIndex + 1} / {feedItems.length}
        </span>
        <button
          onClick={() => handleSwipe('up')}
          disabled={currentFeedIndex === feedItems.length - 1}
          className="disabled:opacity-30 hover:text-white/60 transition-colors"
        >
          Next ↓
        </button>
      </div>
    </div>
  );
}

// Feed Card Content Component
function FeedCardContent({ item }: { item: FeedItem }) {
  switch (item.type) {
    case 'term_card':
    case 'flashcard':
      return <TermCardContent item={item} />;
    case 'quiz':
      return <QuizContent quiz={item} />;
    case 'fillblank':
      return <FillBlankContent card={item} />;
    case 'code_challenge':
      return <CodeContent card={item} />;
    case 'screenshot':
      return <ScreenshotContent card={item} />;
    case 'diagram':
      return <DiagramContent card={item} />;
    case 'concept_showcase':
      return <ConceptShowcaseContent card={item as ConceptShowcaseCard} />;
    default:
      return null;
  }
}

// Term Card Content (Restored to Legacy Design)
function TermCardContent({ item }: { item: TermCard }) {
  const { submitReview } = useAppStore();
  const concept = item.concept;
  const isLiked = useAppStore(s => s.likedItems.has(item.id));
  const isSaved = useAppStore(s => s.savedItems.has(item.id));

  return (
    <div className="flex flex-col h-full">
      {/* Eyebrow */}
      <div className="flex items-center gap-2 mb-4">
        <Lightbulb className="w-4 h-4 text-[#B6FF2E]" />
        <span className="text-xs font-mono text-[#B6FF2E] uppercase tracking-wider">Concept</span>
      </div>

      {/* Title */}
      <h2 className="font-heading text-2xl font-bold text-white mb-4">
        {concept.name}
      </h2>

      {/* Definition */}
      <p className="text-white/80 text-base leading-relaxed mb-6">
        {concept.definition}
      </p>

      {/* Prerequisites */}
      <div className="mt-auto">
        <p className="text-xs text-white/50 mb-2">Prerequisites</p>
        <div className="flex flex-wrap gap-2">
          {concept.prerequisites?.map((prereq: string, i: number) => (
            <motion.span
              key={i}
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.05 }}
              className="px-3 py-1 rounded-full text-xs font-medium bg-white/5 border border-white/10 text-white/70"
            >
              {prereq}
            </motion.span>
          ))}
        </div>
      </div>

      {/* Footer Info */}
      <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/5">
        <span className="text-xs text-white/50">{concept.domain}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-white/50">Complexity:</span>
          <div className="flex gap-0.5">
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className={`w-1.5 h-3 rounded-sm ${i < (concept.complexity || 5) ? 'bg-[#B6FF2E]' : 'bg-white/10'
                  }`}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// Code Content
function CodeContent({ card }: { card: any }) {
  const [showSolution, setShowSolution] = useState(false);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[#2EFFE6]" />
          <span className="text-xs font-mono text-[#2EFFE6] uppercase tracking-wider">Code Challenge</span>
        </div>
        <span className="px-2 py-0.5 rounded bg-white/5 text-[10px] text-white/50 font-mono uppercase">{card.language}</span>
      </div>

      <div className="flex-1 flex flex-col h-full overscroll-contain">
        <h3 className="text-lg font-bold text-white mb-4 leading-tight shrink-0">
          {card.instruction}
        </h3>

        {card.initialCode && (
          <div className="mb-4 p-4 rounded-xl bg-black/40 border border-white/5 font-mono text-sm text-cyan-400 overflow-x-auto shrink-0">
            <pre>{card.initialCode}</pre>
          </div>
        )}

        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {showSolution ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col"
            >
              <div className="p-4 rounded-xl bg-[#2EFFE6]/10 border border-[#2EFFE6]/30 font-mono text-sm text-[#2EFFE6] mb-4 overflow-x-auto whitespace-pre shrink-0">
                {card.solutionCode}
              </div>
              <div className="p-4 rounded-xl bg-white/5 border border-white/10 shrink-0">
                <p className="text-xs font-bold text-white/40 uppercase mb-2">Explanation</p>
                <p className="text-sm text-white/80 leading-relaxed">{card.explanation}</p>
              </div>
            </motion.div>
          ) : (
            <div className="flex-1 flex flex-col justify-center items-center p-8 rounded-xl bg-white/[0.02] border border-dashed border-white/10 group-hover:border-white/20 transition-all min-h-[200px]">
              <div className="w-12 h-12 rounded-full bg-white/5 flex items-center justify-center mb-4">
                <Sparkles className="w-6 h-6 text-white/20" />
              </div>
              <p className="text-sm text-white/40 text-center italic">Try the challenge in your head or editor...</p>
            </div>
          )}
        </div>
      </div>

      {!showSolution && (
        <button
          onClick={() => setShowSolution(true)}
          className="mt-6 w-full py-4 rounded-xl bg-[#2EFFE6] text-[#07070A] font-bold text-sm uppercase tracking-wider hover:bg-[#4dffeb] transition-all transform active:scale-98 shadow-[0_0_20px_rgba(46,255,230,0.2)] shrink-0"
        >
          Reveal Solution
        </button>
      )}

      {card.relatedConcept && (
        <p className="text-[10px] text-white/30 mt-4 text-center italic shrink-0">
          Focus: {card.relatedConcept}
        </p>
      )}
    </div>
  );
}

// Quiz Content
function QuizContent({ quiz }: { quiz: any }) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [showResult, setShowResult] = useState(false);

  const { submitReview } = useAppStore();

  const handleSelect = (optionId: string) => {
    if (showResult) return;
    setSelectedOption(optionId);
  };

  const handleSubmit = () => {
    if (selectedOption) {
      setShowResult(true);
      // Auto-submit review without advancing
      const correct = quiz.options.find((o: QuizOption) => o.id === selectedOption)?.isCorrect;
      submitReview(quiz.id, 'quiz', correct ? 'good' : 'again', false);
    }
  };

  const isCorrect = selectedOption && quiz.options.find((o: QuizOption) => o.id === selectedOption)?.isCorrect;

  return (
    <div className="flex flex-col h-full">
      {/* Subtle Header */}
      <div className="flex items-center justify-between mb-2 min-h-[24px]">
        <span className="text-[10px] font-mono text-white/40 uppercase tracking-widest">Quiz Card</span>

        {quiz.source_url && (
          <a
            href={quiz.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/5 hover:bg-white/10 text-[10px] text-white/50 hover:text-white/80 transition-colors"
            title="View Source"
          >
            <ExternalLink className="w-3 h-3" />
            Source
          </a>
        )}
      </div>

      {/* Grouped Question Block */}
      <div className="flex-1 flex flex-col justify-center my-2">
        <h3 className="text-xl md:text-2xl font-bold text-white leading-relaxed mb-6">
          {quiz.question}
        </h3>

        {/* Options */}
        <div className="space-y-3">
          {quiz.options.map((option: QuizOption, i: number) => {
            const isSelected = selectedOption === option.id;
            const showCorrect = showResult && option.isCorrect;
            const showWrong = showResult && isSelected && !option.isCorrect;

            // Determine styling classes
            let wrapperClass = "group w-full p-4 rounded-xl text-left transition-all duration-200 border relative overflow-hidden";
            let textClass = "";
            let indicatorClass = "w-6 h-6 rounded-full border flex items-center justify-center text-[10px] font-mono shrink-0 transition-colors";

            if (showCorrect) {
              wrapperClass += " bg-green-500/20 border-green-500/50";
              textClass = "text-green-400 font-medium";
              indicatorClass += " bg-green-500 border-transparent text-[#07070A]";
            } else if (showWrong) {
              wrapperClass += " bg-red-500/10 border-red-500/50";
              textClass = "text-red-400";
              indicatorClass += " border-red-500 text-red-500";
            } else if (isSelected) {
              wrapperClass += " bg-white/10 border-white/40";
              textClass = "text-white";
              indicatorClass += " bg-white text-[#07070A] border-transparent";
            } else {
              wrapperClass += " bg-white/5 border-white/5 hover:bg-white/10 hover:border-white/20";
              textClass = "text-white/70 group-hover:text-white";
              indicatorClass += " border-white/20 text-white/40 group-hover:border-white/40 group-hover:text-white/60";
            }

            return (
              <motion.button
                key={option.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 + 0.1 }}
                onClick={() => handleSelect(option.id)}
                disabled={showResult}
                className={wrapperClass}
              >
                <div className="flex items-center gap-3">
                  <div className={indicatorClass}>
                    {showCorrect ? <CheckCircle className="w-3.5 h-3.5" /> : (
                      showWrong ? <XCircle className="w-3.5 h-3.5" /> : String.fromCharCode(65 + i)
                    )}
                  </div>
                  <span className={`flex-1 text-sm ${textClass}`}>{option.text}</span>
                </div>
              </motion.button>
            );
          })}
        </div>
      </div>

      {/* Footer / Submit */}
      <div className="mt-4 pt-2">
        {showResult ? (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="p-4 rounded-xl bg-white/5 border border-white/10"
          >
            <div className="flex items-center gap-2 mb-2">
              {isCorrect ? <CheckCircle className="w-4 h-4 text-green-400" /> : <Lightbulb className="w-4 h-4 text-[#B6FF2E]" />}
              <span className="text-xs font-bold text-white/50 uppercase">Explanation</span>
            </div>
            <p className="text-sm text-white/80 leading-relaxed">{quiz.explanation}</p>
          </motion.div>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={!selectedOption}
            className="w-full py-3.5 rounded-xl bg-[#B6FF2E] text-[#07070A] font-bold text-sm uppercase tracking-wide disabled:opacity-30 disabled:cursor-not-allowed hover:bg-[#c5ff4d] transition-all transform active:scale-98 shadow-[0_0_20px_rgba(182,255,46,0.2)] hover:shadow-[0_0_30px_rgba(182,255,46,0.4)]"
          >
            Check Answer
          </button>
        )}
      </div>

      <div className="mt-3 flex justify-center">
        <span className="text-[10px] text-white/30">
          Related: {quiz.relatedConcept || quiz.conceptName || "General"}
        </span>
      </div>
    </div>
  );
}

// Fill in the Blank Content
function FillBlankContent({ card }: { card: any }) {
  const [answer, setAnswer] = useState('');
  const [showHint, setShowHint] = useState(false);
  const [showAnswer, setShowAnswer] = useState(false);

  const sentenceParts = card.sentence.split('__________');

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Edit3 className="w-4 h-4 text-[#2EFFE6]" />
        <span className="text-xs font-mono text-[#2EFFE6] uppercase tracking-wider">Fill in the Blank</span>
      </div>

      {/* Sentence */}
      <div className="text-white text-lg mb-6">
        {sentenceParts[0]}
        <span className="inline-block min-w-[100px] border-b-2 border-[#2EFFE6]/50 mx-1 px-2 text-center">
          {showAnswer ? card.answer : answer || '...'}
        </span>
        {sentenceParts[1]}
      </div>

      {/* Input */}
      {!showAnswer && (
        <input
          type="text"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Type your answer..."
          className="w-full p-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder:text-white/40 focus:outline-none focus:border-[#2EFFE6]/50 mb-4"
        />
      )}

      {/* Hint */}
      {showHint && !showAnswer && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-3 text-sm text-[#2EFFE6]/80"
        >
          💡 {card.hint}
        </motion.p>
      )}

      {/* Actions */}
      <div className="mt-auto flex gap-2">
        {!showAnswer && (
          <>
            <button
              onClick={() => setShowHint(true)}
              className="flex-1 py-2.5 rounded-xl bg-white/5 text-white/70 text-sm hover:bg-white/10 transition-colors"
            >
              Show Hint
            </button>
            <button
              onClick={() => setShowAnswer(true)}
              className="flex-1 py-2.5 rounded-xl bg-white/5 text-white/70 text-sm hover:bg-white/10 transition-colors"
            >
              Show Answer
            </button>
          </>
        )}
        {showAnswer && (
          <div className="w-full p-3 rounded-xl bg-green-500/10 border border-green-500/30">
            <p className="text-sm text-green-400">Answer: {card.answer}</p>
          </div>
        )}
      </div>

      <p className="text-xs text-white/40 mt-3 text-center">
        Related: {card.relatedConcept}
      </p>
    </div>
  );
}

// Screenshot Content
function ScreenshotContent({ card }: { card: any }) {
  const [imgError, setImgError] = useState(false);
  const imageSrc = card.thumbnailUrl || card.imageUrl;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <ImageIcon className="w-4 h-4 text-[#FF6B6B]" />
        <span className="text-xs font-mono text-[#FF6B6B] uppercase tracking-wider">Screenshot</span>
      </div>

      {(card.title || card.description) && (
        <div className="mb-3">
          {card.title && (
            <h3 className="text-base font-semibold text-white">{card.title}</h3>
          )}
          {card.description && (
            <p className="text-xs text-white/60 mt-1 line-clamp-2">{card.description}</p>
          )}
        </div>
      )}

      {/* Actual Image or Fallback */}
      <div className="flex-1 min-h-[200px] rounded-xl bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 flex items-center justify-center mb-4 overflow-hidden">
        {imageSrc && !imgError ? (
          <img
            src={imageSrc}
            alt={card.title || "User upload"}
            className="w-full h-full object-contain max-h-[300px]"
            onError={() => setImgError(true)}
          />
        ) : (
          <div className="text-center p-4">
            <ImageIcon className="w-12 h-12 text-white/20 mx-auto mb-2" />
            <p className="text-sm text-white/40">Image unavailable</p>
          </div>
        )}
      </div>

      {/* Linked Concepts */}
      {card.linkedConcepts?.length > 0 && (
        <div>
          <p className="text-xs text-white/50 mb-2">Linked Concepts</p>
          <div className="flex flex-wrap gap-2">
            {card.linkedConcepts.map((concept: string, i: number) => (
              <span
                key={i}
                className="px-3 py-1 rounded-full text-xs font-medium bg-[#FF6B6B]/10 border border-[#FF6B6B]/30 text-[#FF6B6B]"
              >
                {concept}
              </span>
            ))}
          </div>
        </div>
      )}

      <p className="text-xs text-white/40 mt-3">
        Added: {card.addedAt?.toLocaleDateString() || 'Recently'}
      </p>
    </div>
  );
}

// Diagram Content — renders mermaid code as styled blocks
function DiagramContent({ card }: { card: any }) {
  // Parse simple mermaid mindmap/flowchart nodes from code
  const parseMermaidNodes = (code: string): { center: string; children: string[] } => {
    const lines = (code || '').split('\n').map(l => l.trim()).filter(Boolean);
    const nodes: string[] = [];
    let center = card.caption || 'Concept Map';

    for (const line of lines) {
      // Improved regex to handle mermaid styles like id((text)), id[text], id([text])
      // We look for content inside the innermost matching brackets
      const matches = line.matchAll(/([(\[{]+)(.*?)([)\]}]+)/g);
      for (const match of matches) {
        // match[2] is the content
        const content = match[2];
        if (content && content.trim()) {
          const text = content.trim();
          // Avoid adding duplicates of center if possible, but dedup happens later
          nodes.push(text);
        }
      }

      // Explicit root check to set center
      if (line.trim().startsWith('root')) {
        const rootMatch = line.match(/root[^\w\s]*[\[\(\{]+(.*?)[\}\)\]]+/);
        if (rootMatch && rootMatch[1]) center = rootMatch[1].trim();
      }
    }

    // Deduplicate and take first 8
    const unique = [...new Set(nodes)].filter(n => n !== center).slice(0, 8);
    return { center: center || nodes[0] || 'Concept', children: unique };
  };

  const { center, children } = parseMermaidNodes(card.mermaidCode);
  const colors = ['#B6FF2E', '#2EFFE6', '#9B59B6', '#F59E0B', '#FF6B6B', '#3B82F6', '#EC4899', '#10B981'];

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Map className="w-4 h-4 text-[#9B59B6]" />
        <span className="text-xs font-mono text-[#9B59B6] uppercase tracking-wider">Concept Map</span>
      </div>

      {/* Visual mindmap from mermaid code */}
      <div className="flex-1 min-h-[200px] rounded-xl bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 p-4 mb-4">
        <div className="flex flex-col items-center gap-3">
          {/* Center node */}
          <div className="px-4 py-2 rounded-lg bg-[#B6FF2E]/20 border border-[#B6FF2E]/40 text-[#B6FF2E] text-sm font-medium text-center max-w-[200px]">
            {center}
          </div>

          {/* Connection lines */}
          {children.length > 0 && (
            <div className="w-px h-3 bg-white/20" />
          )}

          {/* Child nodes in a wrapped grid */}
          <div className="flex flex-wrap justify-center gap-2">
            {children.map((node, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.08 }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium border"
                style={{
                  backgroundColor: `${colors[i % colors.length]}15`,
                  borderColor: `${colors[i % colors.length]}40`,
                  color: colors[i % colors.length],
                }}
              >
                {node}
              </motion.div>
            ))}
          </div>
        </div>

        {/* Raw mermaid code toggle */}
        {card.mermaidCode && (
          <details className="mt-4">
            <summary className="text-[10px] text-white/30 cursor-pointer hover:text-white/50">
              View diagram code
            </summary>
            <pre className="mt-2 p-2 rounded-lg bg-black/30 text-[10px] text-white/50 font-mono overflow-x-auto max-h-[100px]">
              {card.mermaidCode}
            </pre>
          </details>
        )}
      </div>

      {/* Caption */}
      {card.caption && <p className="text-sm text-white/70 mb-2">{card.caption}</p>}
      {card.sourceNote && <p className="text-xs text-white/50">From: {card.sourceNote}</p>}
    </div>
  );
}

// Concept Showcase Content
function ConceptShowcaseContent({ card }: { card: ConceptShowcaseCard }) {
  return (
    <div className="flex flex-col h-full">
      {/* Header with emoji + domain badge */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{card.emojiIcon}</span>
          <span className="text-xs font-mono text-[#B6FF2E] uppercase tracking-wider">Concept Showcase</span>
        </div>
        <span className="px-2.5 py-1 rounded-full text-[10px] font-medium bg-white/5 border border-white/10 text-white/60">
          {card.domain}
        </span>
      </div>

      {/* Concept Name */}
      <h2 className="font-heading text-2xl font-bold text-white mb-1">
        {card.conceptName}
      </h2>

      {/* Tagline */}
      {card.tagline && (
        <p className="text-sm text-[#B6FF2E]/80 italic mb-4">
          "{card.tagline}"
        </p>
      )}

      {/* Definition */}
      <p className="text-white/70 text-sm leading-relaxed mb-4">
        {card.definition}
      </p>

      {/* Visual Metaphor */}
      {card.visualMetaphor && (
        <div className="p-3 rounded-xl bg-gradient-to-r from-[#B6FF2E]/5 to-[#2EFFE6]/5 border border-[#B6FF2E]/10 mb-4">
          <div className="flex items-start gap-2">
            <Sparkles className="w-4 h-4 text-[#B6FF2E] mt-0.5 shrink-0" />
            <p className="text-sm text-white/80">{card.visualMetaphor}</p>
          </div>
        </div>
      )}

      {/* Key Points */}
      {card.keyPoints.length > 0 && (
        <div className="space-y-2 mb-4">
          {card.keyPoints.map((point, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className="flex items-start gap-2"
            >
              <ArrowRight className="w-3.5 h-3.5 text-[#2EFFE6] mt-0.5 shrink-0" />
              <p className="text-sm text-white/70">{point}</p>
            </motion.div>
          ))}
        </div>
      )}

      {/* Real World Example */}
      {card.realWorldExample && (
        <div className="p-3 rounded-xl bg-white/5 border border-white/10 mb-4">
          <div className="flex items-start gap-2">
            <Globe className="w-4 h-4 text-white/40 mt-0.5 shrink-0" />
            <div>
              <p className="text-[10px] text-white/40 uppercase tracking-wider mb-1">Real-World Example</p>
              <p className="text-sm text-white/70">{card.realWorldExample}</p>
            </div>
          </div>
        </div>
      )}

      {/* Footer: Prerequisites + Connections */}
      <div className="mt-auto">
        {/* Related Concepts */}
        {(card.prerequisites.length > 0 || card.relatedConcepts.length > 0) && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {card.prerequisites.map((p, i) => (
              <span
                key={`prereq-${i}`}
                className="px-2.5 py-1 rounded-full text-[10px] font-medium bg-[#2EFFE6]/10 border border-[#2EFFE6]/20 text-[#2EFFE6]"
              >
                {p}
              </span>
            ))}
            {card.relatedConcepts.map((r, i) => (
              <span
                key={`related-${i}`}
                className="px-2.5 py-1 rounded-full text-[10px] font-medium bg-white/5 border border-white/10 text-white/60"
              >
                {r}
              </span>
            ))}
          </div>
        )}

        {/* Complexity bar */}
        <div className="flex items-center justify-between pt-3 border-t border-white/5">
          <div className="flex items-center gap-1.5">
            <Layers className="w-3 h-3 text-white/40" />
            <span className="text-xs text-white/40">Complexity</span>
          </div>
          <div className="flex gap-0.5">
            {Array.from({ length: 10 }).map((_, i) => (
              <div
                key={i}
                className={`w-1.5 h-3 rounded-sm ${i < card.complexityScore ? 'bg-[#B6FF2E]' : 'bg-white/10'
                  }`}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
