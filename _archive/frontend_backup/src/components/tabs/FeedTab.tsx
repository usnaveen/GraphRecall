"use client";

import React, { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Check,
  X,
  HelpCircle,
  Lightbulb,
  Image,
  BookOpen,
  Filter,
  RefreshCw
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStore } from "@/lib/store";
import api, { FeedItem, DifficultyLevel } from "@/lib/api";
import MermaidCard from "@/components/ui/MermaidCard";

// Feed Item Components
const MCQCard = ({ item, onAnswer }: { item: FeedItem; onAnswer: (correct: boolean) => void }) => {
  const [selectedOption, setSelectedOption] = useState<string | null>(null);
  const [showResult, setShowResult] = useState(false);

  const content = item.content as {
    question: string;
    options: { id: string; text: string; is_correct: boolean }[];
    explanation: string;
  };

  const handleSelect = (optionId: string) => {
    if (showResult) return;
    setSelectedOption(optionId);
  };

  const handleSubmit = () => {
    if (!selectedOption) return;
    setShowResult(true);
    const isCorrect = content.options.find(o => o.id === selectedOption)?.is_correct || false;
    onAnswer(isCorrect);
  };

  return (
    <div className="h-full flex flex-col p-6 recall-card">
      <div className="flex items-center gap-2 mb-4">
        <HelpCircle className="h-5 w-5 text-purple-400" />
        <span className="text-purple-400 font-medium">Quiz</span>
        {item.concept_name && (
          <span className="text-slate-500 text-sm">• {item.concept_name}</span>
        )}
      </div>

      <h2 className="text-xl font-semibold text-white mb-6">{content.question}</h2>

      <div className="space-y-3 flex-1">
        {content.options.map((option) => {
          const isSelected = selectedOption === option.id;
          const isCorrect = option.is_correct;

          let bgColor = "bg-[#1A1A1C] border-[#27272A]";
          if (showResult) {
            if (isCorrect) bgColor = "bg-green-500/20 border-green-500";
            else if (isSelected) bgColor = "bg-red-500/20 border-red-500";
          } else if (isSelected) {
            bgColor = "bg-purple-500/20 border-purple-500";
          }

          return (
            <button
              key={option.id}
              onClick={() => handleSelect(option.id)}
              disabled={showResult}
              className={`w-full p-4 rounded-xl border-2 text-left transition-all ${bgColor}`}
            >
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${isSelected ? "bg-purple-500 text-white" : "bg-[#27272A] text-slate-400"
                  }`}>
                  {option.id}
                </div>
                <span className="text-white">{option.text}</span>
              </div>
            </button>
          );
        })}
      </div>

      {showResult && content.explanation && (
        <div className="mt-4 p-4 bg-[#1A1A1C] rounded-xl border border-[#27272A]">
          <p className="text-sm text-slate-400">{content.explanation}</p>
        </div>
      )}

      {!showResult && (
        <Button
          onClick={handleSubmit}
          disabled={!selectedOption}
          className="mt-6 bg-purple-600 hover:bg-purple-700"
        >
          Submit Answer
        </Button>
      )}
    </div>
  );
};

const ConceptShowcaseCard = ({ item }: { item: FeedItem }) => {
  const content = item.content as {
    concept_name: string;
    definition: string;
    domain: string;
    complexity_score: number;
    tagline?: string;
    visual_metaphor?: string;
    key_points?: string[];
    emoji_icon?: string;
    prerequisites?: string[];
  };

  return (
    <div className="h-full flex flex-col p-6 recall-card">
      <div className="flex items-center gap-2 mb-4">
        <Lightbulb className="h-5 w-5 text-amber-400" />
        <span className="text-amber-400 font-medium">Concept</span>
        <span className="text-slate-500 text-sm">• {content.domain}</span>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center text-center">
        <div className="text-6xl mb-4">{content.emoji_icon || "📚"}</div>

        <h2 className="text-2xl font-bold text-white mb-2">{content.concept_name}</h2>

        {content.tagline && (
          <p className="text-purple-400 text-sm mb-4">{content.tagline}</p>
        )}

        <p className="text-slate-300 mb-6 max-w-md">{content.definition}</p>

        {content.visual_metaphor && (
          <div className="bg-[#1A1A1C] p-4 rounded-xl border border-[#27272A] mb-4 max-w-md">
            <p className="text-sm text-slate-400">
              💡 <span className="text-slate-300">{content.visual_metaphor}</span>
            </p>
          </div>
        )}

        {content.key_points && content.key_points.length > 0 && (
          <div className="text-left w-full max-w-md">
            <h4 className="text-sm font-medium text-slate-400 mb-2">Key Points:</h4>
            <ul className="space-y-1">
              {content.key_points.map((point, i) => (
                <li key={i} className="text-sm text-slate-300 flex items-start gap-2">
                  <span className="text-purple-400">•</span>
                  {point}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between mt-4 pt-4 border-t border-[#27272A]">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Complexity:</span>
          <div className="flex">
            {[...Array(10)].map((_, i) => (
              <div
                key={i}
                className={`w-2 h-2 rounded-full mr-0.5 ${i < content.complexity_score ? "bg-purple-500" : "bg-[#27272A]"
                  }`}
              />
            ))}
          </div>
        </div>
        {content.prerequisites && content.prerequisites.length > 0 && (
          <span className="text-xs text-slate-500">
            Prerequisites: {content.prerequisites.slice(0, 2).join(", ")}
          </span>
        )}
      </div>
    </div>
  );
};

const FillBlankCard = ({ item, onAnswer }: { item: FeedItem; onAnswer: (correct: boolean) => void }) => {
  const [answer, setAnswer] = useState("");
  const [showResult, setShowResult] = useState(false);

  const content = item.content as {
    sentence: string;
    answers: string[];
    hint?: string;
  };

  const handleSubmit = () => {
    if (!answer.trim()) return;
    setShowResult(true);
    const isCorrect = content.answers.some(
      a => a.toLowerCase().trim() === answer.toLowerCase().trim()
    );
    onAnswer(isCorrect);
  };

  return (
    <div className="h-full flex flex-col p-6 recall-card">
      <div className="flex items-center gap-2 mb-4">
        <BookOpen className="h-5 w-5 text-cyan-400" />
        <span className="text-cyan-400 font-medium">Fill in the Blank</span>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center">
        <p className="text-xl text-white text-center mb-8 max-w-md">
          {content.sentence.split("_____").map((part, i, arr) => (
            <React.Fragment key={i}>
              {part}
              {i < arr.length - 1 && (
                <span className="inline-block w-32 border-b-2 border-purple-500 mx-1" />
              )}
            </React.Fragment>
          ))}
        </p>

        {!showResult ? (
          <>
            <input
              type="text"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Type your answer..."
              className="w-full max-w-sm p-4 bg-[#1A1A1C] border-2 border-[#27272A] rounded-xl text-white text-center focus:border-purple-500 focus:outline-none"
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            />

            {content.hint && (
              <p className="text-sm text-slate-500 mt-4">💡 Hint: {content.hint}</p>
            )}
          </>
        ) : (
          <div className={`p-4 rounded-xl ${content.answers.some(a => a.toLowerCase().trim() === answer.toLowerCase().trim())
            ? "bg-green-500/20 border-2 border-green-500"
            : "bg-red-500/20 border-2 border-red-500"
            }`}>
            <p className="text-white">Your answer: <strong>{answer}</strong></p>
            <p className="text-slate-400 text-sm mt-1">
              Correct answer: <strong>{content.answers[0]}</strong>
            </p>
          </div>
        )}
      </div>

      {!showResult && (
        <Button
          onClick={handleSubmit}
          disabled={!answer.trim()}
          className="mt-6 bg-purple-600 hover:bg-purple-700"
        >
          Check Answer
        </Button>
      )}
    </div>
  );
};

const ScreenshotCard = ({ item }: { item: FeedItem }) => {
  const content = item.content as {
    file_url: string;
    title?: string;
    description?: string;
  };

  return (
    <div className="h-full flex flex-col recall-card">
      <div className="flex items-center gap-2 p-4">
        <Image className="h-5 w-5 text-pink-400" />
        <span className="text-pink-400 font-medium">Screenshot</span>
        {content.title && (
          <span className="text-slate-500 text-sm">• {content.title}</span>
        )}
      </div>

      <div className="flex-1 flex items-center justify-center p-4">
        <img
          src={content.file_url}
          alt={content.title || "Screenshot"}
          className="max-w-full max-h-full object-contain rounded-xl"
        />
      </div>

      {content.description && (
        <div className="p-4 border-t border-[#27272A]">
          <p className="text-sm text-slate-400">{content.description}</p>
        </div>
      )}
    </div>
  );
};

const FlashcardCard = ({ item }: { item: FeedItem }) => {
  const [isFlipped, setIsFlipped] = useState(false);

  const content = item.content as {
    front: string;
    back: string;
    card_type?: string;
  };

  return (
    <div className="h-full flex flex-col p-6 recall-card">
      <div className="flex items-center gap-2 mb-4">
        <BookOpen className="h-5 w-5 text-emerald-400" />
        <span className="text-emerald-400 font-medium">Flashcard</span>
        {item.concept_name && (
          <span className="text-slate-500 text-sm">• {item.concept_name}</span>
        )}
      </div>

      <button
        onClick={() => setIsFlipped(!isFlipped)}
        className="flex-1 flex items-center justify-center"
      >
        <div className={`w-full max-w-md aspect-[3/2] rounded-2xl p-6 flex items-center justify-center transition-all duration-300 ${isFlipped
          ? "bg-emerald-500/20 border-2 border-emerald-500"
          : "bg-[#1A1A1C] border-2 border-[#27272A]"
          }`}>
          <p className="text-xl text-white text-center">
            {isFlipped ? content.back : content.front}
          </p>
        </div>
      </button>

      <p className="text-center text-slate-500 text-sm mt-4">
        Tap to {isFlipped ? "see question" : "reveal answer"}
      </p>
    </div>
  );
};

// Main Feed Tab Component
export default function FeedTab() {
  const {
    feedData,
    setFeedData,
    currentFeedIndex,
    setCurrentFeedIndex,
    isFeedLoading,
    setFeedLoading,
    userStats,
    setUserStats,
  } = useStore();

  const [startTime, setStartTime] = useState<number>(Date.now());

  useEffect(() => {
    loadFeed();
  }, []);

  useEffect(() => {
    setStartTime(Date.now());
  }, [currentFeedIndex]);

  const loadFeed = async () => {
    setFeedLoading(true);
    try {
      const data = await api.getFeed({ maxItems: 20 });
      setFeedData(data);
      setCurrentFeedIndex(0);
    } catch (error) {
      console.error("Failed to load feed:", error);
    } finally {
      setFeedLoading(false);
    }
  };

  const handleAnswer = async (correct: boolean) => {
    const currentItem = feedData?.items[currentFeedIndex];
    if (!currentItem?.concept_id) return;

    const responseTime = Date.now() - startTime;
    const difficulty: DifficultyLevel = correct ? "good" : "again";

    try {
      await api.recordReview(
        currentItem.concept_id,
        currentItem.item_type,
        difficulty,
        responseTime
      );

      // Refresh stats
      const stats = await api.getUserStats();
      setUserStats(stats);
    } catch (error) {
      console.error("Failed to record review:", error);
    }
  };

  const goNext = () => {
    if (feedData && currentFeedIndex < feedData.items.length - 1) {
      setCurrentFeedIndex(currentFeedIndex + 1);
    }
  };

  const goPrev = () => {
    if (currentFeedIndex > 0) {
      setCurrentFeedIndex(currentFeedIndex - 1);
    }
  };

  const renderFeedItem = (item: FeedItem) => {
    switch (item.item_type) {
      case "mcq":
        return <MCQCard item={item} onAnswer={handleAnswer} />;
      case "concept_showcase":
        return <ConceptShowcaseCard item={item} />;
      case "fill_blank":
        return <FillBlankCard item={item} onAnswer={handleAnswer} />;
      case "flashcard":
        return <FlashcardCard item={item} />;
      case "screenshot":
      case "infographic":
        return <ScreenshotCard item={item} />;
      case "mermaid_diagram":
        return <MermaidCard item={item} />;
      default:
        return <ConceptShowcaseCard item={item} />;
    }
  };

  if (isFeedLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <RefreshCw className="h-8 w-8 text-purple-500 animate-spin mx-auto mb-4" />
          <p className="text-slate-400">Loading your feed...</p>
        </div>
      </div>
    );
  }

  if (!feedData || feedData.items.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="text-center">
          <BookOpen className="h-12 w-12 text-slate-600 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">No items to review</h3>
          <p className="text-slate-400 mb-4">
            Add some notes to start building your knowledge graph!
          </p>
          <Button onClick={loadFeed} variant="outline">
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>
    );
  }

  const currentItem = feedData.items[currentFeedIndex];

  return (
    <div className="h-full flex flex-col recall-card">
      {/* Progress bar */}
      <div className="p-4 border-b border-[#27272A]">
        <div className="flex items-center justify-between text-sm mb-2">
          <span className="text-slate-400">
            Today&apos;s Progress
          </span>
          <span className="text-white font-medium">
            {feedData.completed_today}/{feedData.total_due_today}
          </span>
        </div>
        <div className="h-2 bg-[#27272A] rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all"
            style={{
              width: `${Math.min((feedData.completed_today / Math.max(feedData.total_due_today, 1)) * 100, 100)}%`,
            }}
          />
        </div>
      </div>

      {/* Current item */}
      <div className="flex-1 overflow-hidden">
        {renderFeedItem(currentItem)}
      </div>

      {/* Navigation */}
      <div className="p-4 border-t border-[#27272A] flex items-center justify-between">
        <Button
          variant="ghost"
          onClick={goPrev}
          disabled={currentFeedIndex === 0}
          className="text-slate-400"
        >
          <ChevronLeft className="h-5 w-5" />
        </Button>

        <div className="flex items-center gap-2">
          {feedData.items.slice(
            Math.max(0, currentFeedIndex - 2),
            Math.min(feedData.items.length, currentFeedIndex + 3)
          ).map((_, i) => {
            const actualIndex = Math.max(0, currentFeedIndex - 2) + i;
            return (
              <div
                key={actualIndex}
                className={`w-2 h-2 rounded-full transition-all ${actualIndex === currentFeedIndex
                  ? "w-6 bg-purple-500"
                  : "bg-[#27272A]"
                  }`}
              />
            );
          })}
        </div>

        <Button
          variant="ghost"
          onClick={goNext}
          disabled={currentFeedIndex === feedData.items.length - 1}
          className="text-slate-400"
        >
          <ChevronRight className="h-5 w-5" />
        </Button>
      </div>
    </div>
  );
}
