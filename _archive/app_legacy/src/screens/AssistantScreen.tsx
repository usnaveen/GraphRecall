import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Send, Paperclip, Mic, Search, BookOpen, Target, 
  Map, Lightbulb, Link2
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import type { ChatMessage } from '../types';

const quickActions = [
  { id: 'search', icon: Search, label: 'Search Notes', color: '#B6FF2E' },
  { id: 'summarize', icon: BookOpen, label: 'Summarize Topic', color: '#2EFFE6' },
  { id: 'quiz', icon: Target, label: 'Quiz Me', color: '#FF6B6B' },
  { id: 'path', icon: Map, label: 'Learning Path', color: '#9B59B6' },
  { id: 'explain', icon: Lightbulb, label: 'Explain Like I\'m 5', color: '#F59E0B' },
  { id: 'connect', icon: Link2, label: 'Find Connections', color: '#EC4899' },
];

export function AssistantScreen() {
  const { chatMessages, addChatMessage } = useAppStore();
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

  const handleSend = () => {
    if (!inputValue.trim()) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: inputValue,
    };

    addChatMessage(userMessage);
    setInputValue('');
    setIsTyping(true);

    // Simulate AI response
    setTimeout(() => {
      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'Based on your notes, I can help you understand this concept better. Would you like me to:\n\n1. Show you related concepts in your knowledge graph\n2. Quiz you on this topic\n3. Find the original notes where you learned this',
        sources: ['Deep Learning Notes - Chapter 4'],
        relatedConcepts: ['Neural Networks', 'Backpropagation', 'Gradient Descent'],
      };
      addChatMessage(assistantMessage);
      setIsTyping(false);
    }, 1500);
  };

  const handleQuickAction = (actionId: string) => {
    const action = quickActions.find(a => a.id === actionId);
    if (!action) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: `Help me ${action.label.toLowerCase()}`,
    };

    addChatMessage(userMessage);
    setIsTyping(true);

    setTimeout(() => {
      const responses: Record<string, string> = {
        search: 'I found 3 notes related to your query:\n\n• "Deep Learning Notes - Chapter 3"\n• "ML Interview Prep"\n• "Neural Network Fundamentals"',
        summarize: 'Here\'s a summary of Neural Networks:\n\nNeural networks are computing systems inspired by biological neurons. They consist of layers (input, hidden, output) and learn through backpropagation.',
        quiz: 'Let\'s test your knowledge! Here\'s a quick question:\n\nWhat algorithm is used to update weights in a neural network?\n\nA) K-Means\nB) Backpropagation\nC) Random Forest',
        path: 'To master LSTM, I recommend this learning path:\n\n1. Neural Networks (70% mastery)\n2. RNN (45% mastery)\n3. Gradient Descent (75% mastery)\n4. LSTM (your goal)',
        explain: 'Imagine a neural network like a team of workers:\n\n• Each worker (neuron) does a small task\n• They pass information to each other\n• The team learns from mistakes and gets better',
        connect: 'Neural Networks are connected to:\n\n• CNN (for images)\n• RNN (for sequences)\n• Backpropagation (learning)\n• Gradient Descent (optimization)',
      };

      const assistantMessage: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: responses[actionId] || 'I\'ll help you with that!',
        relatedConcepts: ['Neural Networks', 'Machine Learning'],
      };
      addChatMessage(assistantMessage);
      setIsTyping(false);
    }, 1200);
  };

  const showQuickActions = chatMessages.length <= 1;

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1 mb-4">
        {chatMessages.map((message: ChatMessage, i: number) => (
          <motion.div
            key={message.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i === chatMessages.length - 1 ? 0 : 0 }}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`
                max-w-[85%] rounded-2xl p-4
                ${message.role === 'user'
                  ? 'bg-[#B6FF2E]/20 text-white ml-8'
                  : 'bg-white/5 text-white mr-8 border-l-2 border-[#B6FF2E]/50'
                }
              `}
            >
              {/* Content */}
              <div className="text-sm whitespace-pre-line leading-relaxed">
                {message.content}
              </div>

              {/* Sources */}
              {message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-white/10">
                  <p className="text-xs text-white/50 mb-1">Sources</p>
                  <div className="flex flex-wrap gap-1">
                    {message.sources.map((source: string, j: number) => (
                      <span
                        key={j}
                        className="px-2 py-0.5 rounded-full text-[10px] bg-white/10 text-white/60"
                      >
                        {source}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Related Concepts */}
              {message.relatedConcepts && message.relatedConcepts.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {message.relatedConcepts.map((concept: string, j: number) => (
                    <button
                      key={j}
                      className="px-2 py-0.5 rounded-full text-[10px] bg-[#B6FF2E]/10 text-[#B6FF2E] hover:bg-[#B6FF2E]/20 transition-colors"
                    >
                      {concept}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        ))}

        {/* Typing Indicator */}
        {isTyping && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex justify-start"
          >
            <div className="bg-white/5 rounded-2xl p-4 mr-8 border-l-2 border-[#B6FF2E]/30">
              <div className="flex gap-1">
                <motion.div
                  animate={{ y: [0, -4, 0] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: 0 }}
                  className="w-2 h-2 rounded-full bg-white/40"
                />
                <motion.div
                  animate={{ y: [0, -4, 0] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: 0.15 }}
                  className="w-2 h-2 rounded-full bg-white/40"
                />
                <motion.div
                  animate={{ y: [0, -4, 0] }}
                  transition={{ duration: 0.5, repeat: Infinity, delay: 0.3 }}
                  className="w-2 h-2 rounded-full bg-white/40"
                />
              </div>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Quick Actions */}
      <AnimatePresence>
        {showQuickActions && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="mb-4"
          >
            <p className="text-xs text-white/40 mb-3">Quick Actions</p>
            <div className="grid grid-cols-2 gap-2">
              {quickActions.map((action, i: number) => (
                <motion.button
                  key={action.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  onClick={() => handleQuickAction(action.id)}
                  className="flex items-center gap-2 p-3 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-all text-left"
                >
                  <div 
                    className="w-8 h-8 rounded-lg flex items-center justify-center"
                    style={{ backgroundColor: `${action.color}20` }}
                  >
                    <action.icon className="w-4 h-4" style={{ color: action.color }} />
                  </div>
                  <span className="text-xs text-white/80">{action.label}</span>
                </motion.button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input Bar */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative"
      >
        <div className="flex items-center gap-2 glass-surface rounded-full px-2 py-2">
          <button className="w-9 h-9 rounded-full bg-white/5 flex items-center justify-center hover:bg-white/10 transition-colors">
            <Paperclip className="w-4 h-4 text-white/50" />
          </button>
          
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Ask anything about your knowledge..."
            className="flex-1 bg-transparent text-white text-sm placeholder:text-white/40 focus:outline-none"
          />
          
          <button className="w-9 h-9 rounded-full bg-white/5 flex items-center justify-center hover:bg-white/10 transition-colors">
            <Mic className="w-4 h-4 text-white/50" />
          </button>
          
          <motion.button
            whileTap={{ scale: 0.95 }}
            onClick={handleSend}
            disabled={!inputValue.trim()}
            className="w-9 h-9 rounded-full bg-[#B6FF2E] flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#c5ff4d] transition-colors"
          >
            <Send className="w-4 h-4 text-[#07070A]" />
          </motion.button>
        </div>
      </motion.div>
    </div>
  );
}
