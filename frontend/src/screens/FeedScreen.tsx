import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Heart, Bookmark, Share2, ChevronRight, Lightbulb,
  CheckCircle, XCircle, Edit3, Image as ImageIcon, Map
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import type { FeedItem, QuizOption } from '../types';

export function FeedScreen() {
  const {
    feedItems,
    currentFeedIndex,
    likedItems,
    savedItems,
    nextFeedItem,
    prevFeedItem,
    toggleLike,
    toggleSave
  } = useAppStore();

  const currentItem = feedItems[currentFeedIndex];
  const isLiked = currentItem && likedItems.has(currentItem.id);
  const isSaved = currentItem && savedItems.has(currentItem.id);

  const handleSwipe = (direction: 'up' | 'down') => {
    if (direction === 'up') {
      nextFeedItem();
    } else {
      prevFeedItem();
    }
  };

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

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* Card Container */}
      <div className="flex-1 relative flex items-center justify-center">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentItem.id}
            initial={{ opacity: 0, y: 40, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -40, scale: 0.92 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="w-full max-w-md mx-auto"
          >
            <div className="recall-card p-5 min-h-[480px] flex flex-col">
              {/* Card Content */}
              <div className="flex-1">
                <FeedCardContent item={currentItem} />
              </div>

              {/* Instagram-style Action Bar */}
              <div className="mt-4 pt-4 border-t border-white/10">
                <div className="flex items-center justify-between">
                  {/* Left: Like, Save, Share */}
                  <div className="flex items-center gap-4">
                    {/* Like Button */}
                    <motion.button
                      whileTap={{ scale: 0.85 }}
                      onClick={() => toggleLike(currentItem.id, currentItem.type)}
                      className="flex items-center gap-1.5 group"
                    >
                      <motion.div
                        animate={isLiked ? { scale: [1, 1.3, 1] } : {}}
                        transition={{ duration: 0.3 }}
                      >
                        <Heart
                          className={`w-6 h-6 transition-all duration-200 ${isLiked
                            ? 'fill-red-500 text-red-500'
                            : 'text-white/60 group-hover:text-white'
                            }`}
                        />
                      </motion.div>
                      <span className={`text-sm ${isLiked ? 'text-red-400' : 'text-white/60'}`}>
                        {isLiked ? 'Liked' : 'Like'}
                      </span>
                    </motion.button>

                    {/* Save Button */}
                    <motion.button
                      whileTap={{ scale: 0.85 }}
                      onClick={() => toggleSave(currentItem.id, currentItem.type)}
                      className="flex items-center gap-1.5 group"
                    >
                      <Bookmark
                        className={`w-6 h-6 transition-all duration-200 ${isSaved
                          ? 'fill-[#B6FF2E] text-[#B6FF2E]'
                          : 'text-white/60 group-hover:text-white'
                          }`}
                      />
                      <span className={`text-sm ${isSaved ? 'text-[#B6FF2E]' : 'text-white/60'}`}>
                        {isSaved ? 'Saved' : 'Save'}
                      </span>
                    </motion.button>

                    {/* Share Button */}
                    <motion.button
                      whileTap={{ scale: 0.85 }}
                      className="flex items-center gap-1.5 group"
                    >
                      <Share2 className="w-6 h-6 text-white/60 group-hover:text-white transition-colors" />
                      <span className="text-sm text-white/60">Share</span>
                    </motion.button>
                  </div>

                  {/* Right: Next/Related */}
                  <div className="flex items-center gap-2">
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => nextFeedItem()}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[#B6FF2E]/10 border border-[#B6FF2E]/30 text-[#B6FF2E] text-sm font-medium hover:bg-[#B6FF2E]/20 transition-colors"
                    >
                      Next
                      <ChevronRight className="w-4 h-4" />
                    </motion.button>
                  </div>
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
    case 'flashcard':
      return <FlashcardContent concept={item.concept} />;
    case 'quiz':
      return <QuizContent quiz={item} />;
    case 'fillblank':
      return <FillBlankContent card={item} />;
    case 'screenshot':
      return <ScreenshotContent card={item} />;
    case 'diagram':
      return <DiagramContent card={item} />;
    default:
      return null;
  }
}

