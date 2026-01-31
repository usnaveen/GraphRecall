import { useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, Filter, ChevronDown, X, Target, BookOpen, Link2,
  ZoomIn, ZoomOut, RotateCw, Play, Loader2, Check, XCircle
} from 'lucide-react';
import { mockGraphNodes, mockGraphEdges } from '../data/mockData';
import type { GraphNode, GraphEdge } from '../types';
import { api } from '../services/api';

interface QuizQuestion {
  question: string;
  options: string[];
  correct_answer: string;
  explanation: string;
}

export function GraphScreen() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  // Quiz state
  const [showQuiz, setShowQuiz] = useState(false);
  const [quizLoading, setQuizLoading] = useState(false);
  const [quizQuestions, setQuizQuestions] = useState<QuizQuestion[]>([]);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState<string | null>(null);
  const [showAnswer, setShowAnswer] = useState(false);
  const [quizScore, setQuizScore] = useState(0);
  const [quizTopic, setQuizTopic] = useState('');
  const [quizResearched, setQuizResearched] = useState(false);

  const filteredNodes = searchQuery
    ? (mockGraphNodes as GraphNode[]).filter((n: GraphNode) => n.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : mockGraphNodes;

  const selectedNodeData = (mockGraphNodes as GraphNode[]).find((n: GraphNode) => n.id === selectedNode);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.target === containerRef.current) {
      setIsDragging(true);
      dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.current.x,
        y: e.clientY - dragStart.current.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleZoomIn = () => setZoom(z => Math.min(z * 1.2, 3));
  const handleZoomOut = () => setZoom(z => Math.max(z / 1.2, 0.5));
  const handleReset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  // Quiz functions
  const handleQuizMe = async (topicName: string) => {
    setQuizLoading(true);
    setQuizTopic(topicName);
    setShowQuiz(true);
    setCurrentQuestionIndex(0);
    setQuizScore(0);
    setSelectedAnswer(null);
    setShowAnswer(false);

    try {
      const response = await api.post(`/api/feed/quiz/topic/${encodeURIComponent(topicName)}`, {
        num_questions: 5,
        force_research: false,
      });

      setQuizQuestions(response.data.questions || []);
      setQuizResearched(response.data.researched || false);
    } catch (error) {
      console.error('Failed to generate quiz:', error);
      setQuizQuestions([]);
    } finally {
      setQuizLoading(false);
    }
  };

  const handleAnswerSelect = (answer: string) => {
    if (showAnswer) return;
    setSelectedAnswer(answer);
    setShowAnswer(true);

    const currentQuestion = quizQuestions[currentQuestionIndex];
    if (answer === currentQuestion.correct_answer) {
      setQuizScore(prev => prev + 1);
    }
  };

  const handleNextQuestion = () => {
    if (currentQuestionIndex < quizQuestions.length - 1) {
      setCurrentQuestionIndex(prev => prev + 1);
      setSelectedAnswer(null);
      setShowAnswer(false);
    }
  };

  const handleCloseQuiz = () => {
    setShowQuiz(false);
    setQuizQuestions([]);
    setCurrentQuestionIndex(0);
    setQuizScore(0);
  };

  const currentQuestion = quizQuestions[currentQuestionIndex];

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* Search Bar */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative mb-4"
      >
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search concepts to quiz..."
          className="w-full pl-10 pr-4 py-3 rounded-full glass-surface text-white placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50"
        />
        {/* Quick Quiz button appears when searching */}
        {searchQuery.trim() && (
          <button
            onClick={() => handleQuizMe(searchQuery)}
            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 px-3 py-1.5 bg-[#B6FF2E] text-black rounded-full text-xs font-medium hover:bg-[#c5ff4d] transition-colors"
          >
            <Target className="w-3 h-3" />
            Quiz Me
          </button>
        )}
      </motion.div>

      {/* Graph Canvas */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1 }}
        className="flex-1 rounded-3xl overflow-hidden border border-white/10 relative bg-[#0a0a0f]"
        style={{ minHeight: '300px' }}
        ref={containerRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* Grid Background */}
        <div
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage: `
              linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)
            `,
            backgroundSize: '40px 40px',
          }}
        />

        {/* Graph Content */}
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: 'center center',
            transition: isDragging ? 'none' : 'transform 0.3s ease-out',
          }}
        >
          <svg width="600" height="400" className="overflow-visible">
            {/* Edges */}
            {mockGraphEdges.map((edge: GraphEdge, i: number) => {
              const source = (mockGraphNodes as GraphNode[]).find((n: GraphNode) => n.id === edge.source);
              const target = (mockGraphNodes as GraphNode[]).find((n: GraphNode) => n.id === edge.target);
              if (!source || !target) return null;

              const sx = 300 + source.x * 30;
              const sy = 200 + source.y * 25;
              const tx = 300 + target.x * 30;
              const ty = 200 + target.y * 25;

              return (
                <line
                  key={i}
                  x1={sx}
                  y1={sy}
                  x2={tx}
                  y2={ty}
                  stroke="rgba(255,255,255,0.15)"
                  strokeWidth={1 + edge.strength}
                />
              );
            })}

            {/* Nodes */}
            {filteredNodes.map((node: GraphNode) => {
              const x = 300 + node.x * 30;
              const y = 200 + node.y * 25;
              const isSelected = selectedNode === node.id;

              return (
                <g
                  key={node.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedNode(node.id);
                  }}
                  className="cursor-pointer"
                >
                  {/* Glow */}
                  {(isSelected) && (
                    <circle
                      cx={x}
                      cy={y}
                      r={node.size * 25}
                      fill={node.color}
                      opacity={0.2}
                    />
                  )}

                  {/* Node Circle */}
                  <circle
                    cx={x}
                    cy={y}
                    r={node.size * 15}
                    fill={node.color}
                    stroke={isSelected ? '#fff' : 'transparent'}
                    strokeWidth={2}
                    opacity={0.7 + (node.mastery / 200)}
                  />

                  {/* Label */}
                  <text
                    x={x}
                    y={y + node.size * 25}
                    textAnchor="middle"
                    fill={isSelected ? '#B6FF2E' : 'rgba(255,255,255,0.7)'}
                    fontSize={12}
                    fontWeight={isSelected ? 600 : 400}
                  >
                    {node.name}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        {/* Controls */}
        <div className="absolute bottom-4 right-4 flex flex-col gap-2">
          <button
            onClick={handleZoomIn}
            className="w-10 h-10 rounded-full glass-surface flex items-center justify-center hover:bg-white/10 transition-colors"
          >
            <ZoomIn className="w-4 h-4 text-white/70" />
          </button>
          <button
            onClick={handleZoomOut}
            className="w-10 h-10 rounded-full glass-surface flex items-center justify-center hover:bg-white/10 transition-colors"
          >
            <ZoomOut className="w-4 h-4 text-white/70" />
          </button>
          <button
            onClick={handleReset}
            className="w-10 h-10 rounded-full glass-surface flex items-center justify-center hover:bg-white/10 transition-colors"
          >
            <RotateCw className="w-4 h-4 text-white/70" />
          </button>
        </div>

        {/* Instructions */}
        <div className="absolute bottom-4 left-4 glass-surface rounded-xl px-3 py-2">
          <p className="text-xs text-white/60">
            Drag to pan • Click nodes to focus • Use controls to zoom
          </p>
        </div>
      </motion.div>

      {/* Filters */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-4"
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-white/50">
            Viewing: {filteredNodes.length} concepts
          </span>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-1 text-xs text-[#B6FF2E] hover:text-[#c5ff4d] transition-colors"
          >
            <Filter className="w-3 h-3" />
            Filters
            <ChevronDown className={`w-3 h-3 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="flex gap-2"
          >
            {['Domain', 'Mastery', 'Complexity'].map((filter) => (
              <button
                key={filter}
                className="px-3 py-1.5 rounded-full text-xs bg-white/5 text-white/70 border border-white/10 hover:bg-white/10 transition-colors"
              >
                {filter}
              </button>
            ))}
          </motion.div>
        )}
      </motion.div>

      {/* Selected Node Panel */}
      {selectedNodeData && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 glass-surface rounded-2xl p-4"
        >
          <div className="flex items-start justify-between mb-3">
            <div>
              <h3 className="font-heading font-bold text-white">{selectedNodeData.name}</h3>
              <p className="text-xs text-white/50 mt-1">
                Mastery: {selectedNodeData.mastery}%
              </p>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="p-1 rounded-full hover:bg-white/10 transition-colors"
            >
              <X className="w-4 h-4 text-white/50" />
            </button>
          </div>

          <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mb-3">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${selectedNodeData.mastery}%`,
                backgroundColor: selectedNodeData.color
              }}
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => handleQuizMe(selectedNodeData.name)}
              className="flex-1 py-2 rounded-xl bg-[#B6FF2E]/20 text-[#B6FF2E] text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-[#B6FF2E]/30 transition-colors"
            >
              <Target className="w-3 h-3" />
              Quiz Me
            </button>
            <button className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-white/10 transition-colors">
              <BookOpen className="w-3 h-3" />
              Notes
            </button>
            <button className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-white/10 transition-colors">
              <Link2 className="w-3 h-3" />
              Links
            </button>
          </div>
        </motion.div>
      )}

      {/* Quiz Modal */}
      <AnimatePresence>
        {showQuiz && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-[#0a0a0f] border border-white/10 rounded-3xl w-full max-w-md max-h-[80vh] overflow-hidden"
            >
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-white/10">
                <div>
                  <h3 className="text-lg font-semibold text-white">Quiz: {quizTopic}</h3>
                  {quizResearched && (
                    <p className="text-xs text-[#B6FF2E] mt-0.5">✨ Researched from web</p>
                  )}
                </div>
                <button onClick={handleCloseQuiz}>
                  <X className="w-5 h-5 text-white/60" />
                </button>
              </div>

              {/* Content */}
              <div className="p-6">
                {quizLoading ? (
                  <div className="flex flex-col items-center justify-center py-12">
                    <Loader2 className="w-8 h-8 text-[#B6FF2E] animate-spin" />
                    <p className="text-white/60 mt-4">Generating quiz...</p>
                    <p className="text-xs text-white/40 mt-1">Searching your knowledge graph</p>
                  </div>
                ) : quizQuestions.length === 0 ? (
                  <div className="text-center py-12">
                    <XCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
                    <p className="text-white/80">No quiz questions generated</p>
                    <p className="text-xs text-white/50 mt-1">Try adding more content about this topic</p>
                  </div>
                ) : currentQuestionIndex >= quizQuestions.length ? (
                  <div className="text-center py-12">
                    <div className="w-16 h-16 rounded-full bg-[#B6FF2E]/20 flex items-center justify-center mx-auto mb-4">
                      <Check className="w-8 h-8 text-[#B6FF2E]" />
                    </div>
                    <h4 className="text-xl font-bold text-white">Quiz Complete!</h4>
                    <p className="text-white/60 mt-2">
                      Score: {quizScore}/{quizQuestions.length}
                    </p>
                    <button
                      onClick={handleCloseQuiz}
                      className="mt-6 px-6 py-3 bg-[#B6FF2E] text-black rounded-xl font-medium hover:bg-[#c5ff4d] transition-colors"
                    >
                      Close
                    </button>
                  </div>
                ) : currentQuestion && (
                  <>
                    {/* Progress */}
                    <div className="flex items-center justify-between mb-4">
                      <span className="text-xs text-white/50">
                        Question {currentQuestionIndex + 1}/{quizQuestions.length}
                      </span>
                      <span className="text-xs text-[#B6FF2E]">
                        Score: {quizScore}
                      </span>
                    </div>

                    <div className="w-full h-1 bg-white/10 rounded-full mb-6">
                      <div
                        className="h-full bg-[#B6FF2E] rounded-full transition-all"
                        style={{ width: `${((currentQuestionIndex + 1) / quizQuestions.length) * 100}%` }}
                      />
                    </div>

                    {/* Question */}
                    <p className="text-white font-medium mb-6 leading-relaxed">
                      {currentQuestion.question}
                    </p>

                    {/* Options */}
                    <div className="space-y-3">
                      {currentQuestion.options.map((option, i) => {
                        const isCorrect = option === currentQuestion.correct_answer;
                        const isSelected = option === selectedAnswer;

                        let bgColor = 'bg-white/5';
                        let borderColor = 'border-white/10';
                        let textColor = 'text-white/80';

                        if (showAnswer) {
                          if (isCorrect) {
                            bgColor = 'bg-green-500/20';
                            borderColor = 'border-green-500';
                            textColor = 'text-green-400';
                          } else if (isSelected && !isCorrect) {
                            bgColor = 'bg-red-500/20';
                            borderColor = 'border-red-500';
                            textColor = 'text-red-400';
                          }
                        } else if (isSelected) {
                          bgColor = 'bg-[#B6FF2E]/20';
                          borderColor = 'border-[#B6FF2E]';
                        }

                        return (
                          <button
                            key={i}
                            onClick={() => handleAnswerSelect(option)}
                            disabled={showAnswer}
                            className={`w-full p-4 rounded-xl ${bgColor} border ${borderColor} ${textColor} text-left text-sm transition-all hover:bg-white/10 disabled:cursor-default`}
                          >
                            {option}
                          </button>
                        );
                      })}
                    </div>

                    {/* Explanation */}
                    {showAnswer && currentQuestion.explanation && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="mt-4 p-4 rounded-xl bg-white/5 border border-white/10"
                      >
                        <p className="text-xs text-white/50 mb-1">Explanation</p>
                        <p className="text-sm text-white/80">{currentQuestion.explanation}</p>
                      </motion.div>
                    )}

                    {/* Next Button */}
                    {showAnswer && (
                      <motion.button
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        onClick={handleNextQuestion}
                        className="w-full mt-6 py-3 bg-[#B6FF2E] text-black rounded-xl font-medium hover:bg-[#c5ff4d] transition-colors flex items-center justify-center gap-2"
                      >
                        {currentQuestionIndex < quizQuestions.length - 1 ? (
                          <>
                            Next Question
                            <Play className="w-4 h-4" />
                          </>
                        ) : (
                          'View Results'
                        )}
                      </motion.button>
                    )}
                  </>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
