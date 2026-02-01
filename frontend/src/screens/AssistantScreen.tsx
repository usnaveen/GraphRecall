import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Paperclip, Mic, Search, BookOpen, Target,
  Map, Lightbulb, Link2, MoreVertical, X, Save,
  MessageSquare, Trash2, History, BookmarkPlus
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useAuthStore } from '../store/useAuthStore';
import type { ChatMessage } from '../types';
import { api } from '../services/api';

const quickActions = [
  { id: 'search', icon: Search, label: 'Search Notes', color: '#B6FF2E' },
  { id: 'summarize', icon: BookOpen, label: 'Summarize Topic', color: '#2EFFE6' },
  { id: 'quiz', icon: Target, label: 'Quiz Me', color: '#FF6B6B' },
  { id: 'path', icon: Map, label: 'Learning Path', color: '#9B59B6' },
  { id: 'explain', icon: Lightbulb, label: 'Explain Like I\'m 5', color: '#F59E0B' },
  { id: 'connect', icon: Link2, label: 'Find Connections', color: '#EC4899' },
];

interface ChatConversation {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export function AssistantScreen() {
  const { chatMessages, addChatMessage, clearChatMessages } = useAppStore();
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatConversation[]>([]);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveTopic, setSaveTopic] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

  // Long press handlers for saving messages
  const handleMessageTouchStart = (messageId: string) => {
    longPressTimer.current = setTimeout(() => {
      setSelectedMessageId(messageId);
      setShowSaveModal(true);
    }, 600); // 600ms long press
  };