// Flashcard Content
function FlashcardContent({ concept }: { concept: any }) {
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
          {concept.prerequisites.map((prereq: string, i: number) => (
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
                className={`w-1.5 h-3 rounded-sm ${i < concept.complexity ? 'bg-[#B6FF2E]' : 'bg-white/10'
                  }`}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// Quiz Content
function QuizContent({ quiz }: { quiz: any }) {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [showResult, setShowResult] = useState(false);

  const handleSelect = (optionId: string) => {
    if (showResult) return;
    setSelectedOption(optionId);
  };

  const handleSubmit = () => {
    if (selectedOption) {
      setShowResult(true);
    }
  };

  const isCorrect = selectedOption && quiz.options.find((o: QuizOption) => o.id === selectedOption)?.isCorrect;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <div className="w-6 h-6 rounded-full bg-[#B6FF2E]/20 flex items-center justify-center">
          <span className="text-xs text-[#B6FF2E]">?</span>
        </div>
        <span className="text-xs font-mono text-[#B6FF2E] uppercase tracking-wider">Quiz Time</span>
      </div>

      {/* Question */}
      <p className="text-white text-lg font-medium mb-6">
        {quiz.question}
      </p>

      {/* Options */}
      <div className="space-y-2 flex-1">
        {quiz.options.map((option: QuizOption, i: number) => {
          const isSelected = selectedOption === option.id;
          const showCorrect = showResult && option.isCorrect;
          const showWrong = showResult && isSelected && !option.isCorrect;

          return (
            <motion.button
              key={option.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.05 }}
              onClick={() => handleSelect(option.id)}
              disabled={showResult}
              className={`
                w-full p-3 rounded-xl text-left text-sm transition-all duration-200
                ${showCorrect
                  ? 'bg-green-500/20 border border-green-500/50 text-green-400'
                  : showWrong
                    ? 'bg-red-500/20 border border-red-500/50 text-red-400'
                    : isSelected
                      ? 'bg-[#B6FF2E]/20 border border-[#B6FF2E]/50 text-[#B6FF2E]'
                      : 'bg-white/5 border border-white/10 text-white/80 hover:bg-white/10'
                }
              `}
            >
              <div className="flex items-center gap-3">
                <span className="w-6 h-6 rounded-full bg-white/10 flex items-center justify-center text-xs font-mono">
                  {String.fromCharCode(65 + i)}
                </span>
                {option.text}
                {showCorrect && <CheckCircle className="w-4 h-4 ml-auto" />}
                {showWrong && <XCircle className="w-4 h-4 ml-auto" />}
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* Result or Submit */}
      {showResult ? (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 p-3 rounded-xl bg-white/5"
        >
          <p className={`text-sm ${isCorrect ? 'text-green-400' : 'text-red-400'}`}>
            {isCorrect ? '✅ Correct!' : '❌ Incorrect'}
          </p>
          <p className="text-xs text-white/60 mt-1">{quiz.explanation}</p>
        </motion.div>
      ) : (
        <button
          onClick={handleSubmit}
          disabled={!selectedOption}
          className="mt-4 w-full py-3 rounded-xl bg-[#B6FF2E] text-[#07070A] font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#c5ff4d] transition-colors"
        >
          Submit Answer
        </button>
      )}

      <p className="text-xs text-white/40 mt-3 text-center">
        Related: {quiz.relatedConcept}
      </p>
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
          className="w-full p-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder:text-white/40 focus:outline-none focus:border-[#2EFFE6]/50"
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
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <ImageIcon className="w-4 h-4 text-[#FF6B6B]" />
        <span className="text-xs font-mono text-[#FF6B6B] uppercase tracking-wider">Screenshot</span>
      </div>

      {/* Image Placeholder */}
      <div className="flex-1 min-h-[200px] rounded-xl bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 flex items-center justify-center mb-4">
        <div className="text-center">
          <ImageIcon className="w-12 h-12 text-white/20 mx-auto mb-2" />
          <p className="text-sm text-white/40">User uploaded screenshot</p>
        </div>
      </div>

      {/* Linked Concepts */}
      <div>
        <p className="text-xs text-white/50 mb-2">Linked Concepts</p>
        <div className="flex flex-wrap gap-2">
          {card.linkedConcepts?.map((concept: string, i: number) => (
            <span
              key={i}
              className="px-3 py-1 rounded-full text-xs font-medium bg-[#FF6B6B]/10 border border-[#FF6B6B]/30 text-[#FF6B6B]"
            >
              {concept}
            </span>
          )) || (
              <>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-[#B6FF2E]/10 border border-[#B6FF2E]/30 text-[#B6FF2E]">CNNs</span>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-[#2EFFE6]/10 border border-[#2EFFE6]/30 text-[#2EFFE6]">Pooling</span>
                <span className="px-3 py-1 rounded-full text-xs font-medium bg-[#FF6B6B]/10 border border-[#FF6B6B]/30 text-[#FF6B6B]">Filters</span>
              </>
            )}
        </div>
      </div>

      <p className="text-xs text-white/40 mt-3">
        Added: {card.addedAt?.toLocaleDateString() || 'Jan 15, 2026'}
      </p>
    </div>
  );
}

// Diagram Content
function DiagramContent({ card }: { card: any }) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Map className="w-4 h-4 text-[#9B59B6]" />
        <span className="text-xs font-mono text-[#9B59B6] uppercase tracking-wider">Concept Map</span>
      </div>

      {/* Diagram Placeholder */}
      <div className="flex-1 min-h-[200px] rounded-xl bg-gradient-to-br from-white/5 to-white/[0.02] border border-white/10 flex items-center justify-center mb-4 p-4">
        <div className="text-center">
          <div className="flex flex-col items-center gap-2">
            <div className="px-4 py-2 rounded-lg bg-[#B6FF2E]/20 border border-[#B6FF2E]/40 text-[#B6FF2E] text-sm font-medium">
              Neural Network
            </div>
            <div className="flex gap-4 mt-2">
              <div className="px-3 py-1.5 rounded-lg bg-white/10 text-white/70 text-xs">Input Layer</div>
              <div className="px-3 py-1.5 rounded-lg bg-white/10 text-white/70 text-xs">Hidden Layers</div>
              <div className="px-3 py-1.5 rounded-lg bg-white/10 text-white/70 text-xs">Output Layer</div>
            </div>
          </div>
        </div>
      </div>

      {/* Caption */}
      <p className="text-sm text-white/70 mb-2">{card.caption}</p>
      <p className="text-xs text-white/50">From: {card.sourceNote}</p>

      {/* Actions */}
      <div className="flex gap-2 mt-4">
        <button className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-sm hover:bg-white/10 transition-colors">
          Open Original Note
        </button>
        <button className="flex-1 py-2 rounded-xl bg-[#9B59B6]/20 text-[#9B59B6] text-sm hover:bg-[#9B59B6]/30 transition-colors">
          Explore Graph
        </button>
      </div>
    </div>
  );
}
