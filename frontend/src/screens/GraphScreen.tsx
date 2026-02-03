import { useRef, useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, Filter, ChevronDown, X, Target, BookOpen, Link2, FileText,
  ZoomIn, ZoomOut, RotateCw, Loader2, XCircle
} from 'lucide-react';
import type { GraphNode, GraphEdge } from '../types';
import { api } from '../services/api';
import { useAppStore } from '../store/useAppStore';

/* ------------------------------------------------------------------ */
/*  Force-layout types used only inside this file                      */
/* ------------------------------------------------------------------ */
interface SimNode {
  id: string;
  name: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  color: string;
  mastery: number;
}

interface SimEdge {
  source: string;
  target: string;
  strength: number;
}

/* ------------------------------------------------------------------ */
/*  Force simulation helpers (pure functions, no external deps)        */
/* ------------------------------------------------------------------ */

function buildSimNodes(nodes: GraphNode[], cw: number, ch: number): SimNode[] {
  if (nodes.length === 0) return [];

  // Find the extent of backend positions to normalize them
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of nodes) {
    if (n.x < minX) minX = n.x;
    if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.y > maxY) maxY = n.y;
  }

  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const pad = 0.15; // 15 percent padding on each side
  const usableW = cw * (1 - 2 * pad);
  const usableH = ch * (1 - 2 * pad);

  return nodes.map(n => ({
    id: n.id,
    name: n.name,
    x: cw * pad + ((n.x - minX) / rangeX) * usableW,
    y: ch * pad + ((n.y - minY) / rangeY) * usableH,
    vx: 0,
    vy: 0,
    size: n.size,
    color: n.color,
    mastery: n.mastery,
  }));
}

function runForceSimulation(
  simNodes: SimNode[],
  simEdges: SimEdge[],
  cw: number,
  ch: number,
  iterations: number = 100
): void {
  const edgeMap = new Map<string, number>(); // "src|tgt" -> index lookup for quick check
  const edgeList: { si: number; ti: number; strength: number }[] = [];

  const idxMap = new Map<string, number>();
  simNodes.forEach((n, i) => idxMap.set(n.id, i));

  for (const e of simEdges) {
    const si = idxMap.get(e.source);
    const ti = idxMap.get(e.target);
    if (si !== undefined && ti !== undefined) {
      edgeList.push({ si, ti, strength: e.strength });
      edgeMap.set(`${si}| ${ti} `, edgeList.length - 1);
      edgeMap.set(`${ti}| ${si} `, edgeList.length - 1);
    }
  }

  const n = simNodes.length;
  const idealLen = Math.sqrt((cw * ch) / Math.max(n, 1)) * 0.8;

  for (let iter = 0; iter < iterations; iter++) {
    const alpha = 1 - iter / iterations; // cooling
    const repStrength = idealLen * idealLen * 0.5;

    // Reset forces
    for (let i = 0; i < n; i++) {
      simNodes[i].vx = 0;
      simNodes[i].vy = 0;
    }

    // Repulsion (every pair)
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = simNodes[i].x - simNodes[j].x;
        let dy = simNodes[i].y - simNodes[j].y;
        let dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 1) dist = 1;
        const force = repStrength / (dist * dist);
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        simNodes[i].vx += fx;
        simNodes[i].vy += fy;
        simNodes[j].vx -= fx;
        simNodes[j].vy -= fy;
      }
    }

    // Attraction (edges)
    for (const edge of edgeList) {
      const a = simNodes[edge.si];
      const b = simNodes[edge.ti];
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      let dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 1) dist = 1;
      const force = (dist - idealLen * 0.6) * 0.05 * edge.strength;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    // Centering force
    const cx = cw / 2;
    const cy = ch / 2;
    for (let i = 0; i < n; i++) {
      simNodes[i].vx += (cx - simNodes[i].x) * 0.01;
      simNodes[i].vy += (cy - simNodes[i].y) * 0.01;
    }

    // Apply velocities with cooling & damping
    const maxSpeed = idealLen * 0.4;
    for (let i = 0; i < n; i++) {
      const node = simNodes[i];
      node.vx *= alpha * 0.8;
      node.vy *= alpha * 0.8;
      const speed = Math.sqrt(node.vx * node.vx + node.vy * node.vy);
      if (speed > maxSpeed) {
        node.vx = (node.vx / speed) * maxSpeed;
        node.vy = (node.vy / speed) * maxSpeed;
      }
      node.x += node.vx;
      node.y += node.vy;
      // Keep within bounds with some margin
      node.x = Math.max(40, Math.min(cw - 40, node.x));
      node.y = Math.max(40, Math.min(ch - 40, node.y));
    }
  }
}

