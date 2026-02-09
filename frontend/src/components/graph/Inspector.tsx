import { useMemo } from "react";
import { motion } from "framer-motion";
import { X, Target, BookOpen, Link2, Circle, GitBranch, Layers } from "lucide-react";
import type { Node3D, Link3D } from "../../lib/forceSimulation3d";
import type { Community } from "../../lib/graphData";

const REL_TYPE_COLORS: Record<string, string> = {
  PREREQUISITE_OF: "#2EFFE6",
  SUBTOPIC_OF: "#9B59B6",
  BUILDS_ON: "#F59E0B",
  RELATED_TO: "#FFFFFF",
  PART_OF: "#EC4899",
};

interface InspectorProps {
  selectedNode: Node3D;
  connectedLinks: Link3D[];
  communities: Community[];
  onClose: () => void;
  onNodeSelect: (node: Node3D) => void;
  onQuiz: (topic: string) => void;
  onShowResources: (topic: string, type: "note" | "link") => void;
}

export default function Inspector({
  selectedNode,
  connectedLinks,
  communities,
  onClose,
  onNodeSelect,
  onQuiz,
  onShowResources,
}: InspectorProps) {
  // Build connected nodes sorted by weight
  const connectedNodes = useMemo(() => {
    const nodeMap = new Map<string, { node: Node3D; maxWeight: number; relType: string }>();
    connectedLinks.forEach((link) => {
      const otherNode = link.source.id === selectedNode.id ? link.target : link.source;
      const existing = nodeMap.get(otherNode.id);
      if (!existing || link.weight > existing.maxWeight) {
        nodeMap.set(otherNode.id, {
          node: otherNode,
          maxWeight: link.weight,
          relType: link.description || "RELATED_TO",
        });
      }
    });
    return Array.from(nodeMap.values()).sort((a, b) => b.maxWeight - a.maxWeight);
  }, [connectedLinks, selectedNode.id]);

  // Top relationships by weight
  const topRelationships = useMemo(() => {
    return [...connectedLinks].sort((a, b) => b.weight - a.weight).slice(0, 5);
  }, [connectedLinks]);

  // Community hierarchy
  const hierarchyInfo = useMemo(() => {
    if (!selectedNode.community) return null;

    const current = selectedNode.community;
    const parents = communities.filter((c) => current.parent && c.id === current.parent);
    const children = communities.filter((c) => c.parent === current.id);

    return { current, parents, children };
  }, [selectedNode.community, communities]);

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 20 }}
      className="absolute top-3 right-3 w-80 max-h-[calc(100%-24px)] bg-black/80 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden flex flex-col z-20"
    >
      {/* Header */}
      <div className="p-4 border-b border-white/10 flex-shrink-0">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0 mr-2">
            <div className="flex items-center gap-2 mb-1">
              <Circle className="w-3 h-3 flex-shrink-0" style={{ color: selectedNode.computedColor }} />
              <h3 className="text-sm font-bold text-white truncate">{selectedNode.title}</h3>
            </div>
            {selectedNode.community && (
              <p className="text-[10px] text-white/40 mt-0.5">
                {selectedNode.community.title} &bull; {selectedNode.community.size} nodes
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-full hover:bg-white/10 transition-colors flex-shrink-0"
          >
            <X className="w-4 h-4 text-white/50" />
          </button>
        </div>

        {/* Stats badges */}
        <div className="flex flex-wrap gap-1.5 mt-2">
          <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/10 text-white/70">
            {selectedNode.degree} connections
          </span>
          {selectedNode.domain && (
            <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/10 text-white/70">
              {selectedNode.domain}
            </span>
          )}
          {selectedNode.community && (
            <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/10 text-white/70">
              Level {selectedNode.community.level}
            </span>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => onQuiz(selectedNode.title)}
            className="flex-1 py-1.5 rounded-lg bg-[#B6FF2E]/20 text-[#B6FF2E] text-[10px] font-medium flex items-center justify-center gap-1 hover:bg-[#B6FF2E]/30 transition-colors"
          >
            <Target className="w-3 h-3" />
            Quiz
          </button>
          <button
            onClick={() => onShowResources(selectedNode.title, "note")}
            className="flex-1 py-1.5 rounded-lg bg-white/5 text-white/70 text-[10px] font-medium flex items-center justify-center gap-1 hover:bg-white/10 transition-colors"
          >
            <BookOpen className="w-3 h-3" />
            Notes
          </button>
          <button
            onClick={() => onShowResources(selectedNode.title, "link")}
            className="flex-1 py-1.5 rounded-lg bg-white/5 text-white/70 text-[10px] font-medium flex items-center justify-center gap-1 hover:bg-white/10 transition-colors"
          >
            <Link2 className="w-3 h-3" />
            Links
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Description */}
        {selectedNode.definition && (
          <div>
            <p className="text-[10px] text-white/40 uppercase tracking-wider mb-1.5">Description</p>
            <p className="text-xs text-white/70 leading-relaxed">{selectedNode.definition}</p>
          </div>
        )}

        {/* Community Hierarchy */}
        {hierarchyInfo && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Layers className="w-3 h-3 text-white/40" />
              <p className="text-[10px] text-white/40 uppercase tracking-wider">Community Hierarchy</p>
            </div>
            <div className="space-y-1.5">
              {hierarchyInfo.parents.map((c) => (
                <div key={c.id} className="px-2.5 py-1.5 rounded-lg border border-blue-500/20 bg-blue-500/5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] text-blue-400 font-medium">PARENT</span>
                    <span className="text-[10px] text-white/50">L{c.level}</span>
                  </div>
                  <p className="text-[11px] text-white/80 mt-0.5">{c.title}</p>
                </div>
              ))}
              <div className="px-2.5 py-1.5 rounded-lg border border-[#B6FF2E]/30 bg-[#B6FF2E]/5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] text-[#B6FF2E] font-medium">CURRENT</span>
                  <span className="text-[10px] text-white/50">L{hierarchyInfo.current.level}</span>
                  <span className="text-[10px] text-white/40">{hierarchyInfo.current.size} entities</span>
                </div>
                <p className="text-[11px] text-white/80 mt-0.5">{hierarchyInfo.current.title}</p>
              </div>
              {hierarchyInfo.children.map((c) => (
                <div key={c.id} className="px-2.5 py-1.5 rounded-lg border border-green-500/20 bg-green-500/5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[9px] text-green-400 font-medium">CHILD</span>
                    <span className="text-[10px] text-white/50">L{c.level}</span>
                    <span className="text-[10px] text-white/40">{c.size} entities</span>
                  </div>
                  <p className="text-[11px] text-white/80 mt-0.5">{c.title}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Top Relationships */}
        {topRelationships.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <GitBranch className="w-3 h-3 text-white/40" />
              <p className="text-[10px] text-white/40 uppercase tracking-wider">Strongest Relationships</p>
            </div>
            <div className="space-y-1.5">
              {topRelationships.map((link) => {
                const other = link.source.id === selectedNode.id ? link.target : link.source;
                const relType = link.description?.toUpperCase() || "RELATED_TO";
                const relColor = REL_TYPE_COLORS[relType] || "#FFFFFF";
                return (
                  <button
                    key={link.id}
                    onClick={() => onNodeSelect(other)}
                    className="w-full text-left px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span
                          className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: relColor }}
                        />
                        <span className="text-[11px] text-white/80 truncate">{other.title}</span>
                      </div>
                      <span className="text-[10px] text-white/40 ml-2 flex-shrink-0">
                        {Math.round(link.weight * 100)}%
                      </span>
                    </div>
                    <span className="text-[9px] text-white/30 mt-0.5 block" style={{ color: relColor }}>
                      {relType.replace(/_/g, " ")}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Connected Entities */}
        {connectedNodes.length > 0 && (
          <div>
            <p className="text-[10px] text-white/40 uppercase tracking-wider mb-2">
              Connected Entities ({connectedNodes.length})
            </p>
            <div className="flex flex-wrap gap-1">
              {connectedNodes.map(({ node, relType }) => {
                const relColor = REL_TYPE_COLORS[relType.toUpperCase()] || "#FFFFFF";
                return (
                  <button
                    key={node.id}
                    onClick={() => onNodeSelect(node)}
                    className="px-2 py-0.5 rounded-full text-[10px] bg-white/5 border border-white/10 text-white/60 hover:bg-white/10 transition-colors flex items-center gap-1"
                  >
                    <span
                      className="w-1 h-1 rounded-full flex-shrink-0"
                      style={{ backgroundColor: relColor }}
                    />
                    {node.title}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
}
