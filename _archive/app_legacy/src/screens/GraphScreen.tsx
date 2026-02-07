import { useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { Search, Filter, ChevronDown, X, Target, BookOpen, Link2, ZoomIn, ZoomOut, RotateCw } from 'lucide-react';
import { mockGraphNodes, mockGraphEdges } from '../data/mockData';
import type { GraphNode, GraphEdge } from '../types';

export function GraphScreen() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const containerRef = useRef<HTMLDivElement>(null);

  const filteredNodes = searchQuery 
    ? mockGraphNodes.filter(n => n.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : mockGraphNodes;

  const selectedNodeData = mockGraphNodes.find(n => n.id === selectedNode);

  const handleMouseDown = (e: React.MouseEvent) => {
    if (e.target === containerRef.current) {
      setIsDragging(true);
      dragStart.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDragging) {
      setPan({
        x: e.clientX - dragStart.current.x,
        y: e.clientY - dragStart.current.y,
      });
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  const handleZoomIn = () => setZoom(z => Math.min(z * 1.2, 3));
  const handleZoomOut = () => setZoom(z => Math.max(z / 1.2, 0.5));
  const handleReset = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

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
          placeholder="Search concepts..."
          className="w-full pl-10 pr-4 py-3 rounded-full glass-surface text-white placeholder:text-white/40 focus:outline-none focus:border-[#B6FF2E]/50"
        />
      </motion.div>

      {/* Graph Canvas */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1 }}
        className="flex-1 rounded-3xl overflow-hidden border border-white/10 relative bg-[#0a0a0f]"
        style={{ minHeight: '300px' }}
        ref={containerRef}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* Grid Background */}
        <div 
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage: `
              linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)
            `,
            backgroundSize: '40px 40px',
          }}
        />

        {/* Graph Content */}
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: 'center center',
            transition: isDragging ? 'none' : 'transform 0.3s ease-out',
          }}
        >
          <svg width="600" height="400" className="overflow-visible">
            {/* Edges */}
            {mockGraphEdges.map((edge: GraphEdge, i: number) => {
              const source = mockGraphNodes.find(n => n.id === edge.source);
              const target = mockGraphNodes.find(n => n.id === edge.target);
              if (!source || !target) return null;
              
              const sx = 300 + source.x * 30;
              const sy = 200 + source.y * 25;
              const tx = 300 + target.x * 30;
              const ty = 200 + target.y * 25;
              
              return (
                <line
                  key={i}
                  x1={sx}
                  y1={sy}
                  x2={tx}
                  y2={ty}
                  stroke="rgba(255,255,255,0.15)"
                  strokeWidth={1 + edge.strength}
                />
              );
            })}

            {/* Nodes */}
            {filteredNodes.map((node: GraphNode) => {
              const x = 300 + node.x * 30;
              const y = 200 + node.y * 25;
              const isSelected = selectedNode === node.id;
              
              return (
                <g 
                  key={node.id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedNode(node.id);
                  }}
                  className="cursor-pointer"
                >
                  {/* Glow */}
                  {(isSelected) && (
                    <circle
                      cx={x}
                      cy={y}
                      r={node.size * 25}
                      fill={node.color}
                      opacity={0.2}
                    />
                  )}
                  
                  {/* Node Circle */}
                  <circle
                    cx={x}
                    cy={y}
                    r={node.size * 15}
                    fill={node.color}
                    stroke={isSelected ? '#fff' : 'transparent'}
                    strokeWidth={2}
                    opacity={0.7 + (node.mastery / 200)}
                  />
                  
                  {/* Label */}
                  <text
                    x={x}
                    y={y + node.size * 25}
                    textAnchor="middle"
                    fill={isSelected ? '#B6FF2E' : 'rgba(255,255,255,0.7)'}
                    fontSize={12}
                    fontWeight={isSelected ? 600 : 400}
                  >
                    {node.name}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        {/* Controls */}
        <div className="absolute bottom-4 right-4 flex flex-col gap-2">
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
        <div className="absolute bottom-4 left-4 glass-surface rounded-xl px-3 py-2">
          <p className="text-xs text-white/60">
            Drag to pan • Click nodes to focus • Use controls to zoom
          </p>
        </div>
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
            <ChevronDown className={`w-3 h-3 transition-transform ${showFilters ? 'rotate-180' : ''}`} />
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
                width: `${selectedNodeData.mastery}%`,
                backgroundColor: selectedNodeData.color 
              }}
            />
          </div>

          <div className="flex gap-2">
            <button className="flex-1 py-2 rounded-xl bg-[#B6FF2E]/20 text-[#B6FF2E] text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-[#B6FF2E]/30 transition-colors">
              <Target className="w-3 h-3" />
              Practice
            </button>
            <button className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-white/10 transition-colors">
              <BookOpen className="w-3 h-3" />
              Notes
            </button>
            <button className="flex-1 py-2 rounded-xl bg-white/5 text-white/70 text-xs font-medium flex items-center justify-center gap-1.5 hover:bg-white/10 transition-colors">
              <Link2 className="w-3 h-3" />
              Links
            </button>
          </div>
        </motion.div>
      )}
    </div>
  );
}
