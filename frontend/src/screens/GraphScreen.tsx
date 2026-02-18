import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Search, X, Target, Link2, Plus, Loader2, ChevronDown } from "lucide-react";
import { GraphVisualizer } from "../components/graph/GraphVisualizer";
import Inspector from "../components/graph/Inspector";
import Controls from "../components/graph/Controls";
import type { GraphData, Community } from "../lib/graphData";
import { ForceSimulation3D } from "../lib/forceSimulation3d";
import type { GraphLayout, Node3D, Link3D } from "../lib/forceSimulation3d";
import { api, nodesService } from "../services/api";
import { useAppStore } from "../store/useAppStore";

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

type LinkSuggestion = {
  target_id: string;
  relationship_type: string;
  strength?: number;
  reason?: string;
};

export function GraphScreen() {
  const { startQuizForTopic, graphCache, setGraphCache } = useAppStore();

  const [layout, setLayout] = useState<GraphLayout | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNode, setSelectedNode] = useState<Node3D | null>(null);
  const [hoveredNode, setHoveredNode] = useState<Node3D | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null);
  const [showCommunities, setShowCommunities] = useState(true);
  const [isolateCommunity, setIsolateCommunity] = useState(false);

  // Controls state
  const [minRelationshipWeight, setMinRelationshipWeight] = useState(0);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const [showInspector, setShowInspector] = useState(true);

  // Resources Modal State
  const [showResources, setShowResources] = useState(false);
  const [resourceType, setResourceType] = useState<"note" | "link">("note");
  const [selectedResourceTopic, setSelectedResourceTopic] = useState("");
  const [resources, setResources] = useState<any[]>([]);
  const [resourcesLoading, setResourcesLoading] = useState(false);

  // Manual node creation
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newNodeName, setNewNodeName] = useState("");
  const [newNodeDesc, setNewNodeDesc] = useState("");
  const [newNodeDomain, setNewNodeDomain] = useState("General");
  const [newNodeParentId, setNewNodeParentId] = useState<string | null>(null);
  const [parentSearchQuery, setParentSearchQuery] = useState("");
  const [creatingNode, setCreatingNode] = useState(false);
  const [suggestions, setSuggestions] = useState<LinkSuggestion[]>([]);
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkNodeId, setLinkNodeId] = useState<string | null>(null);
  const [pendingPosition, setPendingPosition] = useState<{ x: number; y: number; z: number } | null>(null);

  const openCreateModal = useCallback(
    (prefillName?: string, position?: { x: number; y: number; z: number }) => {
      setNewNodeName(prefillName || "");
      setNewNodeDesc("");
      setNewNodeDomain("General");
      setNewNodeParentId(null);
      setParentSearchQuery("");
      setPendingPosition(position || null);
      setShowCreateModal(true);
    },
    []
  );

  const loadGraph = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.graph.getGraph();
      const adapted = adaptGraphData(data);
      const sim = new ForceSimulation3D();
      const layoutResult = await sim.generateLayout(adapted);
      setLayout(layoutResult);
      setGraphCache(adapted, layoutResult);
    } catch (err: any) {
      console.error("Failed to load graph:", err);
      setError("Failed to load knowledge graph.");
    } finally {
      setLoading(false);
    }
  }, [setGraphCache]);

  useEffect(() => {
    const isCacheFresh =
      graphCache.loadedAt && Date.now() - graphCache.loadedAt < 1000 * 60 * 30;

    if (graphCache.data && graphCache.layout && isCacheFresh) {
      setLayout(graphCache.layout);
      setLoading(false);
    } else {
      loadGraph();
    }
  }, [graphCache, loadGraph]);


  const highlightedIds = useMemo(() => {
    if (!searchQuery || !layout?.nodes) return new Set<string>();
    const lower = searchQuery.toLowerCase();
    return new Set(layout.nodes.filter((n) => n.title.toLowerCase().includes(lower)).map((n) => n.id));
  }, [searchQuery, layout]);

  const searchMatches = useMemo(() => {
    if (!searchQuery || !layout?.nodes) return [];
    const lower = searchQuery.toLowerCase();
    return layout.nodes.filter((n) => n.title.toLowerCase().includes(lower));
  }, [searchQuery, layout]);

  const handleSearchFocus = useCallback(() => {
    if (searchMatches.length === 0) return;
    const match = searchMatches[0];
    setSelectedNode(match);
    setFocusNodeId(match.id);
  }, [searchMatches]);

  const noSearchMatch = searchQuery.trim().length > 0 && highlightedIds.size === 0;
  const isMobile = typeof window !== "undefined" ? window.innerWidth < 640 : false;

  // Reset isolation when selected node changes or is deselected
  useEffect(() => {
    if (!selectedNode) {
      setIsolateCommunity(false);
    }
  }, [selectedNode]);

  // Parent concept search results for create modal
  const parentSearchResults = useMemo(() => {
    if (!parentSearchQuery.trim() || !layout?.nodes) return [];
    const lower = parentSearchQuery.toLowerCase();
    return layout.nodes
      .filter((n) => n.title.toLowerCase().includes(lower))
      .slice(0, 5);
  }, [parentSearchQuery, layout]);

  const visibleNodeIds = useMemo(() => {
    if (!isolateCommunity || !selectedNode?.community) return undefined;
    return new Set(selectedNode.community.entity_ids);
  }, [isolateCommunity, selectedNode]);

  const showLabels = useMemo(() => {
    const count = layout?.nodes.length || 0;
    return count <= 220;
  }, [layout]);

  // Connected links for inspector panel
  const connectedLinks = useMemo<Link3D[]>(() => {
    if (!selectedNode || !layout?.links) return [];
    return layout.links.filter(
      (l) => l.source.id === selectedNode.id || l.target.id === selectedNode.id
    );
  }, [selectedNode, layout]);

  // Visible node/link counts for controls panel
  const visibleNodeCount = useMemo(() => {
    if (!layout?.nodes) return 0;
    let nodes = layout.nodes;
    if (visibleNodeIds) nodes = nodes.filter((n) => visibleNodeIds.has(n.id));
    if (selectedDomain) nodes = nodes.filter((n) => n.domain === selectedDomain);
    return nodes.length;
  }, [layout, visibleNodeIds, selectedDomain]);

  const visibleLinkCount = useMemo(() => {
    if (!layout?.links) return 0;
    let links = layout.links;
    if (minRelationshipWeight > 0) links = links.filter((l) => l.weight >= minRelationshipWeight);
    return links.length;
  }, [layout, minRelationshipWeight]);

  useEffect(() => {
    if (!searchQuery.trim()) {
      setFocusNodeId(null);
    }
  }, [searchQuery]);

  const handleShowResources = async (topicName: string, type: "note" | "link") => {
    setSelectedResourceTopic(topicName);
    setResourceType(type);
    setResourcesLoading(true); // Set loading FIRST
    setResources([]);
    setShowResources(true); // Then show modal

    try {
      const response = await api.get(`/feed/resources/${encodeURIComponent(topicName)}`);
      const allResources = response.data.resources || [];
      const filtered = allResources.filter((r: any) => {
        if (type === "note") return r.type === "note" || r.type === "saved_response";
        if (type === "link") return r.resource_type === "article" || r.resource_type === "youtube" || r.resource_type === "documentation";
        return true;
      });
      setResources(filtered);
    } catch (error) {
      console.error("Failed to fetch resources:", error);
    } finally {
      setResourcesLoading(false);
    }
  };

  const handleCreateNode = async () => {
    if (!newNodeName.trim()) return;
    setCreatingNode(true);
    try {
      const created = await nodesService.createNode(
        newNodeName.trim(),
        newNodeDesc.trim() || undefined,
        pendingPosition || undefined,
        newNodeDomain,
        newNodeParentId || undefined
      );
      setShowCreateModal(false);
      setNewNodeName("");
      setNewNodeDesc("");
      setNewNodeDomain("General");
      setNewNodeParentId(null);
      setParentSearchQuery("");
      setPendingPosition(null);

      // Suggest links
      const nodeId = created?.node?.id || created?.node?.properties?.id;
      if (nodeId) {
        setLinkNodeId(nodeId);
        const suggestionRes = await nodesService.suggestLinks(nodeId);
        const links = (suggestionRes.links || []).map((l: any) => ({ ...l, _approved: true }));
        setSuggestions(links);
        if (links.length > 0) {
          setShowLinkModal(true);
        }
      }

      await loadGraph();
    } catch (err) {
      console.error("Failed to create node:", err);
    } finally {
      setCreatingNode(false);
    }
  };

  const handleApplyLinks = async () => {
    if (!linkNodeId) return;
    const approved = suggestions.filter((s: any) => s._approved);
    if (approved.length === 0) {
      setShowLinkModal(false);
      return;
    }
    try {
      await nodesService.applyLinks(
        linkNodeId,
        approved.map((s) => ({
          target_id: s.target_id,
          relationship_type: s.relationship_type,
          strength: s.strength,
        }))
      );
      setShowLinkModal(false);
      setSuggestions([]);
      setLinkNodeId(null);
      await loadGraph();
    } catch (err) {
      console.error("Failed to apply links:", err);
    }
  };

  if (loading) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-black/90 text-white">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-[#B6FF2E]" />
          <p className="text-sm text-gray-400">Loading Knowledge Graph...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-black/90 text-white">
        <div className="flex flex-col items-center gap-4">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-120px)] flex flex-col relative">
      {/* Search Bar */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative mb-4 z-50"
      >
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            if (e.target.value === "") setSelectedNode(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              handleSearchFocus();
            }
          }}
          placeholder="Search concepts to quiz..."
          className="w-full pl-10 pr-4 py-3 rounded-full glass-surface text-white placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50"
        />

        {/* Autocomplete Suggestions */}
        {searchQuery.trim() && searchMatches.length > 0 && !selectedNode && (
          <div className="absolute top-full left-4 right-4 mt-2 bg-[#1a1a1f] border border-white/10 rounded-xl overflow-hidden shadow-2xl max-h-60 overflow-y-auto z-50">
            {searchMatches.slice(0, 5).map((node) => (
              <button
                key={node.id}
                onClick={() => {
                  setSearchQuery(node.title);
                  setSelectedNode(node);
                  setFocusNodeId(node.id);
                }}
                className="w-full text-left px-4 py-3 hover:bg-white/5 transition-colors flex items-center justify-between group"
              >
                <span className="text-sm text-white group-hover:text-[#B6FF2E] transition-colors">{node.title}</span>
                {node.community && (
                  <span className="text-[10px] text-white/30">{node.community.title}</span>
                )}
              </button>
            ))}
          </div>
        )}

        {searchQuery.trim() && (
          <button
            onClick={() => startQuizForTopic(searchQuery)}
            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 px-3 py-1.5 bg-[#B6FF2E] text-black rounded-full text-xs font-medium hover:bg-[#c5ff4d] transition-colors shadow-lg"
          >
            <Target className="w-3 h-3" />
            Quiz Me
          </button>
        )}
      </motion.div>

      {noSearchMatch && (
        <div className="mb-3 flex items-center justify-between px-2">
          <p className="text-xs text-white/50">No exact match found.</p>
          <button
            onClick={() => openCreateModal(searchQuery.trim() || undefined)}
            className="text-xs text-[#B6FF2E] hover:text-[#c5ff4d]"
          >
            Create this node
          </button>
        </div>
      )}

      {/* Graph Canvas */}
      <div className="flex-1 rounded-3xl overflow-hidden border border-white/10 relative bg-[#0a0a0f]">
        <GraphVisualizer
          layout={layout}
          selectedNode={selectedNode}
          hoveredNode={hoveredNode}
          onNodeSelect={(node) => {
            setSelectedNode(node);
            if (node) {
              setFocusNodeId(node.id);
              setShowInspector(true);
            }
          }}
          onNodeHover={(node) => setHoveredNode(node)}
          showCommunities={showCommunities}
          searchTerm={searchQuery}
          visibleNodeIds={visibleNodeIds}
          showLabels={showLabels}
          isMobile={isMobile}
          onEmptyContextMenu={(point) => {
            openCreateModal(undefined, point);
          }}
          focusNodeId={focusNodeId}
          pulseNodeId={focusNodeId || selectedNode?.id || null}
          minRelationshipWeight={minRelationshipWeight}
          selectedDomain={selectedDomain}
        />

        {/* Controls Panel (top-left) */}
        {!isMobile && (
          <Controls
            layout={layout}
            showCommunities={showCommunities}
            onToggleCommunities={() => setShowCommunities((v) => !v)}
            onRecomputeCommunities={async () => {
              try {
                await api.post("/graph3d/communities/recompute");
                await loadGraph();
              } catch (e) {
                console.error("Failed to recompute communities", e);
              }
            }}
            minRelationshipWeight={minRelationshipWeight}
            onMinRelationshipWeightChange={setMinRelationshipWeight}
            selectedDomain={selectedDomain}
            onDomainChange={setSelectedDomain}
            visibleNodeCount={visibleNodeCount}
            visibleLinkCount={visibleLinkCount}
          />
        )}

        {/* Mobile community toggle fallback */}
        {isMobile && (
          <div className="absolute top-3 left-3 flex items-center gap-2 bg-black/50 rounded-full px-3 py-1.5">
            <span className="text-[10px] text-white/60">Communities</span>
            <button
              onClick={() => setShowCommunities((v) => !v)}
              className={`text-[10px] px-2 py-0.5 rounded-full ${showCommunities ? "bg-[#B6FF2E] text-black" : "bg-white/10 text-white/60"}`}
            >
              {showCommunities ? "On" : "Off"}
            </button>
          </div>
        )}

        {/* Inspector Panel (right side overlay) */}
        <AnimatePresence>
          {selectedNode && showInspector && !isMobile && (
            <Inspector
              selectedNode={selectedNode}
              connectedLinks={connectedLinks}
              communities={layout?.communities || []}
              onClose={() => setShowInspector(false)}
              onNodeSelect={(node) => {
                setSelectedNode(node);
                setFocusNodeId(node.id);
              }}
              onQuiz={(topic) => startQuizForTopic(topic)}
              onShowResources={handleShowResources}
            />
          )}
        </AnimatePresence>

        {/* Floating action button */}
        <button
          onClick={() => openCreateModal()}
          className="absolute bottom-4 right-4 w-12 h-12 rounded-full bg-[#B6FF2E] text-black flex items-center justify-center shadow-lg hover:bg-[#c5ff4d] transition-colors"
        >
          <Plus className="w-6 h-6" />
        </button>
      </div>


      {/* Create Node Modal */}
      <AnimatePresence>
        {showCreateModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-[#1a1a1f] border border-white/10 rounded-2xl w-full max-w-sm p-6"
            >
              <h3 className="text-lg font-semibold text-white mb-4">Create Concept</h3>
              <input
                value={newNodeName}
                onChange={(e) => setNewNodeName(e.target.value)}
                placeholder="Concept name"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50 mb-3"
              />
              <textarea
                value={newNodeDesc}
                onChange={(e) => setNewNodeDesc(e.target.value)}
                placeholder="Description (optional)"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50 mb-3 h-20 resize-none"
              />

              {/* Domain Dropdown */}
              <div className="relative mb-3">
                <select
                  value={newNodeDomain}
                  onChange={(e) => setNewNodeDomain(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-[#B6FF2E]/50 appearance-none cursor-pointer"
                >
                  {DOMAIN_OPTIONS.map((d) => (
                    <option key={d} value={d} className="bg-[#1a1a1f] text-white">
                      {d}
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40 pointer-events-none" />
              </div>

              {/* Parent Concept Search */}
              <div className="relative mb-4">
                <input
                  value={newNodeParentId ? parentSearchQuery : parentSearchQuery}
                  onChange={(e) => {
                    setParentSearchQuery(e.target.value);
                    if (!e.target.value.trim()) setNewNodeParentId(null);
                  }}
                  placeholder="Parent concept (optional)"
                  className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50"
                />
                {newNodeParentId && (
                  <button
                    onClick={() => { setNewNodeParentId(null); setParentSearchQuery(""); }}
                    className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 rounded-full hover:bg-white/10"
                  >
                    <X className="w-3 h-3 text-white/40" />
                  </button>
                )}
                {parentSearchQuery.trim() && !newNodeParentId && parentSearchResults.length > 0 && (
                  <div className="absolute top-full left-0 right-0 mt-1 bg-[#1a1a1f] border border-white/10 rounded-xl overflow-hidden shadow-xl z-50 max-h-40 overflow-y-auto">
                    {parentSearchResults.map((node) => (
                      <button
                        key={node.id}
                        onClick={() => {
                          setNewNodeParentId(node.id);
                          setParentSearchQuery(node.title);
                        }}
                        className="w-full text-left px-3 py-2 hover:bg-white/5 transition-colors text-sm text-white/80"
                      >
                        {node.title}
                        {node.domain && <span className="text-[10px] text-white/30 ml-2">{node.domain}</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setPendingPosition(null);
                    setShowCreateModal(false);
                  }}
                  className="flex-1 py-2 rounded-xl bg-white/5 text-white/80 text-sm hover:bg-white/10 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateNode}
                  disabled={creatingNode || !newNodeName.trim()}
                  className="flex-1 py-2 rounded-xl bg-[#B6FF2E] text-black text-sm font-medium hover:bg-[#c5ff4d] transition-colors disabled:opacity-50"
                >
                  {creatingNode ? "Creating..." : "Create"}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Link Suggestions Modal */}
      <AnimatePresence>
        {showLinkModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4"
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="bg-[#1a1a1f] border border-white/10 rounded-2xl w-full max-w-md p-6"
            >
              <h3 className="text-lg font-semibold text-white mb-2">Suggested Links</h3>
              <p className="text-xs text-white/50 mb-4">
                Review and approve connections for your new concept.
              </p>
              <div className="space-y-2 max-h-[40vh] overflow-y-auto">
                {suggestions.map((s, i) => (
                  <label key={`${s.target_id}-${i}`} className="flex items-start gap-2 p-2 rounded-lg bg-white/5">
                    <input
                      type="checkbox"
                      defaultChecked
                      onChange={(e) => {
                        const next = [...suggestions];
                        (next[i] as any)._approved = e.target.checked;
                        setSuggestions(next);
                      }}
                    />
                    <div className="flex-1">
                      <p className="text-sm text-white">{(s as any).target_name || s.target_id}</p>
                      <p className="text-[11px] text-white/50">
                        {s.relationship_type} • {Math.round((s.strength || 0.5) * 100)}%
                      </p>
                      {s.reason && <p className="text-[11px] text-white/40 mt-1">{s.reason}</p>}
                    </div>
                  </label>
                ))}
              </div>
              <div className="flex gap-3 mt-4">
                <button
                  onClick={() => setShowLinkModal(false)}
                  className="flex-1 py-2 rounded-xl bg-white/5 text-white/80 text-sm hover:bg-white/10 transition-colors"
                >
                  Skip
                </button>
                <button
                  onClick={handleApplyLinks}
                  className="flex-1 py-2 rounded-xl bg-[#B6FF2E] text-black text-sm font-medium hover:bg-[#c5ff4d] transition-colors"
                >
                  Apply Links
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Resources Modal */}
      <AnimatePresence>
        {showResources && (
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
              className="bg-[#0a0a0f] border border-white/10 rounded-3xl w-full max-w-md max-h-[80vh] flex flex-col"
            >
              <div className="flex items-center justify-between p-4 border-b border-white/10">
                <h3 className="text-lg font-semibold text-white capitalize">{resourceType}s for {selectedResourceTopic}</h3>
                <button onClick={() => setShowResources(false)}>
                  <X className="w-5 h-5 text-white/60" />
                </button>
              </div>

              <div className="p-4 overflow-y-auto flex-1">
                {resourcesLoading ? (
                  <div className="flex justify-center p-8">
                    <Loader2 className="w-8 h-8 animate-spin text-[#B6FF2E]" />
                  </div>
                ) : resources.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-white/60">No {resourceType}s found.</p>
                    <p className="text-xs text-white/40 mt-1">Try generating a quiz or adding notes!</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {resources.map((res: any, i) => (
                      <div key={i} className="p-3 bg-white/5 rounded-xl border border-white/10">
                        <div className="flex justify-between items-start mb-1">
                          <h4 className="font-medium text-white text-sm">{res.title}</h4>
                          <span className="text-[10px] text-white/40">{new Date(res.created_at).toLocaleDateString()}</span>
                        </div>
                        <p className="text-xs text-white/60 mb-2 line-clamp-3">{res.preview}</p>
                        {res.source_url && (
                          <a
                            href={res.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[10px] text-[#2EFFE6] flex items-center gap-1 hover:underline"
                          >
                            <Link2 className="w-3 h-3" /> Open Link
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}

function adaptGraphData(raw: any): GraphData {
  const nodes = raw.nodes || [];
  const edges = raw.edges || [];

  const entities = nodes.map((n: any) => ({
    id: String(n.id),
    title: n.name || n.label || "Concept",
    type: "concept",
    description: n.definition || "",
    frequency: 1,
    degree: 0,
    size: typeof n.size === "number" ? n.size : undefined,
    color: n.color || undefined,
    domain: n.domain || "General",
    x: typeof n.x === "number" ? n.x : undefined,
    y: typeof n.y === "number" ? n.y : undefined,
    z: typeof n.z === "number" ? n.z : undefined,
  }));

  const degreeMap = new Map<string, number>();
  edges.forEach((e: any) => {
    degreeMap.set(e.source, (degreeMap.get(e.source) || 0) + 1);
    degreeMap.set(e.target, (degreeMap.get(e.target) || 0) + 1);
  });
  entities.forEach((e: any) => {
    e.degree = degreeMap.get(e.id) || 0;
  });

  const relationships = edges.map((e: any) => ({
    id: String(e.id || `${e.source}-${e.target}`),
    source: String(e.source),
    target: String(e.target),
    description: e.relationship_type || "RELATED_TO",
    weight: e.strength ?? 0.6,
  }));

  if (raw.communities && raw.communities.length > 0) {
    const nodeColorMap = new Map<string, string>();
    nodes.forEach((n: any) => {
      if (n.id && n.color) nodeColorMap.set(String(n.id), n.color);
    });

    const communities: Community[] = raw.communities.map((c: any) => {
      const firstNodeId = c.entity_ids?.[0];
      const color = firstNodeId ? nodeColorMap.get(String(firstNodeId)) : undefined;
      return {
        id: String(c.id),
        title: c.title || "Community",
        level: c.level ?? 0,
        parent: c.parent || undefined,
        children: c.children || [],
        entity_ids: c.entity_ids || [],
        size: c.size || (c.entity_ids ? c.entity_ids.length : 0),
        computedColor: color || "#95a5a6",
      };
    });
    return { entities, relationships, communities };
  }

  const domainGroups = new Map<string, string[]>();
  entities.forEach((e: any) => {
    const d = e.domain || "General";
    if (!domainGroups.has(d)) domainGroups.set(d, []);
    domainGroups.get(d)?.push(e.id);
  });

  const communities: Community[] = Array.from(domainGroups.entries()).map(([domain, ids], idx) => ({
    id: `domain-${idx}-${domain}`,
    title: domain,
    level: 0,
    parent: undefined,
    children: [],
    entity_ids: ids,
    size: ids.length,
    computedColor: nodes.find((n: any) => n.domain === domain)?.color || "#95a5a6",
  }));

  return { entities, relationships, communities };
}