/* ------------------------------------------------------------------ */
/*  Canvas drawing helpers                                             */
/* ------------------------------------------------------------------ */

function drawGrid(ctx: CanvasRenderingContext2D, cw: number, ch: number, panX: number, panY: number, zoom: number) {
  const gridSize = 40;
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.03)';
  ctx.lineWidth = 1;

  // Calculate the grid offset so it pans with the view


  const startX = -panX / zoom - gridSize;
  const startY = -panY / zoom - gridSize;
  const endX = startX + cw / zoom + gridSize * 2;
  const endY = startY + ch / zoom + gridSize * 2;

  ctx.beginPath();
  for (let x = Math.floor(startX / gridSize) * gridSize; x <= endX; x += gridSize) {
    ctx.moveTo(x, startY);
    ctx.lineTo(x, endY);
  }
  for (let y = Math.floor(startY / gridSize) * gridSize; y <= endY; y += gridSize) {
    ctx.moveTo(startX, y);
    ctx.lineTo(endX, y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawEdges(
  ctx: CanvasRenderingContext2D,
  simNodes: SimNode[],
  simEdges: SimEdge[],
  selectedId: string | null
) {
  const idxMap = new Map<string, number>();
  simNodes.forEach((n, i) => idxMap.set(n.id, i));

  for (const edge of simEdges) {
    const si = idxMap.get(edge.source);
    const ti = idxMap.get(edge.target);
    if (si === undefined || ti === undefined) continue;
    const a = simNodes[si];
    const b = simNodes[ti];

    const isConnectedToSelected = selectedId !== null && (a.id === selectedId || b.id === selectedId);
    const baseAlpha = 0.08 + edge.strength * 0.15;
    const alpha = isConnectedToSelected ? Math.min(baseAlpha * 3, 0.6) : baseAlpha;

    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = isConnectedToSelected
      ? `rgba(182, 255, 46, ${alpha})`
      : `rgba(255, 255, 255, ${alpha})`;
    ctx.lineWidth = isConnectedToSelected ? 1.5 : 0.8;
    ctx.stroke();
  }
}

function drawNodes(
  ctx: CanvasRenderingContext2D,
  simNodes: SimNode[],
  selectedId: string | null,
  filteredIds: Set<string>
) {
  for (const node of simNodes) {
    const isSelected = node.id === selectedId;
    const isVisible = filteredIds.has(node.id);
    if (!isVisible) continue;

    const radius = (8 + node.size * 8);
    const opacity = 0.6 + (node.mastery / 250);

    // Glow for selected node
    if (isSelected) {
      const gradient = ctx.createRadialGradient(
        node.x, node.y, radius * 0.5,
        node.x, node.y, radius * 3
      );
      gradient.addColorStop(0, 'rgba(182, 255, 46, 0.3)');
      gradient.addColorStop(1, 'rgba(182, 255, 46, 0)');
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius * 3, 0, Math.PI * 2);
      ctx.fillStyle = gradient;
      ctx.fill();
    }

    // Subtle glow for all nodes
    const glowGrad = ctx.createRadialGradient(
      node.x, node.y, radius * 0.3,
      node.x, node.y, radius * 2
    );
    glowGrad.addColorStop(0, hexToRgba(node.color, 0.15));
    glowGrad.addColorStop(1, hexToRgba(node.color, 0));
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius * 2, 0, Math.PI * 2);
    ctx.fillStyle = glowGrad;
    ctx.fill();

    // Main circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = hexToRgba(node.color, opacity);
    ctx.fill();

    // Selected ring
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius + 3, 0, Math.PI * 2);
      ctx.strokeStyle = '#B6FF2E';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }
}

