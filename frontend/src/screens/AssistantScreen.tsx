import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send, Search, BookOpen, Target,
  Map, Lightbulb, Link2, MoreVertical, X, Save,
  MessageSquare, Trash2, History, BookmarkPlus,
  Cpu, Activity
} from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import { useAuthStore } from '../store/useAuthStore';
import type { ChatMessage } from '../types';
import { api } from '../services/api';

/**
 * Extract topic from "quiz me on X" style messages.
 * Returns the topic string or null if not a quiz request.
 */
function extractQuizTopic(message: string): string | null {
  if (message.startsWith('@quiz ')) return message.replace('@quiz ', '').trim();

  const patterns = [
    /quiz\s+me\s+on\s+(.+)/i,
    /test\s+me\s+on\s+(.+)/i,
    /review\s+(.+)/i,
    /practice\s+(.+)/i,
  ];
  for (const pattern of patterns) {
    const match = message.match(pattern);
    if (match) return match[1].trim();
  }
  return null;
}

const quickActions = [
  { id: 'search', tag: '@search ', icon: Search, label: 'Search Notes', color: '#B6FF2E' },
  { id: 'summarize', tag: '@summary ', icon: BookOpen, label: 'Summarize', color: '#2EFFE6' },
  { id: 'quiz', tag: '@quiz ', icon: Target, label: 'Quiz Me', color: '#FF6B6B' },
  { id: 'path', tag: '@path ', icon: Map, label: 'Learning Path', color: '#9B59B6' },
  { id: 'explain', tag: '@eli5 ', icon: Lightbulb, label: 'ELI5', color: '#F59E0B' },
  { id: 'connect', tag: '@connect ', icon: Link2, label: 'Connect', color: '#EC4899' },
];

