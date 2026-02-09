import { useMemo } from "react";
import { motion } from "framer-motion";
import { Filter, Eye, EyeOff, ChevronDown, BarChart3 } from "lucide-react";
import type { GraphLayout } from "../../lib/forceSimulation3d";

interface ControlsProps {
  layout: GraphLayout | null;
  showCommunities: boolean;
  onToggleCommunities: () => void;
  onRecomputeCommunities: () => void;
  minRelationshipWeight: number;
  onMinRelationshipWeightChange: (weight: number) => void;
  selectedDomain: string | null;
  onDomainChange: (domain: string | null) => void;
  visibleNodeCount: number;
  visibleLinkCount: number;
}

const DOMAIN_OPTIONS = [
  "General",
  "Machine Learning",
  "Mathematics",
  "Computer Science",
  "Database Systems",
  "System Design",
  "Programming",
  "Statistics",
];

export default function Controls({
  layout,
  showCommunities,
  onToggleCommunities,
  onRecomputeCommunities,
  minRelationshipWeight,
  onMinRelationshipWeightChange,
  selectedDomain,
  onDomainChange,
  visibleNodeCount,
  visibleLinkCount,
}: ControlsProps) {
  const totalNodes = layout?.nodes.length || 0;
  const totalLinks = layout?.links.length || 0;

  // Available domains from data
  const availableDomains = useMemo(() => {
    if (!layout?.nodes) return [];
    const domains = new Set(layout.nodes.map((n) => n.domain).filter(Boolean));
    return Array.from(domains).sort() as string[];
  }, [layout]);

  // Community levels available
  const communityLevels = useMemo(() => {
    if (!layout?.communities) return [];
    const levels = new Set(layout.communities.map((c) => c.level));
    return Array.from(levels).sort((a, b) => a - b);
  }, [layout]);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="absolute top-3 left-3 bg-black/80 backdrop-blur-xl border border-white/10 rounded-2xl p-3 z-20 w-56"
    >
      {/* Header */}
      <div className="flex items-center gap-1.5 mb-3">
        <Filter className="w-3 h-3 text-white/50" />
        <span className="text-[11px] font-medium text-white/70">Graph Controls</span>
      </div>

      {/* Domain Filter */}
      <div className="mb-3">
        <label className="text-[10px] text-white/40 uppercase tracking-wider block mb-1">Domain</label>
        <div className="relative">
          <select
            value={selectedDomain || ""}
            onChange={(e) => onDomainChange(e.target.value || null)}
            className="w-full px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/10 text-white text-[11px] focus:outline-none focus:border-[#B6FF2E]/50 appearance-none cursor-pointer"
          >
            <option value="" className="bg-[#1a1a1f] text-white">All Domains</option>
            {(availableDomains.length > 0 ? availableDomains : DOMAIN_OPTIONS).map((d) => (
              <option key={d} value={d} className="bg-[#1a1a1f] text-white">
                {d}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 text-white/30 pointer-events-none" />
        </div>
      </div>

      {/* Weight Slider */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <label className="text-[10px] text-white/40 uppercase tracking-wider">Min Weight</label>
          <span className="text-[10px] text-white/60">{Math.round(minRelationshipWeight * 100)}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={Math.round(minRelationshipWeight * 100)}
          onChange={(e) => onMinRelationshipWeightChange(parseInt(e.target.value) / 100)}
          className="w-full h-1 bg-white/10 rounded-full appearance-none cursor-pointer accent-[#B6FF2E]"
        />
      </div>

      {/* Community Controls */}
      <div className="mb-3">
        <label className="text-[10px] text-white/40 uppercase tracking-wider block mb-1">Communities</label>
        <div className="flex gap-1.5">
          <button
            onClick={onToggleCommunities}
            className={`flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded-lg text-[10px] transition-colors ${
              showCommunities
                ? "bg-[#B6FF2E]/20 text-[#B6FF2E]"
                : "bg-white/5 text-white/50"
            }`}
          >
            {showCommunities ? (
              <Eye className="w-3 h-3" />
            ) : (
              <EyeOff className="w-3 h-3" />
            )}
            {showCommunities ? "On" : "Off"}
          </button>
          <button
            onClick={onRecomputeCommunities}
            className="flex-1 px-2 py-1 rounded-lg text-[10px] bg-white/5 text-white/50 hover:bg-white/10 transition-colors"
          >
            Recompute
          </button>
        </div>
        {communityLevels.length > 1 && (
          <p className="text-[9px] text-white/30 mt-1">
            {communityLevels.length} levels detected
          </p>
        )}
      </div>

      {/* Statistics Footer */}
      <div className="pt-2 border-t border-white/10">
        <div className="flex items-center gap-1.5 mb-1">
          <BarChart3 className="w-3 h-3 text-white/30" />
          <span className="text-[10px] text-white/40">Statistics</span>
        </div>
        <div className="flex justify-between text-[10px] text-white/50">
          <span>Nodes: {visibleNodeCount} / {totalNodes}</span>
          <span>Links: {visibleLinkCount} / {totalLinks}</span>
        </div>
      </div>
    </motion.div>
  );
}