function drawLabels(
  ctx: CanvasRenderingContext2D,
  simNodes: SimNode[],
  selectedId: string | null,
  filteredIds: Set<string>,
  zoom: number
) {
  const fontSize = Math.max(10, Math.min(13, 12 / Math.sqrt(zoom)));
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';

  for (const node of simNodes) {
    if (!filteredIds.has(node.id)) continue;
    const isSelected = node.id === selectedId;
    const radius = (8 + node.size * 8);

    ctx.font = `${isSelected ? 600 : 400} ${fontSize} px - apple - system, BlinkMacSystemFont, "Segoe UI", sans - serif`;
    ctx.fillStyle = isSelected ? '#B6FF2E' : 'rgba(255, 255, 255, 0.7)';
    ctx.fillText(node.name, node.x, node.y + radius + 6);
  }
}

function hexToRgba(hex: string, alpha: number): string {
  let r = 0, g = 0, b = 0;
  if (!hex || hex.length < 4) return `rgba(150, 100, 255, ${alpha})`;
  const h = hex.replace('#', '');
  if (h.length === 3) {
    r = parseInt(h[0] + h[0], 16);
    g = parseInt(h[1] + h[1], 16);
    b = parseInt(h[2] + h[2], 16);
  } else if (h.length >= 6) {
    r = parseInt(h.substring(0, 2), 16);
    g = parseInt(h.substring(2, 4), 16);
    b = parseInt(h.substring(4, 6), 16);
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function GraphScreen() {
  const { startQuizForTopic, conceptsList, fetchConcepts } = useAppStore();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  // Camera state
  const [zoom, setZoom] = useState(1);
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });

  // Real Data State
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  // const [edges, setEdges] = useState<GraphEdge[]>([]); // Edges unused for now
  const [edges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Simulation nodes (laid out)
  const simNodesRef = useRef<SimNode[]>([]);
  const simEdgesRef = useRef<SimEdge[]>([]);
  const layoutReadyRef = useRef(false);

  // Canvas
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef<number>(0);

  // Interaction refs (avoid stale closures)
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const panRef = useRef({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const lastPinchDistRef = useRef(0);

  // Keep refs in sync with state
  useEffect(() => { panRef.current = panOffset; }, [panOffset]);
  useEffect(() => { zoomRef.current = zoom; }, [zoom]);

  // Linked notes for selected node (from graph focus API)
  const [linkedNotes, setLinkedNotes] = useState<any[]>([]);
  const [linkedNotesLoading, setLinkedNotesLoading] = useState(false);
  const [nodeConnections, setNodeConnections] = useState<any[]>([]);

  // Resources Modal State
  const [showResources, setShowResources] = useState(false);
  const [resourceType, setResourceType] = useState<'note' | 'link' | 'concept'>('note');
  const [selectedResourceTopic, setSelectedResourceTopic] = useState('');
  const [resources, setResources] = useState<any[]>([]);
  const [resourcesLoading, setResourcesLoading] = useState(false);

  // Note detail modal
  const [selectedNoteDetail, setSelectedNoteDetail] = useState<any | null>(null);

  /* ---------------------------------------------------------------- */
  /*  Fetch Graph Data on Mount                                       */
  /* ---------------------------------------------------------------- */
  /* ---------------------------------------------------------------- */
  /*  Fetch Graph Data on Mount (Persistence Fix)                     */
  /* ---------------------------------------------------------------- */
  useEffect(() => {
    const loadData = async () => {
      // If we have concepts in store, use them immediately
      if (conceptsList.length > 0) {
        setLoading(false);
        return;
      }

      // Otherwise fetch
      try {
        setLoading(true);
        await fetchConcepts();
      } catch (err) {
        console.error("Failed to load concepts:", err);
        setError("Failed to load knowledge graph.");
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, [fetchConcepts, conceptsList.length]);

  // Sync store concepts to local graph nodes
  useEffect(() => {
    if (conceptsList.length > 0) {
      const graphNodes: GraphNode[] = conceptsList.map(c => ({
        id: c.id,
        name: c.name,
        definition: c.definition, // This might need type extension if GraphNode is strict, but TS usually allows extra props if unused in target type
        label: 'Concept',
        size: c.complexity_score * 5 + 20,
        complexity: c.complexity_score,
        x: 0,
        y: 0,
        z: 0,
        color: '#B6FF2E', // Default color, or map from domain
        mastery: 0
      } as unknown as GraphNode)); // Cast to avoid strict property checks if types are mismatching slightly
      setNodes(graphNodes);
    }
  }, [conceptsList]);

  /* ---------------------------------------------------------------- */
  /*  Fetch linked notes when a node is selected                       */
  /* ---------------------------------------------------------------- */
  useEffect(() => {
    if (!selectedNode) {
      setLinkedNotes([]);
      setNodeConnections([]);
      return;
    }
    const fetchFocus = async () => {
      setLinkedNotesLoading(true);
      try {
        const data = await api.graph.getFocus(selectedNode);
        setLinkedNotes(data.linked_notes || []);
        setNodeConnections((data.connections || []).slice(0, 5));
      } catch (err) {
        console.error("Failed to fetch node focus:", err);
      } finally {
        setLinkedNotesLoading(false);
      }
    };
    fetchFocus();
  }, [selectedNode]);

  /* ---------------------------------------------------------------- */
  /*  Run force layout when nodes/edges arrive                         */
  /* ---------------------------------------------------------------- */
  useEffect(() => {
    if (nodes.length === 0) {
      layoutReadyRef.current = false;
      return;
    }

    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const cw = container.clientWidth;
    const ch = container.clientHeight;

    const sim = buildSimNodes(nodes, cw, ch);
    const sEdges: SimEdge[] = edges.map(e => ({
      source: e.source,
      target: e.target,
      strength: e.strength,
    }));

    runForceSimulation(sim, sEdges, cw, ch, 120);

    simNodesRef.current = sim;
    simEdgesRef.current = sEdges;
    layoutReadyRef.current = true;
  }, [nodes, edges]);

  /* ---------------------------------------------------------------- */
  /*  Canvas render loop                                               */
  /* ---------------------------------------------------------------- */
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const cw = canvas.width / dpr;
    const ch = canvas.height / dpr;

    // Clear
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Background fill
    ctx.fillStyle = '#0a0a0f';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    ctx.scale(dpr, dpr);

    // Draw grid (before pan/zoom so it stays behind)
    drawGrid(ctx, cw, ch, panRef.current.x, panRef.current.y, zoomRef.current);

    // Apply camera transform
    ctx.translate(panRef.current.x, panRef.current.y);
    ctx.scale(zoomRef.current, zoomRef.current);

    if (layoutReadyRef.current) {
      const filteredIds = new Set<string>();
      const query = searchQuery.toLowerCase();
      for (const n of simNodesRef.current) {
        if (!query || n.name.toLowerCase().includes(query)) {
          filteredIds.add(n.id);
        }
      }

      drawEdges(ctx, simNodesRef.current, simEdgesRef.current, selectedNode);
      drawNodes(ctx, simNodesRef.current, selectedNode, filteredIds);
      drawLabels(ctx, simNodesRef.current, selectedNode, filteredIds, zoomRef.current);
    }

    ctx.restore();

    animFrameRef.current = requestAnimationFrame(render);
  }, [searchQuery, selectedNode]);

  // Start / restart render loop when dependencies change
  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [render]);

  /* ---------------------------------------------------------------- */
  /*  Canvas sizing                                                    */
  /* ---------------------------------------------------------------- */
  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = container.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width} px`;
    canvas.style.height = `${rect.height} px`;
  }, []);

  useEffect(() => {
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    return () => window.removeEventListener('resize', resizeCanvas);
  }, [resizeCanvas]);

  // Re-layout when canvas size changes significantly (e.g. first paint)
  // Re-layout when nodes arrive or container resizes
  useEffect(() => {
    if (loading || nodes.length === 0) {
      layoutReadyRef.current = false;
      return;
    }

    const runLayout = () => {
      const container = containerRef.current;
      if (!container) return;
      const cw = container.clientWidth;
      const ch = container.clientHeight;

      if (cw > 0 && ch > 0) {
        // Only re-run if we haven't or if dimensions changed substantially? 
        // For now, always re-run on valid resize to ensure fit.
        const sim = buildSimNodes(nodes, cw, ch);
        const sEdges: SimEdge[] = edges.map(e => ({
          source: e.source,
          target: e.target,
          strength: e.strength,
        }));
        runForceSimulation(sim, sEdges, cw, ch, 120);
        simNodesRef.current = sim;
        simEdgesRef.current = sEdges;
        layoutReadyRef.current = true;
        resizeCanvas();
        // Force a render frame
        animFrameRef.current = requestAnimationFrame(render);
      }
    };

    // Run initially (with delay for tab animation)
    const timer = setTimeout(runLayout, 100);

    // Also use ResizeObserver to catch when tab becomes visible/sized
    const observer = new ResizeObserver(() => {
      runLayout();
    });

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, [loading, nodes, edges, resizeCanvas, render]);

  /* ---------------------------------------------------------------- */
  /*  Hit testing                                                      */
  /* ---------------------------------------------------------------- */
  const hitTest = useCallback((clientX: number, clientY: number): SimNode | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    // Convert screen coords to world coords
    const sx = clientX - rect.left;
    const sy = clientY - rect.top;
    const wx = (sx - panRef.current.x) / zoomRef.current;
    const wy = (sy - panRef.current.y) / zoomRef.current;

    // Check nodes in reverse (topmost first)
    for (let i = simNodesRef.current.length - 1; i >= 0; i--) {
      const node = simNodesRef.current[i];
      const r = (8 + node.size * 8) + 4; // 4px tolerance
      const dx = wx - node.x;
      const dy = wy - node.y;
      if (dx * dx + dy * dy <= r * r) {
        return node;
      }
    }
    return null;
  }, []);

  /* ---------------------------------------------------------------- */
  /*  Mouse interaction handlers                                       */
  /* ---------------------------------------------------------------- */
  const handleCanvasMouseDown = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const hit = hitTest(e.clientX, e.clientY);
    if (hit) {
      // Clicking a node
      setSelectedNode(hit.id);
      return;
    }
    // Start panning
    isDraggingRef.current = true;
    dragStartRef.current = {
      x: e.clientX - panRef.current.x,
      y: e.clientY - panRef.current.y,
    };
  }, [hitTest]);

  const handleCanvasMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!isDraggingRef.current) return;
    const newPan = {
      x: e.clientX - dragStartRef.current.x,
      y: e.clientY - dragStartRef.current.y,
    };
    setPanOffset(newPan);
  }, []);

  const handleCanvasMouseUp = useCallback(() => {
    isDraggingRef.current = false;
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();

    // Mouse position relative to canvas
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const direction = e.deltaY < 0 ? 1 : -1;
    const factor = 1 + direction * 0.1;
    const newZoom = Math.max(0.3, Math.min(5, zoomRef.current * factor));

    // Zoom toward mouse position
    const scale = newZoom / zoomRef.current;
    const newPanX = mx - (mx - panRef.current.x) * scale;
    const newPanY = my - (my - panRef.current.y) * scale;

    setZoom(newZoom);
    setPanOffset({ x: newPanX, y: newPanY });
  }, []);

  /* ---------------------------------------------------------------- */
  /*  Touch interaction handlers                                       */
  /* ---------------------------------------------------------------- */
  const handleTouchStart = useCallback((e: React.TouchEvent<HTMLCanvasElement>) => {
    if (e.touches.length === 1) {
      const touch = e.touches[0];
      const hit = hitTest(touch.clientX, touch.clientY);
      if (hit) {
        setSelectedNode(hit.id);
        return;
      }
      isDraggingRef.current = true;
      dragStartRef.current = {
        x: touch.clientX - panRef.current.x,
        y: touch.clientY - panRef.current.y,
      };
    } else if (e.touches.length === 2) {
      // Pinch zoom start
      isDraggingRef.current = false;
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      lastPinchDistRef.current = Math.sqrt(dx * dx + dy * dy);
    }
  }, [hitTest]);

  const handleTouchMove = useCallback((e: React.TouchEvent<HTMLCanvasElement>) => {
    e.preventDefault();
    if (e.touches.length === 1 && isDraggingRef.current) {
      const touch = e.touches[0];
      const newPan = {
        x: touch.clientX - dragStartRef.current.x,
        y: touch.clientY - dragStartRef.current.y,
      };
      setPanOffset(newPan);
    } else if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (lastPinchDistRef.current > 0) {
        const scale = dist / lastPinchDistRef.current;
        const newZoom = Math.max(0.3, Math.min(5, zoomRef.current * scale));

        // Pinch center
        const cx = (e.touches[0].clientX + e.touches[1].clientX) / 2;
        const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
        const canvas = canvasRef.current;
        if (canvas) {
          const rect = canvas.getBoundingClientRect();
          const mx = cx - rect.left;
          const my = cy - rect.top;
          const zoomScale = newZoom / zoomRef.current;
          const newPanX = mx - (mx - panRef.current.x) * zoomScale;
          const newPanY = my - (my - panRef.current.y) * zoomScale;
          setPanOffset({ x: newPanX, y: newPanY });
        }
        setZoom(newZoom);
      }
      lastPinchDistRef.current = dist;
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    isDraggingRef.current = false;
    lastPinchDistRef.current = 0;
  }, []);

  /* ---------------------------------------------------------------- */
  /*  Zoom controls                                                    */
  /* ---------------------------------------------------------------- */
  const handleZoomIn = () => setZoom(z => Math.min(z * 1.2, 5));
  const handleZoomOut = () => setZoom(z => Math.max(z / 1.2, 0.3));
  const handleReset = () => {
    setZoom(1);
    setPanOffset({ x: 0, y: 0 });
  };

  /* ---------------------------------------------------------------- */
  /*  Filtered nodes for display count and search                     */
  /* ---------------------------------------------------------------- */
  const filteredNodes = searchQuery
    ? nodes.filter((n: GraphNode) => n.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : nodes;

  const selectedNodeData = nodes.find((n: GraphNode) => n.id === selectedNode);

  /* ---------------------------------------------------------------- */
  /*  Resources handler                                                */
  /* ---------------------------------------------------------------- */
  const handleShowResources = async (topicName: string, type: 'note' | 'link') => {
    setSelectedResourceTopic(topicName);
    setResourceType(type);
    setShowResources(true);
    setResourcesLoading(true);
    setResources([]);

    try {
      const response = await api.get(`/ feed / resources / ${encodeURIComponent(topicName)}?resource_type = ${type === 'link' ? 'article' : 'notes'} `);

      const allResources = response.data.resources || [];
      const filtered = allResources.filter((r: any) => {
        if (type === 'note') return r.type === 'note' || r.type === 'saved_response';
        if (type === 'link') return r.resource_type === 'article' || r.resource_type === 'youtube' || r.resource_type === 'documentation';
        return true;
      });

      setResources(filtered);
    } catch (error) {
      console.error("Failed to fetch resources:", error);
    } finally {
      setResourcesLoading(false);
    }
  };

  /* ---------------------------------------------------------------- */
  /*  Quiz functions                                                   */
  /* ---------------------------------------------------------------- */
  const handleQuizMe = async (topicName: string, e?: React.MouseEvent) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    await startQuizForTopic(topicName);
  };

  /* ---------------------------------------------------------------- */
  /*  Loading / Error states                                           */
  /* ---------------------------------------------------------------- */
  if (loading) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-black/90 text-white">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
          <p className="text-sm text-gray-400">Loading Knowledge Graph...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-black/90 text-white">
        <div className="flex flex-col items-center gap-4">
          <XCircle className="w-8 h-8 text-red-500" />
          <p className="text-sm text-red-400">{error}</p>
        </div>
      </div>
    );
  }

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */
  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* Search Bar */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative mb-4"
      >
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search concepts to quiz..."
          className="w-full pl-10 pr-4 py-3 rounded-full glass-surface text-white placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50"
        />
        {searchQuery.trim() && (
          <button
            onClick={() => handleQuizMe(searchQuery)}
            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 px-3 py-1.5 bg-[#B6FF2E] text-black rounded-full text-xs font-medium hover:bg-[#c5ff4d] transition-colors"
          >
            <Target className="w-3 h-3" />
            Quiz Me
          </button>
        )}
      </motion.div>

      {/* Graph Canvas */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1 }}
        className="flex-1 rounded-3xl overflow-hidden border border-white/10 relative bg-[#0a0a0f]"
        style={{ minHeight: '300px' }}
        ref={containerRef}
      >
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
          style={{ cursor: isDraggingRef.current ? 'grabbing' : 'grab' }}
          onMouseDown={handleCanvasMouseDown}
          onMouseMove={handleCanvasMouseMove}
          onMouseUp={handleCanvasMouseUp}
          onMouseLeave={handleCanvasMouseUp}
          onWheel={handleWheel}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        />

        {/* Zoom Controls */}
        <div className="absolute bottom-4 right-4 flex flex-col gap-2 z-10">
          <button
            onClick={handleZoomIn}
            className="w-10 h-10 rounded-full glass-surface flex items-center justify-center hover:bg-white/10 transition-colors"
          >
            <ZoomIn className="w-4 h-4 text-white/70" />
          </button>
          <button
            onClick={handleZoomOut}
            className="w-10 h-10 rounded-full glass-surface flex items-center justify-center hover:bg-white/10 transition-colors"
          >
            <ZoomOut className="w-4 h-4 text-white/70" />
          </button>
          <button
            onClick={handleReset}
            className="w-10 h-10 rounded-full glass-surface flex items-center justify-center hover:bg-white/10 transition-colors"
          >
            <RotateCw className="w-4 h-4 text-white/70" />
          </button>
        </div>

        {/* Instructions */}
        <div className="absolute bottom-4 left-4 glass-surface rounded-xl px-3 py-2 z-10">
          <p className="text-xs text-white/60">
            Drag to pan &bull; Click nodes to focus &bull; Scroll to zoom
          </p>
        </div>

        {/* Empty state */}
        {nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none">
            <div className="text-center">
              <p className="text-white/40 text-sm">No concepts yet.</p>
              <p className="text-white/30 text-xs mt-1">Add content to build your knowledge graph.</p>
            </div>
          </div>
        )}
      </motion.div>

      {/* Filters */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mt-4"
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-white/50">
            Viewing: {filteredNodes.length} concepts
          </span>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-1 text-xs text-[#B6FF2E] hover:text-[#c5ff4d] transition-colors"
          >
            <Filter className="w-3 h-3" />
            Filters
            <ChevronDown className={`w - 3 h - 3 transition - transform ${showFilters ? 'rotate-180' : ''} `} />
          </button>
        </div>

        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="flex gap-2"
          >
            {['Domain', 'Mastery', 'Complexity'].map((filter) => (
              <button
                key={filter}
                className="px-3 py-1.5 rounded-full text-xs bg-white/5 text-white/70 border border-white/10 hover:bg-white/10 transition-colors"
              >
                {filter}
              </button>
            ))}
          </motion.div>
        )}
      </motion.div>

      {/* Selected Node Panel */}
      {selectedNodeData && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 glass-surface rounded-2xl p-4"
        >
          <div className="flex items-start justify-between mb-3">
            <div>
              <h3 className="font-heading font-bold text-white">{selectedNodeData.name}</h3>
              <p className="text-xs text-white/50 mt-1">
                Mastery: {selectedNodeData.mastery}%
              </p>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="p-1 rounded-full hover:bg-white/10 transition-colors"
            >
              <X className="w-4 h-4 text-white/50" />
            </button>
          </div>

          <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mb-3">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${selectedNodeData.mastery}% `,
                backgroundColor: selectedNodeData.color
              }}
            />
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2">
            <button
              onClick={() => handleQuizMe(selectedNodeData.name)}
              className="flex-1 py-2 rounded-xl bg-[#B6FF2E]/20 text-[#B6FF2E] text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-[#B6FF2E]/30 transition-colors"
            >
              <Target className="w-3 h-3" />
              Quiz Me
            </button>
            <button
              onClick={() => handleShowResources(selectedNodeData.name, 'note')}
              className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-white/10 transition-colors"
            >
              <BookOpen className="w-3 h-3" />
              Notes
            </button>
            <button
              onClick={() => handleShowResources(selectedNodeData.name, 'link')}
              className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-white/10 transition-colors"
            >
              <Link2 className="w-3 h-3" />
              Links
            </button>
          </div>

          {/* Linked Notes Section */}
          {linkedNotesLoading ? (
            <div className="mt-3 flex justify-center">
              <Loader2 className="w-4 h-4 animate-spin text-white/30" />
            </div>
          ) : linkedNotes.length > 0 ? (
            <div className="mt-3 pt-3 border-t border-white/10">
              <p className="text-[10px] text-white/40 uppercase tracking-wider mb-2">Linked Notes</p>
              <div className="space-y-1.5 max-h-[120px] overflow-y-auto">
                {linkedNotes.map((note: any) => (
                  <div
                    key={note.id}
                    className="p-2 rounded-lg bg-white/5 border border-white/5 hover:bg-white/10 transition-colors cursor-pointer"
                    onClick={() => setSelectedNoteDetail(note)}
                  >
                    <p className="text-xs text-white/80 font-medium truncate">{note.title}</p>
                    <p className="text-[10px] text-white/40 truncate mt-0.5">{note.preview}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Connected Concepts */}
          {nodeConnections.length > 0 && (
            <div className="mt-3 pt-3 border-t border-white/10">
              <p className="text-[10px] text-white/40 uppercase tracking-wider mb-2">Connected Concepts</p>
              <div className="flex flex-wrap gap-1.5">
                {nodeConnections.map((conn: any, i: number) => (
                  <button
                    key={i}
                    onClick={() => setSelectedNode(conn.concept?.id)}
                    className="px-2 py-1 rounded-full text-[10px] bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 transition-colors flex items-center gap-1"
                  >
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: selectedNodeData.color }} />
                    {conn.concept?.name}
                  </button>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      )}

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



      {/* Note Detail Modal */}
      <AnimatePresence>
        {selectedNoteDetail && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-end sm:items-center justify-center p-4"
            onClick={() => setSelectedNoteDetail(null)}
          >
            <motion.div
              initial={{ y: 100, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              exit={{ y: 100, opacity: 0 }}
              className="bg-[#1a1a2e] rounded-2xl border border-white/10 w-full max-w-lg max-h-[70vh] overflow-hidden flex flex-col"
              onClick={(e: React.MouseEvent) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-white/10">
                <div className="flex items-center gap-2 min-w-0">
                  <FileText className="w-4 h-4 text-[#2EFFE6] flex-shrink-0" />
                  <h3 className="text-white font-medium text-sm truncate">{selectedNoteDetail.title || 'Untitled Note'}</h3>
                </div>
                <button
                  onClick={() => setSelectedNoteDetail(null)}
                  className="p-1.5 rounded-full bg-white/5 hover:bg-white/10 transition-colors flex-shrink-0"
                >
                  <X className="w-4 h-4 text-white/60" />
                </button>
              </div>

              {/* Metadata */}
              <div className="px-4 py-2 flex items-center gap-3 text-[10px] text-white/40 border-b border-white/5">
                {selectedNoteDetail.resource_type && (
                  <span className="px-2 py-0.5 rounded-full bg-[#2EFFE6]/10 text-[#2EFFE6]">
                    {selectedNoteDetail.resource_type}
                  </span>
                )}
                {selectedNoteDetail.created_at && (
                  <span>{new Date(selectedNoteDetail.created_at).toLocaleDateString()}</span>
                )}
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-4">
                <p className="text-white/70 text-sm leading-relaxed whitespace-pre-wrap">
                  {selectedNoteDetail.preview || selectedNoteDetail.content_text || 'No content available.'}
                </p>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
