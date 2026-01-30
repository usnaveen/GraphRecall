"use client";

import React, { useEffect, useState } from "react";
import Visualizer3D from "@/components/graph/Visualizer3D";
import { useStore } from "@/lib/store";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Search, Filter, RefreshCw, X } from "lucide-react";

// Domain colors
const DOMAIN_COLORS: Record<string, string> = {
  "Machine Learning": "#8b5cf6",
  "Mathematics": "#3b82f6",
  "Programming": "#10b981",
  "Science": "#f59e0b",
  "Computer Science": "#ec4899",
  "Physics": "#06b6d4",
  "General": "#6b7280",
};

export default function GraphTab() {
  const {
    graph3DData,
    setGraph3DData,
    graphSearchQuery,
    setGraphSearchQuery,
    setSelectedConcept,
    isGraphLoading,
    setGraphLoading,
    graphError,
    setGraphError,
  } = useStore();

  const [selectedDomains, setSelectedDomains] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    load3DGraph();
  }, [selectedDomains]);

  const load3DGraph = async () => {
    setGraphLoading(true);
    setGraphError(null);
    try {
      const data = await api.get3DGraph({
        domains: selectedDomains.length > 0 ? selectedDomains : undefined,
      });
      // Transform data for Visualizer3D
      const vData = {
        nodes: data.nodes.map((n: any) => ({
          ...n,
          val: n.complexity_score || 1, // Force graph uses 'val' for size
        })),
        links: data.edges.map((e: any) => ({
          source: e.source,
          target: e.target,
          ...e
        }))
      };
      // @ts-ignore
      setGraph3DData(vData);
    } catch (error) {
      setGraphError(error instanceof Error ? error.message : "Failed to load graph");
    } finally {
      setGraphLoading(false);
    }
  };



  const handleSearch = async () => {
    if (!graphSearchQuery.trim()) {
      load3DGraph();
      return;
    }

    try {
      const { results } = await api.searchGraph(graphSearchQuery);
      if (results.length > 0) {
        // Focus on first result
        const focus = await api.focusOnConcept(results[0].id, 2);

        // Transform for 3D
        const vData = {
          nodes: [focus.center, ...focus.connections.map(c => c.concept)].map(n => ({
            ...n,
            val: n.complexity_score || 1
          })),
          links: focus.connections.map((c, i) => ({
            source: c.direction === "outgoing" ? focus.center.id : c.concept.id,
            target: c.direction === "outgoing" ? c.concept.id : focus.center.id,
            relationship_type: c.relationship,
            strength: c.strength
          }))
        };

        // @ts-ignore
        setGraph3DData(vData);
      }
    } catch (error) {
      console.error("Search failed:", error);
    }
  };

  const toggleDomain = (domain: string) => {
    setSelectedDomains(prev =>
      prev.includes(domain)
        ? prev.filter(d => d !== domain)
        : [...prev, domain]
    );
  };

  if (isGraphLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0A0A0B]">
        <div className="text-center">
          <RefreshCw className="h-8 w-8 text-purple-500 animate-spin mx-auto mb-4" />
          <p className="text-slate-400">Loading knowledge graph...</p>
        </div>
      </div>
    );
  }

  if (graphError) {
    return (
      <div className="h-full flex items-center justify-center bg-[#0A0A0B]">
        <div className="text-center">
          <p className="text-red-400 mb-4">{graphError}</p>
          <Button onClick={load3DGraph} variant="outline">
            <RefreshCw className="h-4 w-4 mr-2" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full relative">
      {/* Search bar */}
      <div className="absolute top-4 left-4 right-4 z-10 flex gap-2">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <input
            type="text"
            value={graphSearchQuery}
            onChange={(e) => setGraphSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Search concepts..."
            className="w-full pl-10 pr-4 py-2 bg-[#1A1A1C] border border-[#27272A] rounded-xl text-white placeholder:text-slate-500 focus:border-purple-500 focus:outline-none"
          />
          {graphSearchQuery && (
            <button
              onClick={() => {
                setGraphSearchQuery("");
                load3DGraph();
              }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <Button
          variant="outline"
          size="icon"
          onClick={() => setShowFilters(!showFilters)}
          className={showFilters ? "bg-purple-500/20 border-purple-500" : ""}
        >
          <Filter className="h-4 w-4" />
        </Button>
      </div>

      {/* Domain filters */}
      {showFilters && graph3DData && (
        <div className="absolute top-16 left-4 right-4 z-10 p-4 bg-[#1A1A1C] border border-[#27272A] rounded-xl">
          <p className="text-sm text-slate-400 mb-3">Filter by domain:</p>
          <div className="flex flex-wrap gap-2">
            {graph3DData.clusters?.map((cluster: any) => (
              <button
                key={cluster.domain}
                onClick={() => toggleDomain(cluster.domain)}
                className={`px-3 py-1 rounded-full text-sm font-medium transition-all ${selectedDomains.includes(cluster.domain)
                  ? "text-white"
                  : "text-slate-400 bg-[#27272A] hover:bg-[#3f3f46]"
                  }`}
                style={{
                  backgroundColor: selectedDomains.includes(cluster.domain)
                    ? cluster.color
                    : undefined,
                }}
              >
                {cluster.domain} ({cluster.count})
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Graph stats */}
      {graph3DData && (
        <div className="absolute bottom-4 left-4 z-10 flex gap-2">
          <div className="px-3 py-1.5 bg-[#1A1A1C]/80 border border-[#27272A] rounded-lg text-xs text-slate-400 backdrop-blur-sm">
            {graph3DData.total_nodes || graph3DData.nodes?.length} concepts
          </div>
          <div className="px-3 py-1.5 bg-[#1A1A1C]/80 border border-[#27272A] rounded-lg text-xs text-slate-400 backdrop-blur-sm">
            {graph3DData.total_edges || graph3DData.links?.length} connections
          </div>
        </div>
      )}

      {/* Legend */}
      {graph3DData && graph3DData.clusters?.length > 0 && (
        <div className="absolute bottom-4 right-4 z-10 p-3 bg-[#1A1A1C]/80 border border-[#27272A] rounded-xl backdrop-blur-sm">
          <p className="text-xs text-slate-500 mb-2">Domains</p>
          <div className="space-y-1">
            {graph3DData.clusters.slice(0, 5).map((cluster: any) => (
              <div key={cluster.domain} className="flex items-center gap-2">
                <div
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: cluster.color }}
                />
                <span className="text-xs text-slate-400">{cluster.domain}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3D Graph */}
      {(!graph3DData || !graph3DData.nodes || graph3DData.nodes.length === 0) ? (
        <div className="h-full flex items-center justify-center bg-[#0A0A0B]">
          <div className="text-center">
            <p className="text-slate-400 mb-4">No concepts in your knowledge graph yet</p>
            <Button onClick={load3DGraph} variant="outline">
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh
            </Button>
          </div>
        </div>
      ) : (
        // @ts-ignore
        <Visualizer3D data={graph3DData} />
      )}
    </div>
  );
}
