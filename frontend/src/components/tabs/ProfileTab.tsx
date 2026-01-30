"use client";

import React, { useEffect, useState } from "react";
import {
  User,
  Flame,
  Target,
  BookOpen,
  Network,
  Trophy,
  Calendar,
  ChevronRight,
  Settings,
  Info,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStore } from "@/lib/store";
import api from "@/lib/api";

// Simple activity heatmap component
const ActivityHeatmap = ({ data }: { data: Record<string, number> }) => {
  const today = new Date();
  const weeks = 12;
  const days = [];

  for (let i = weeks * 7 - 1; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    const dateStr = date.toISOString().split("T")[0];
    const count = data[dateStr] || 0;
    
    let intensity = "bg-[#1A1A1C]";
    if (count > 0) intensity = "bg-purple-900/50";
    if (count >= 5) intensity = "bg-purple-700/50";
    if (count >= 10) intensity = "bg-purple-500/50";
    if (count >= 20) intensity = "bg-purple-400";

    days.push({
      date: dateStr,
      count,
      intensity,
      dayOfWeek: date.getDay(),
    });
  }

  // Group by weeks
  const weeksArray: typeof days[] = [];
  for (let i = 0; i < days.length; i += 7) {
    weeksArray.push(days.slice(i, i + 7));
  }

  return (
    <div className="flex gap-1">
      {weeksArray.map((week, wi) => (
        <div key={wi} className="flex flex-col gap-1">
          {week.map((day) => (
            <div
              key={day.date}
              className={`w-3 h-3 rounded-sm ${day.intensity}`}
              title={`${day.date}: ${day.count} reviews`}
            />
          ))}
        </div>
      ))}
    </div>
  );
};

// Domain progress bars
const DomainProgress = ({ domain, progress }: { domain: string; progress: number }) => (
  <div className="space-y-1">
    <div className="flex items-center justify-between text-sm">
      <span className="text-slate-300">{domain}</span>
      <span className="text-slate-500">{Math.round(progress * 100)}%</span>
    </div>
    <div className="h-2 bg-[#27272A] rounded-full overflow-hidden">
      <div
        className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all"
        style={{ width: `${progress * 100}%` }}
      />
    </div>
  </div>
);

