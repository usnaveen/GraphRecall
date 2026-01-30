"use client";

import React, { useEffect } from "react";
import {
  Home as HomeIcon,
  Network,
  PlusCircle,
  MessageCircle,
  User,
  Flame,
  Target
} from "lucide-react";
import { useStore, AppTab } from "@/lib/store";
import api from "@/lib/api";

// Import tab components
import FeedTab from "@/components/tabs/FeedTab";
import GraphTab from "@/components/tabs/GraphTab";
import CreateTab from "@/components/tabs/CreateTab";
import ChatTab from "@/components/tabs/ChatTab";
import ProfileTab from "@/components/tabs/ProfileTab";

import Link from 'next/link';
import { LiquidDock } from "@/components/layout/LiquidDock";

export default function Home() {
  const {
    activeTab,
    setActiveTab,
    userStats,
    setUserStats,
    setFeedData,
    setFeedLoading,
    setGraph3DData,
    setGraphLoading,
    setChatSuggestions,
  } = useStore();

  // Load initial data
  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    try {
      // Load user stats
      const stats = await api.getUserStats();
      setUserStats(stats);

      // Load chat suggestions
      const { suggestions } = await api.getChatSuggestions();
      setChatSuggestions(suggestions);
    } catch (error) {
      console.error("Failed to load initial data:", error);
    }
  };

  const renderTab = () => {
    switch (activeTab) {
      case "feed":
        return <FeedTab />;
      case "graph":
        return <GraphTab />;
      case "create":
        return <CreateTab />;
      case "chat":
        return <ChatTab />;
      case "profile":
        return <ProfileTab />;
      default:
        return <FeedTab />;
    }
  };

  return (
    <div className="h-screen flex flex-col bg-[#0A0A0B]">
      {/* Header */}
      <header className="h-14 border-b border-[#27272A] flex items-center justify-between px-4 bg-[#0A0A0B]/95 backdrop-blur-sm sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <Network className="h-6 w-6 text-purple-500" />
          <h1 className="text-lg font-semibold text-white">GraphRecall</h1>
        </div>

        {/* Stats in header */}
        {userStats && (
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1.5 text-orange-400">
              <Flame className="h-4 w-4" />
              <span>{userStats.streak_days}</span>
            </div>
            <div className="flex items-center gap-1.5 text-purple-400">
              <Target className="h-4 w-4" />
              <span>{userStats.completed_today}/{userStats.due_today}</span>
            </div>
          </div>
        )}
      </header>

      {/* Main Content Area */}
      <main className="flex-1 overflow-hidden relative">
        {renderTab()}
      </main>

      {/* Liquid Glass Dock */}
      <LiquidDock />
    </div>
  );
}
