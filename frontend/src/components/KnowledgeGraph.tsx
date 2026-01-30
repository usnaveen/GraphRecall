"use client";

import React, { useCallback, useEffect, useMemo } from "react";
import {
  ReactFlow,
  Node,
  Edge,
  Controls,
  MiniMap,
  Background,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useStore } from "@/lib/store";
import { Concept } from "@/lib/api";

// Custom node component for concepts
function ConceptNode({ data }: { data: Concept & { proficiency?: number } }) {
  // Color based on proficiency (if available) or domain
  const getNodeColor = () => {
    if (data.proficiency !== undefined) {
      if (data.proficiency < 0.4) return "#ef4444"; // red - low proficiency
      if (data.proficiency < 0.7) return "#f59e0b"; // yellow - medium
      return "#22c55e"; // green - high proficiency
    }
    // Default domain-based colors
    const domainColors: Record<string, string> = {
      "Machine Learning": "#8b5cf6",
      "Mathematics": "#3b82f6",
      "Programming": "#10b981",
      "Science": "#f59e0b",
      "General": "#6b7280",
    };
    return domainColors[data.domain] || "#6b7280";
  };

  // Size based on complexity
  const getNodeSize = () => {
    const base = 80;
    const scale = (data.complexity_score || 5) / 5;
    return base * scale;
  };

  const size = getNodeSize();
  const color = getNodeColor();

  return (
    <div
      className="flex items-center justify-center rounded-full border-2 shadow-lg cursor-pointer transition-all hover:scale-110"
      style={{
        width: size,
        height: size,
        backgroundColor: color,
        borderColor: "rgba(255,255,255,0.3)",
      }}
    >
      <div className="text-center text-white text-xs font-medium px-2 truncate max-w-full">
        {data.name}
      </div>
    </div>
  );
}

const nodeTypes = {
  concept: ConceptNode,
};

interface KnowledgeGraphProps {
  onConceptSelect?: (concept: Concept | null) => void;
}

export default function KnowledgeGraph({ onConceptSelect }: KnowledgeGraphProps) {
  const { graphData, isGraphLoading, graphError, setSelectedConcept } = useStore();
  
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Convert graph data to React Flow format
  useEffect(() => {
    if (!graphData) return;

    const flowNodes: Node[] = graphData.nodes.map((concept, index) => {
      // Create a circular layout
      const angle = (2 * Math.PI * index) / graphData.nodes.length;
      const radius = Math.min(400, graphData.nodes.length * 30);
      
      return {
        id: concept.id,
        type: "concept",
        position: {
          x: 400 + radius * Math.cos(angle),
          y: 300 + radius * Math.sin(angle),
        },
        data: concept,
      };
    });

    const flowEdges: Edge[] = graphData.edges.map((edge, index) => ({
      id: `edge-${index}`,
      source: edge.source,
      target: edge.target,
      type: "default",
      animated: edge.type === "PREREQUISITE_OF",
      label: edge.type.replace(/_/g, " "),
      labelStyle: { fontSize: 10, fill: "#666" },
      style: {
        stroke: edge.type === "PREREQUISITE_OF" ? "#f59e0b" : "#6b7280",
        strokeWidth: 2,
      },
    }));

    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [graphData, setNodes, setEdges]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_, node) => {
      const concept = node.data as Concept;
      setSelectedConcept(concept);
      onConceptSelect?.(concept);
    },
    [setSelectedConcept, onConceptSelect]
  );

  if (isGraphLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-slate-900">
        <div className="text-slate-400 flex flex-col items-center gap-4">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-500"></div>
          <span>Loading knowledge graph...</span>
        </div>
      </div>
    );
  }

  if (graphError) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-slate-900">
        <div className="text-red-400 text-center">
          <p className="text-lg">Error loading graph</p>
          <p className="text-sm text-slate-500 mt-2">{graphError}</p>
        </div>
      </div>
    );
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-slate-900">
        <div className="text-slate-400 text-center">
          <p className="text-lg">No concepts yet</p>
          <p className="text-sm text-slate-500 mt-2">
            Ingest some notes to build your knowledge graph
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        className="bg-slate-900"
      >
        <Controls className="bg-slate-800 border-slate-700" />
        <MiniMap
          className="bg-slate-800 border-slate-700"
          nodeColor={(node) => {
            const data = node.data as Concept;
            const domainColors: Record<string, string> = {
              "Machine Learning": "#8b5cf6",
              "Mathematics": "#3b82f6",
              "Programming": "#10b981",
              default: "#6b7280",
            };
            return domainColors[data?.domain] || domainColors.default;
          }}
        />
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#374151" />
      </ReactFlow>
    </div>
  );
}