  const handleMessageTouchEnd = () => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
    }
  };

  // Save message for quiz
  const handleSaveMessage = async () => {
    if (!selectedMessageId) return;

    try {
      await api.post(`/api/chat/messages/${selectedMessageId}/save`, {
        topic: saveTopic || undefined,
      });
      setShowSaveModal(false);
      setSelectedMessageId(null);
      setSaveTopic('');
    } catch (error) {
      console.error('Failed to save message:', error);
    }
  };

  // Add conversation to knowledge base
  const handleAddToKnowledge = async () => {
    if (!conversationId) return;

    try {
      await api.post(`/api/chat/conversations/${conversationId}/to-knowledge`, {});
      setShowMenu(false);
    } catch (error) {
      console.error('Failed to add to knowledge:', error);
    }
  };

  // Load chat history
  const loadChatHistory = async () => {
    try {
      const response = await api.get('/api/chat/history');
      setChatHistory(response.data.conversations || []);
      setShowHistory(true);
      setShowMenu(false);
    } catch (error) {
      console.error('Failed to load history:', error);
    }
  };

  // Clear conversation
  const handleClearConversation = () => {
    clearChatMessages();
    setConversationId(null);
    setShowMenu(false);
  };

  // Send message with streaming
  const handleSend = async () => {
    if (!inputValue.trim()) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: inputValue,
    };

    addChatMessage(userMessage);
    setInputValue('');
    setIsTyping(true);

    // Initial placeholder for assistant message
    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      status: 'Initialising...',
    };
    addChatMessage(assistantMessage);

    // Use auth token and correct API URL
    const token = useAuthStore.getState().idToken; // Access token directly from store
    const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

    try {
      // Use streaming endpoint
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          message: inputValue,
          user_id: '00000000-0000-0000-0000-000000000001',
        }),
      });

      if (!response.ok) {
        throw new Error('Stream failed');
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      let currentStatus = 'Thinking...';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));

                if (data.type === 'status') {
                  currentStatus = data.content;
                  // Update message status in store
                  const updatedMsg = { ...assistantMessage, content: fullContent, status: currentStatus };
                  addChatMessage(updatedMsg); // Store should handle update if ID matches, else we'd need an update method
                } else if (data.type === 'chunk') {
                  fullContent += data.content;
                  const updatedMsg = { ...assistantMessage, content: fullContent, status: currentStatus };
                  addChatMessage(updatedMsg);
                } else if (data.type === 'done') {
                  const finalMsg: ChatMessage = {
                    ...assistantMessage,
                    content: fullContent,
                    status: undefined,
                    sources: data.sources || [],
                    relatedConcepts: data.related_concepts || [],
                  };
                  addChatMessage(finalMsg);
                }
              } catch (e) {
                // Ignore parse errors
              }
            }
          }
        }
      }

    } catch (error) {
      console.error('Chat error:', error);
      const errorMessage: ChatMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
      };
      addChatMessage(errorMessage);
    } finally {
      setIsTyping(false);
    }
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
    setInputValue(`Help me ${action.label.toLowerCase()}`);
    handleSend();
  };

  const showQuickActions = chatMessages.length <= 1;

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col relative">
      {/* Three-dot Menu Button */}
      <div className="absolute top-0 right-0 z-20">
        <button
          onClick={() => setShowMenu(!showMenu)}
          className="p-2 rounded-full hover:bg-white/10 transition-colors"
        >
          <MoreVertical className="w-5 h-5 text-white/60" />
        </button>

        {/* Dropdown Menu */}
        <AnimatePresence>
          {showMenu && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="absolute right-0 top-10 bg-[#1a1a1f] border border-white/10 rounded-xl shadow-xl overflow-hidden min-w-[200px]"
            >
              <button
                onClick={handleAddToKnowledge}
                className="w-full flex items-center gap-3 px-4 py-3 text-sm text-white/80 hover:bg-white/5 transition-colors"
              >
                <BookmarkPlus className="w-4 h-4" />
                Add to Knowledge Base
              </button>
              <button
                onClick={loadChatHistory}
                className="w-full flex items-center gap-3 px-4 py-3 text-sm text-white/80 hover:bg-white/5 transition-colors"
              >
                <History className="w-4 h-4" />
                View Chat History
              </button>
              <button
                onClick={handleClearConversation}
                className="w-full flex items-center gap-3 px-4 py-3 text-sm text-red-400 hover:bg-white/5 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                Clear Conversation
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* History Modal */}
      <AnimatePresence>
        {showHistory && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/70 z-30 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-[#1a1a1f] border border-white/10 rounded-2xl w-full max-w-md max-h-[70vh] overflow-hidden"
            >
              <div className="flex items-center justify-between p-4 border-b border-white/10">
                <h3 className="text-lg font-semibold text-white">Chat History</h3>
                <button onClick={() => setShowHistory(false)}>
                  <X className="w-5 h-5 text-white/60" />
                </button>
              </div>
              <div className="overflow-y-auto max-h-[50vh] p-2">
                {chatHistory.length === 0 ? (
                  <p className="text-center text-white/50 py-8">No chat history</p>
                ) : (
                  chatHistory.map((conv) => (
                    <div
                      key={conv.id}
                      className="p-3 rounded-xl hover:bg-white/5 cursor-pointer transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <MessageSquare className="w-4 h-4 text-[#B6FF2E]" />
                        <span className="text-sm text-white font-medium">{conv.title}</span>
                      </div>
                      <p className="text-xs text-white/50 mt-1">
                        {conv.message_count} messages • {new Date(conv.updated_at).toLocaleDateString()}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Save for Quiz Modal */}
      <AnimatePresence>
        {showSaveModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/70 z-30 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-[#1a1a1f] border border-white/10 rounded-2xl w-full max-w-sm p-6"
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-[#B6FF2E]/20 flex items-center justify-center">
                  <Save className="w-5 h-5 text-[#B6FF2E]" />
                </div>
                <h3 className="text-lg font-semibold text-white">Save for Quiz</h3>
              </div>

              <p className="text-sm text-white/60 mb-4">
                This response will be saved and used to generate quiz questions.
              </p>

              <input
                type="text"
                value={saveTopic}
                onChange={(e) => setSaveTopic(e.target.value)}
                placeholder="Topic name (optional)"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50 mb-4"
              />

              <div className="flex gap-3">
                <button
                  onClick={() => setShowSaveModal(false)}
                  className="flex-1 py-3 rounded-xl bg-white/5 text-white/80 text-sm hover:bg-white/10 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveMessage}
                  className="flex-1 py-3 rounded-xl bg-[#B6FF2E] text-black text-sm font-medium hover:bg-[#c5ff4d] transition-colors"
                >
                  Save
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 pr-1 mb-4 mt-10">
        {chatMessages.map((message: ChatMessage, i: number) => (
          <motion.div
            key={message.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i === chatMessages.length - 1 ? 0 : 0 }}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            onTouchStart={() => message.role === 'assistant' && handleMessageTouchStart(message.id)}
            onTouchEnd={handleMessageTouchEnd}
            onMouseDown={() => message.role === 'assistant' && handleMessageTouchStart(message.id)}
            onMouseUp={handleMessageTouchEnd}
            onMouseLeave={handleMessageTouchEnd}
          >
            <div
              className={`
                max-w-[85%] rounded-2xl p-4 relative
                ${message.role === 'user'
                  ? 'bg-[#B6FF2E]/20 text-white ml-8'
                  : 'bg-white/5 text-white mr-8 border-l-2 border-[#B6FF2E]/50'
                }
              `}
            >
              {/* Long press hint for assistant messages */}
              {message.role === 'assistant' && (
                <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100">
                  <Save className="w-3 h-3 text-white/30" />
                </div>
              )}

              {/* Content */}
              <div className="text-sm whitespace-pre-line leading-relaxed">
                {message.content}
                {message.status && (
                  <div className="mt-2 flex items-center gap-2 text-[10px] text-[#B6FF2E]/60 italic animate-pulse">
                    <motion.div
                      animate={{ rotate: 360 }}
                      transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                      className="w-2 h-2 border-t border-[#B6FF2E] rounded-full"
                    />
                    {message.status}
                  </div>
                )}
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
