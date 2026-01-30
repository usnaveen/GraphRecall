"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  Send,
  Loader2,
  BookOpen,
  Network,
  Sparkles,
  MessageCircle,
  ChevronRight,
  User,
  Bot,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStore } from "@/lib/store";
import api, { ChatMessage, ChatResponse } from "@/lib/api";

export default function ChatTab() {
  const {
    chatMessages,
    addChatMessage,
    clearChatMessages,
    isChatLoading,
    setChatLoading,
    chatSuggestions,
    setChatSuggestions,
    setActiveTab,
    setSelectedConcept,
  } = useStore();

  const [input, setInput] = useState("");
  const [lastResponse, setLastResponse] = useState<ChatResponse | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages]);

  useEffect(() => {
    if (chatSuggestions.length === 0) {
      loadSuggestions();
    }
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const loadSuggestions = async () => {
    try {
      const { suggestions } = await api.getChatSuggestions();
      setChatSuggestions(suggestions);
    } catch (error) {
      console.error("Failed to load suggestions:", error);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isChatLoading) return;

    const userMessage: ChatMessage = {
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };

    addChatMessage(userMessage);
    setInput("");
    setChatLoading(true);

    try {
      const response = await api.chat(
        userMessage.content,
        chatMessages.map((m) => ({ role: m.role, content: m.content }))
      );

      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: response.response,
        timestamp: new Date().toISOString(),
      };

      addChatMessage(assistantMessage);
      setLastResponse(response);
    } catch (error) {
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again.",
        timestamp: new Date().toISOString(),
      };
      addChatMessage(errorMessage);
    } finally {
      setChatLoading(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setInput(suggestion);
  };

  const handleConceptClick = (conceptId: string, conceptName: string) => {
    setSelectedConcept({
      id: conceptId,
      name: conceptName,
      definition: "",
      domain: "",
      complexity_score: 5,
    });
    setActiveTab("graph");
  };

  const renderMessage = (message: ChatMessage, index: number) => {
    const isUser = message.role === "user";

    return (
      <div
        key={index}
        className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}
      >
        <div
          className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
            isUser ? "bg-purple-500" : "bg-[#27272A]"
          }`}
        >
          {isUser ? (
            <User className="h-4 w-4 text-white" />
          ) : (
            <Bot className="h-4 w-4 text-purple-400" />
          )}
        </div>
        <div
          className={`max-w-[80%] p-4 rounded-2xl ${
            isUser
              ? "bg-purple-500 text-white rounded-br-md"
              : "bg-[#1A1A1C] text-slate-300 rounded-bl-md"
          }`}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>
          {message.timestamp && (
            <p
              className={`text-xs mt-2 ${
                isUser ? "text-purple-200" : "text-slate-500"
              }`}
            >
              {new Date(message.timestamp).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full flex flex-col">
      {/* Chat header */}
      <div className="p-4 border-b border-[#27272A]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-purple-500/20 rounded-full flex items-center justify-center">
            <Sparkles className="h-5 w-5 text-purple-400" />
          </div>
          <div>
            <h2 className="font-semibold text-white">GraphRecall Assistant</h2>
            <p className="text-xs text-slate-500">
              Powered by your knowledge graph
            </p>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.length === 0 ? (
          // Empty state with suggestions
          <div className="h-full flex flex-col items-center justify-center">
            <MessageCircle className="h-12 w-12 text-slate-600 mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">
              Start a conversation
            </h3>
            <p className="text-sm text-slate-400 text-center mb-6 max-w-sm">
              Ask me anything about your notes, concepts, or learning materials.
              I can help you understand and review.
            </p>

            {chatSuggestions.length > 0 && (
              <div className="w-full max-w-sm space-y-2">
                <p className="text-xs text-slate-500 text-center mb-2">
                  Try asking:
                </p>
                {chatSuggestions.map((suggestion, i) => (
                  <button
                    key={i}
                    onClick={() => handleSuggestionClick(suggestion)}
                    className="w-full p-3 bg-[#1A1A1C] border border-[#27272A] rounded-xl text-left text-sm text-slate-300 hover:bg-[#27272A] transition-colors flex items-center justify-between group"
                  >
                    <span>{suggestion}</span>
                    <ChevronRight className="h-4 w-4 text-slate-500 group-hover:text-white transition-colors" />
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          // Messages list
          <>
            {chatMessages.map((msg, i) => renderMessage(msg, i))}
            
            {/* Loading indicator */}
            {isChatLoading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-[#27272A] flex items-center justify-center flex-shrink-0">
                  <Bot className="h-4 w-4 text-purple-400" />
                </div>
                <div className="bg-[#1A1A1C] p-4 rounded-2xl rounded-bl-md">
                  <div className="flex gap-1">
                    <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                    <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                    <div className="w-2 h-2 bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              </div>
            )}

            {/* Sources and related concepts from last response */}
            {lastResponse && !isChatLoading && (
              <div className="ml-11 space-y-3">
                {lastResponse.sources.length > 0 && (
                  <div className="p-3 bg-[#1A1A1C] rounded-xl border border-[#27272A]">
                    <p className="text-xs text-slate-500 mb-2 flex items-center gap-1">
                      <BookOpen className="h-3 w-3" /> Sources
                    </p>
                    <div className="space-y-2">
                      {lastResponse.sources.slice(0, 3).map((source, i) => (
                        <div key={i} className="text-xs">
                          <span className="text-purple-400">{source.title}</span>
                          <p className="text-slate-500 line-clamp-1">
                            {source.preview}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {lastResponse.related_concepts.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    <span className="text-xs text-slate-500 flex items-center gap-1">
                      <Network className="h-3 w-3" /> Related:
                    </span>
                    {lastResponse.related_concepts.slice(0, 5).map((concept) => (
                      <button
                        key={concept.id}
                        onClick={() =>
                          handleConceptClick(concept.id, concept.name)
                        }
                        className="px-2 py-1 text-xs bg-purple-500/20 text-purple-400 rounded-full hover:bg-purple-500/30 transition-colors"
                      >
                        {concept.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="p-4 border-t border-[#27272A]">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
            placeholder="Ask about your notes..."
            className="flex-1 p-3 bg-[#1A1A1C] border border-[#27272A] rounded-xl text-white placeholder:text-slate-500 focus:border-purple-500 focus:outline-none"
            disabled={isChatLoading}
          />
          <Button
            onClick={handleSend}
            disabled={!input.trim() || isChatLoading}
            className="bg-purple-600 hover:bg-purple-700 px-4"
          >
            {isChatLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