interface ChatConversation {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

const expandTags = (text: string): string => {
  if (text.startsWith('@search ')) return `Search my knowledge graph for: ${text.replace('@search ', '')}. Prioritize my notes.`;
  if (text.startsWith('@summary ')) return `Provide a comprehensive summary of '${text.replace('@summary ', '')}' based on my notes.`;
  if (text.startsWith('@quiz ')) return `Generate a quiz to test my knowledge on: ${text.replace('@quiz ', '')}`;
  if (text.startsWith('@path ')) return `Create a structured learning path for '${text.replace('@path ', '')}', starting from basics.`;
  if (text.startsWith('@eli5 ')) return `Explain '${text.replace('@eli5 ', '')}' in simple terms (ELI5). Use analogies.`;
  if (text.startsWith('@connect ')) return `Analyze how '${text.replace('@connect ', '')}' connects to other concepts in my graph.`;
  return text;
};

export function AssistantScreen() {
  const {
    chatMessages,
    addChatMessage,
    clearChatMessages,
    navigateToFeedWithTopic,
    quizOnTopic,
    fetchNotes,
    fetchConcepts,
  } = useAppStore();
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [knowledgeStatus, setKnowledgeStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatConversation[]>([]);
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveTopic, setSaveTopic] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [swipingMessageId, setSwipingMessageId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Source-scoped filtering state
  const [selectedSources, setSelectedSources] = useState<{ id: string; title: string }[]>([]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

  // Swipe-right handler — triggers save modal when user drags an assistant message right
  const handleSwipeSave = (messageId: string) => {
    setSelectedMessageId(messageId);
    setShowSaveModal(true);
    setSwipingMessageId(null);
  };

  // Save message for quiz
  const handleSaveMessage = async () => {
    if (!selectedMessageId) return;

    try {
      const msg = chatMessages.find(m => m.id === selectedMessageId);
      if (!msg?.serverId) {
        alert('This message is not yet saved on the server.');
        return;
      }
      await api.post(`/chat/messages/${msg.serverId}/save`, {
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
      await api.post(`/chat/conversations/${conversationId}/to-knowledge`, {});
      setShowMenu(false);
      setKnowledgeStatus({ type: 'success', message: 'Added to Knowledge Base' });
      fetchNotes();
      fetchConcepts(true);
      setTimeout(() => setKnowledgeStatus(null), 3000);
    } catch (error) {
      console.error('Failed to add to knowledge:', error);
      setKnowledgeStatus({ type: 'error', message: 'Failed to add to Knowledge Base' });
      setTimeout(() => setKnowledgeStatus(null), 3000);
    }
  };

  // Load chat history
  const loadChatHistory = async () => {
    try {
      const response = await api.get('/chat/history');
      setChatHistory(response.data.conversations || []);
      setShowHistory(true);
      setShowMenu(false);
    } catch (error) {
      console.error('Failed to load history:', error);
    }
  };

  const handleSelectConversation = async (convId: string) => {
    try {
      const response = await api.get(`/chat/conversations/${convId}`);
      const messages = response.data.messages || [];
      clearChatMessages();
      messages.forEach((m: any) => {
        let sources: string[] | undefined = undefined;
        if (m.sources_json) {
          try {
            const parsed = typeof m.sources_json === 'string' ? JSON.parse(m.sources_json) : m.sources_json;
            sources = parsed.map((s: any) => s.title || s.name || s);
          } catch {
            sources = undefined;
          }
        }
        addChatMessage({
          id: m.id,
          role: m.role,
          content: m.content,
          sources,
          serverId: m.id,
        });
      });
      setConversationId(convId);
      setShowHistory(false);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  // Clear conversation
  const handleClearConversation = () => {
    clearChatMessages();
    setConversationId(null);
    setShowMenu(false);
  };

  const ensureConversation = async () => {
    if (conversationId) return conversationId;
    const response = await api.post('/chat/conversations');
    const newId = response.data.conversation_id || response.data.id;
    setConversationId(newId);
    return newId;
  };

  // Send message with streaming
  const handleSend = async (overrideMessage?: string) => {
    const rawInput = (overrideMessage ?? inputValue).trim();
    if (!rawInput) return;

    // Expand tags
    const messageText = expandTags(rawInput);
    const quizTopic = extractQuizTopic(rawInput); // Check raw input for @quiz tag

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: rawInput, // Show what user typed (with tag) or full text? Usually show expanded for clarity or raw for style. Let's show raw to keep "tag" feel.
    };

    addChatMessage(userMessage);
    setInputValue('');
    setIsTyping(true);

    // If it's a quiz request, start streaming quiz generation after chat response begins
    // The quizOnTopic will update the assistant message status with progress
    if (quizTopic) {
      // Wait for the chat SSE stream to finish, then start quiz generation
      // We schedule it to run after the chat response completes
      const startQuizGeneration = () => {
        quizOnTopic(quizTopic);
      };
      // Use a microtask-style delay so the chat message appears first
      setTimeout(startQuizGeneration, 500);
    }

    // Initial placeholder for assistant message
    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      status: 'Initialising...',
    };
    addChatMessage(assistantMessage);

    const token = useAuthStore.getState().idToken;
    const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

    try {
      const activeConversationId = await ensureConversation();
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          message: messageText, // Send expanded text
          user_id: '00000000-0000-0000-0000-000000000001',
          conversation_id: activeConversationId,
          source_ids: selectedSources.length > 0 ? selectedSources.map(s => s.id) : undefined,
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
                  const updatedMsg = { ...assistantMessage, content: fullContent, status: currentStatus };
                  addChatMessage(updatedMsg);
                } else if (data.type === 'chunk') {
                  fullContent += data.content;
                  const updatedMsg = { ...assistantMessage, content: fullContent, status: currentStatus };
                  addChatMessage(updatedMsg);
                } else if (data.type === 'done') {
                  // Backend sends objects: {id, title} for sources, {id, name} for concepts
                  // Extract string values for display, but keep IDs for source-scoped chat
                  const mappedSources = (data.sources || []).map((s: any) =>
                    typeof s === 'string' ? s : s.title || s.name || String(s)
                  );
                  const mappedConcepts = (data.related_concepts || []).map((c: any) =>
                    typeof c === 'string' ? c : c.name || c.title || String(c)
                  );
                  // Keep raw source objects for source-scoped filtering
                  const rawSources = (data.sources || []).map((s: any) =>
                    typeof s === 'string' ? { id: s, title: s } : { id: s.id || s.title, title: s.title || s.name || String(s) }
                  );
                  const finalMsg: ChatMessage = {
                    ...assistantMessage,
                    content: fullContent,
                    status: undefined, // Clear status when done
                    sources: mappedSources,
                    relatedConcepts: mappedConcepts,
                    serverId: data.message_id,
                    sourceObjects: rawSources,
                  };
                  addChatMessage(finalMsg);
                  if (data.conversation_id) {
                    setConversationId(data.conversation_id);
                  }
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

    setInputValue(action.tag);
    inputRef.current?.focus();
  };

  const showQuickActions = chatMessages.length <= 1;

  // Custom renderer for ReactMarkdown
  const MarkdownComponents = {
    p: ({ children }: any) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
    ul: ({ children }: any) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
    ol: ({ children }: any) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
    li: ({ children }: any) => <li>{children}</li>,
    h1: ({ children }: any) => <h1 className="text-xl font-bold mb-2 mt-4">{children}</h1>,
    h2: ({ children }: any) => <h2 className="text-lg font-bold mb-2 mt-3">{children}</h2>,
    h3: ({ children }: any) => <h3 className="text-md font-bold mb-1 mt-2">{children}</h3>,
    code: ({ inline, children }: any) => {
      if (inline) {
        return <code className="bg-white/10 rounded px-1 py-0.5 text-xs font-mono">{children}</code>;
      }
      return (
        <pre className="bg-[#1a1a1f] p-3 rounded-lg overflow-x-auto mb-2 border border-white/10">
          <code className="text-xs font-mono text-white/80">{children}</code>
        </pre>
      );
    },
    strong: ({ children }: any) => <strong className="font-semibold text-[#B6FF2E]">{children}</strong>,
    a: ({ href, children }: any) => (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-[#2EFFE6] hover:underline">
        {children}
      </a>
    ),
  };

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col relative">
      {knowledgeStatus && (
        <div
          className={`absolute top-0 left-1/2 -translate-x-1/2 z-30 px-4 py-2 rounded-full text-xs font-medium ${knowledgeStatus.type === 'success'
            ? 'bg-[#B6FF2E]/20 text-[#B6FF2E] border border-[#B6FF2E]/30'
            : 'bg-red-500/20 text-red-300 border border-red-500/30'
            }`}
        >
          {knowledgeStatus.message}
        </div>
      )}
      <div className="absolute top-0 right-0 z-20 flex items-center gap-2">
        {conversationId && (
          <span className="text-xs text-white/40 font-mono hidden sm:block">
            {chatHistory.find(c => c.id === conversationId)?.title || 'Current Chat'}
          </span>
        )}
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
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="absolute right-0 top-10 bg-[#1a1a1f] border border-white/10 rounded-xl shadow-xl overflow-hidden min-w-[200px] origin-top-right z-50"
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
                      onClick={() => handleSelectConversation(conv.id)}
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
      <div className="flex-1 overflow-y-auto space-y-6 pr-2 mb-4 mt-2 p-1">
        {chatMessages.length === 0 && !showQuickActions && (
          <div className="h-full flex flex-col items-center justify-center opacity-30">
            <MessageSquare className="w-12 h-12 mb-2" />
            <p>Start a conversation</p>
          </div>
        )}

        {chatMessages.map((message: ChatMessage, index: number) => (
          <motion.div
            key={message.id}
            initial={index >= chatMessages.length - 2 ? { opacity: 0, y: 10 } : false}
            animate={{ opacity: 1, y: 0 }}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} relative overflow-visible group`}
          >
            {/* Swipe/Status Layer */}
            {message.role === 'assistant' && (
              <div className="absolute -left-12 top-0 bottom-0 flex items-center">
                <motion.div
                  animate={{
                    x: swipingMessageId === message.id ? 10 : 0,
                    opacity: swipingMessageId === message.id ? 1 : 0
                  }}
                  className="p-2 rounded-full bg-[#B6FF2E] text-black shadow-lg shadow-[#B6FF2E]/20"
                >
                  <Save className="w-4 h-4" />
                </motion.div>
              </div>
            )}

            <motion.div
              className={`
                max-w-[85%] rounded-2xl p-4 relative shadow-sm
                ${message.role === 'user'
                  ? 'bg-[#B6FF2E]/10 text-white ml-10 border border-[#B6FF2E]/20'
                  : 'bg-[#1a1a2e] text-white mr-10 border border-white/10'
                }
              `}
              // Enhanced drag gesture
              {...(message.role === 'assistant' && !message.status ? {
                drag: 'x',
                dragConstraints: { left: 0, right: 80 },
                dragElastic: 0.1,
                onDrag: (_: any, info: any) => {
                  if (info.offset.x > 40) {
                    setSwipingMessageId(message.id);
                  } else {
                    setSwipingMessageId(null);
                  }
                },
                onDragEnd: (_: any, info: any) => {
                  if (info.offset.x > 60) {
                    handleSwipeSave(message.id);
                  }
                  setSwipingMessageId(null);
                }
              } : {})}
              style={{ x: 0 }} // Reset x on drag end visually handled by dragConstraints roughly
            >
              {/* Swipe Hint */}
              {message.role === 'assistant' && !message.status && (
                <div className="absolute -right-6 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-30 transition-opacity">
                  <div className="w-1 h-8 rounded-full bg-white/20" />
                </div>
              )}

              {/* Status Header for Assistant */}
              {message.role === 'assistant' && message.status && (
                <div className="mb-3 flex items-center gap-2 text-xs font-mono text-[#B6FF2E]">
                  <Activity className="w-3 h-3 animate-pulse" />
                  <span className="opacity-80 uppercase tracking-wider">{message.status}</span>
                </div>
              )}

              {/* Content */}
              <div className="text-sm text-white/90">
                {message.role === 'user' ? (
                  <p className="whitespace-pre-wrap font-medium">{message.content}</p>
                ) : (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={MarkdownComponents}
                  >
                    {message.content}
                  </ReactMarkdown>
                )}
              </div>

              {/* Sources */}
              {message.sources && message.sources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-white/10">
                  <p className="text-xs text-white/50 mb-1">Sources</p>
                  <div className="flex flex-wrap gap-1">
                    {message.sources.map((source: string, j: number) => {
                      // Check if already selected
                      const isSelected = selectedSources.some(s => s.title === source);
                      // Use real ID from sourceObjects if available
                      const sourceObj = message.sourceObjects?.find(s => s.title === source);
                      return (
                        <button
                          key={j}
                          onClick={() => {
                            if (!isSelected) {
                              setSelectedSources(prev => [...prev, {
                                id: sourceObj?.id || source,
                                title: source,
                              }]);
                            }
                          }}
                          className={`px-2 py-0.5 rounded-full text-[10px] transition-colors cursor-pointer
                              ${isSelected
                              ? 'bg-[#22C55E]/20 text-[#22C55E] border border-[#22C55E]/30'
                              : 'bg-white/10 text-white/60 hover:bg-[#22C55E]/10 hover:text-[#22C55E]'}
                            `}
                          title={isSelected ? 'Already selected' : 'Click to focus chat on this source'}
                        >
                          {source}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Related Concepts */}
              {message.relatedConcepts && message.relatedConcepts.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {message.relatedConcepts.map((concept: string, j: number) => (
                    <button
                      key={j}
                      onClick={() => navigateToFeedWithTopic(concept)}
                      className="px-2.5 py-1 rounded-full text-[10px] bg-[#B6FF2E]/5 text-[#B6FF2E] border border-[#B6FF2E]/10 hover:bg-[#B6FF2E]/10 transition-colors"
                    >
                      {concept}
                    </button>
                  ))}
                </div>
              )}
            </motion.div>
          </motion.div>
        ))}

        {/* Typing Bubble */}
        {isTyping && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex justify-start px-4"
          >
            <div className="flex items-center gap-2 p-3 rounded-2xl bg-[#1a1a2e] border border-white/5">
              <Cpu className="w-3 h-3 text-[#B6FF2E] animate-pulse" />
              <span className="text-xs text-white/40">Processing...</span>
            </div>
          </motion.div>
        )}

        <div ref={messagesEndRef} className="h-4" />
      </div>

      {/* Quick Actions */}
      <AnimatePresence>
        {showQuickActions && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="mb-4 px-4"
          >
            <p className="text-[10px] text-white/30 uppercase tracking-wider mb-2 ml-1">Suggested Actions</p>
            <div className="grid grid-cols-2 gap-2">
              {quickActions.map((action, i: number) => (
                <motion.button
                  key={action.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  onClick={() => handleQuickAction(action.id)}
                  className="flex items-center gap-3 p-3 rounded-xl bg-gradient-to-br from-white/5 to-white/0 border border-white/10 hover:border-white/20 transition-all text-left group"
                >
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110"
                    style={{ backgroundColor: `${action.color}15`, color: action.color }}
                  >
                    <action.icon className="w-4 h-4" />
                  </div>
                  <div>
                    <span className="text-xs font-medium text-white/90 block">{action.label}</span>
                    <span className="text-[10px] text-white/40 font-mono">{action.tag}</span>
                  </div>
                </motion.button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Input Bar */}
      <div className="p-4 pt-0">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative"
        >
          <div className="flex flex-col gap-2 glass-surface rounded-2xl p-2 border border-white/10 focus-within:border-[#B6FF2E]/50 transition-colors bg-[#0a0a0f]">
            {/* Selected Sources Pills */}
            {selectedSources.length > 0 && (
              <div className="flex flex-wrap gap-1 px-1">
                {selectedSources.map((source) => (
                  <span
                    key={source.id}
                    className="group inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-[#22C55E]/20 text-[#22C55E] border border-[#22C55E]/30"
                  >
                    <span className="max-w-[100px] truncate">{source.title}</span>
                    <button
                      onClick={() => setSelectedSources(prev => prev.filter(s => s.id !== source.id))}
                      className="opacity-0 group-hover:opacity-100 transition-opacity hover:text-red-400"
                      title="Remove source"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
                <button
                  onClick={() => setSelectedSources([])}
                  className="px-2 py-0.5 rounded-full text-[10px] text-white/40 hover:text-white/60 transition-colors"
                >
                  Clear all
                </button>
              </div>
            )}

            {/* Input Row */}
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder={selectedSources.length > 0
                  ? `Ask about ${selectedSources.length} source${selectedSources.length > 1 ? 's' : ''}...`
                  : "Message assistant..."}
                className="flex-1 bg-transparent text-white text-sm placeholder:text-white/30 focus:outline-none px-2 font-medium"
              />

              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={() => handleSend()}
                disabled={!inputValue.trim()}
                className="w-10 h-10 rounded-full bg-[#B6FF2E] flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#c5ff4d] transition-colors text-black shadow-lg shadow-[#B6FF2E]/10"
              >
                <Send className="w-5 h-5" />
              </motion.button>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