export default function ProfileTab() {
  const { userStats, setUserStats } = useStore();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activityData, setActivityData] = useState<Record<string, number>>({});

  useEffect(() => {
    loadStats();
    // Mock activity data for now
    generateMockActivityData();
  }, []);

  const loadStats = async () => {
    setIsRefreshing(true);
    try {
      const stats = await api.getUserStats();
      setUserStats(stats);
    } catch (error) {
      console.error("Failed to load stats:", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  const generateMockActivityData = () => {
    // Generate some mock activity data for the heatmap
    const data: Record<string, number> = {};
    const today = new Date();
    
    for (let i = 0; i < 84; i++) {
      const date = new Date(today);
      date.setDate(date.getDate() - i);
      const dateStr = date.toISOString().split("T")[0];
      // Random activity with some days more active
      if (Math.random() > 0.3) {
        data[dateStr] = Math.floor(Math.random() * 25);
      }
    }
    
    setActivityData(data);
  };

  const stats = [
    {
      icon: Flame,
      label: "Streak",
      value: userStats?.streak_days || 0,
      suffix: "days",
      color: "text-orange-400",
    },
    {
      icon: Target,
      label: "Accuracy",
      value: Math.round((userStats?.accuracy_rate || 0) * 100),
      suffix: "%",
      color: "text-green-400",
    },
    {
      icon: BookOpen,
      label: "Concepts",
      value: userStats?.total_concepts || 0,
      suffix: "",
      color: "text-purple-400",
    },
    {
      icon: Network,
      label: "Notes",
      value: userStats?.total_notes || 0,
      suffix: "",
      color: "text-cyan-400",
    },
  ];

  const menuItems = [
    { icon: Settings, label: "Settings", action: () => {} },
    { icon: Info, label: "About GraphRecall", action: () => {} },
  ];

  return (
    <div className="h-full overflow-y-auto">
      {/* Profile header */}
      <div className="p-6 pb-4">
        <div className="flex items-center gap-4 mb-6">
          <div className="w-16 h-16 bg-purple-500 rounded-full flex items-center justify-center">
            <User className="h-8 w-8 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">Student</h2>
            <p className="text-sm text-slate-400">
              {userStats?.total_reviews || 0} total reviews
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={loadStats}
            disabled={isRefreshing}
            className="ml-auto text-slate-400"
          >
            <RefreshCw className={`h-5 w-5 ${isRefreshing ? "animate-spin" : ""}`} />
          </Button>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 gap-3 mb-6">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="p-4 bg-[#1A1A1C] rounded-xl border border-[#27272A]"
            >
              <div className="flex items-center gap-2 mb-2">
                <stat.icon className={`h-4 w-4 ${stat.color}`} />
                <span className="text-sm text-slate-400">{stat.label}</span>
              </div>
              <p className="text-2xl font-bold text-white">
                {stat.value}
                <span className="text-sm font-normal text-slate-500 ml-1">
                  {stat.suffix}
                </span>
              </p>
            </div>
          ))}
        </div>

        {/* Today&apos;s progress */}
        <div className="p-4 bg-[#1A1A1C] rounded-xl border border-[#27272A] mb-6">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-slate-400">Today&apos;s Progress</span>
            <span className="text-sm text-white font-medium">
              {userStats?.completed_today || 0}/{userStats?.due_today || 0}
            </span>
          </div>
          <div className="h-3 bg-[#27272A] rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all"
              style={{
                width: `${Math.min(
                  ((userStats?.completed_today || 0) /
                    Math.max(userStats?.due_today || 1, 1)) *
                    100,
                  100
                )}%`,
              }}
            />
          </div>
          {(userStats?.overdue || 0) > 0 && (
            <p className="text-xs text-orange-400 mt-2">
              {userStats?.overdue} items overdue
            </p>
          )}
        </div>

        {/* Activity heatmap */}
        <div className="p-4 bg-[#1A1A1C] rounded-xl border border-[#27272A] mb-6">
          <div className="flex items-center gap-2 mb-4">
            <Calendar className="h-4 w-4 text-slate-400" />
            <span className="text-sm text-slate-400">Activity (12 weeks)</span>
          </div>
          <div className="overflow-x-auto">
            <ActivityHeatmap data={activityData} />
          </div>
          <div className="flex items-center justify-end gap-1 mt-2 text-xs text-slate-500">
            <span>Less</span>
            <div className="w-3 h-3 rounded-sm bg-[#1A1A1C]" />
            <div className="w-3 h-3 rounded-sm bg-purple-900/50" />
            <div className="w-3 h-3 rounded-sm bg-purple-700/50" />
            <div className="w-3 h-3 rounded-sm bg-purple-500/50" />
            <div className="w-3 h-3 rounded-sm bg-purple-400" />
            <span>More</span>
          </div>
        </div>

        {/* Domain progress */}
        {userStats?.domain_progress && Object.keys(userStats.domain_progress).length > 0 && (
          <div className="p-4 bg-[#1A1A1C] rounded-xl border border-[#27272A] mb-6">
            <div className="flex items-center gap-2 mb-4">
              <TrendingUp className="h-4 w-4 text-slate-400" />
              <span className="text-sm text-slate-400">Domain Progress</span>
            </div>
            <div className="space-y-4">
              {Object.entries(userStats.domain_progress)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 5)
                .map(([domain, progress]) => (
                  <DomainProgress key={domain} domain={domain} progress={progress} />
                ))}
            </div>
          </div>
        )}

        {/* Menu items */}
        <div className="space-y-2">
          {menuItems.map((item) => (
            <button
              key={item.label}
              onClick={item.action}
              className="w-full p-4 bg-[#1A1A1C] rounded-xl border border-[#27272A] flex items-center justify-between hover:bg-[#27272A] transition-colors"
            >
              <div className="flex items-center gap-3">
                <item.icon className="h-5 w-5 text-slate-400" />
                <span className="text-white">{item.label}</span>
              </div>
              <ChevronRight className="h-5 w-5 text-slate-500" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
