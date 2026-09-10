/* GraphRecall iOS force-graph boot — visual parity toward web GraphVisualizer */
(function () {
  const ACCENT = '#B6FF2E';
  const CANVAS = '#07070A';
  const DOMAIN_COLORS = {
    'Machine Learning': '#7C3AED',
    'Mathematics': '#3B82F6',
    'Computer Science': '#10B981',
    'Database Systems': '#F59E0B',
    'System Design': '#EF4444',
    'Programming': '#06B6D4',
    'Statistics': '#8B5CF6',
    'Learning Science': '#2EFFE6',
    'General': '#6B7280'
  };
  const DYNAMIC_PALETTE = [
    '#E11D48', '#DB2777', '#C026D3', '#7C3AED', '#4F46E5',
    '#2563EB', '#0284C7', '#0891B2', '#0D9488', '#059669',
    '#16A34A', '#65A30D', '#CA8A04', '#D97706', '#EA580C', '#DC2626'
  ];
  const REL_COLORS = {
    PREREQUISITE_OF: '#2EFFE6',
    SUBTOPIC_OF: '#9B59B6',
    BUILDS_ON: '#F59E0B',
    RELATED_TO: '#FFFFFF',
    PART_OF: '#EC4899',
    USES: '#3B82F6',
    ORCHESTRATED_BY: '#7C3AED',
    SUPPORTS: '#10B981'
  };
  const COMM_PALETTE = [
    '#7C3AED', '#3B82F6', '#10B981', '#F59E0B', '#EF4444',
    '#06B6D4', '#8B5CF6', '#B6FF2E', '#EC4899', '#2EFFE6'
  ];

  function domainColor(domain) {
    if (!domain) return DOMAIN_COLORS.General;
    if (DOMAIN_COLORS[domain]) return DOMAIN_COLORS[domain];
    let h = 0;
    for (let i = 0; i < domain.length; i++) h = (h * 31 + domain.charCodeAt(i)) >>> 0;
    return DYNAMIC_PALETTE[h % DYNAMIC_PALETTE.length];
  }

  function post(msg) {
    try { window.webkit.messageHandlers.graphBridge.postMessage(msg); } catch (e) {}
  }

  /* ---------- Galaxy starfield (2D stand-in for GalaxyBackground.tsx) ---------- */
  const starsCanvas = document.getElementById('stars');
  const sctx = starsCanvas.getContext('2d');
  let stars = [];
  let starT = 0;

  function resizeStars() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    starsCanvas.width = Math.floor(window.innerWidth * dpr);
    starsCanvas.height = Math.floor(window.innerHeight * dpr);
    starsCanvas.style.width = window.innerWidth + 'px';
    starsCanvas.style.height = window.innerHeight + 'px';
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.min(2200, Math.floor((window.innerWidth * window.innerHeight) / 280));
    stars = Array.from({ length: count }, () => {
      const t = Math.random();
      return {
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        r: 0.4 + Math.random() * 1.2,
        a: 0.12 + Math.random() * 0.35,
        speed: 0.02 + Math.random() * 0.06,
        // cool cyan/teal palette matching web GalaxyBackground
        c: `rgba(${Math.floor(64 + 40 * t)},${Math.floor(140 + 64 * t)},${Math.floor(217 + 25 * t)},`
      };
    });
  }

  function drawStars() {
    starT += 0.005;
    sctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    sctx.fillStyle = CANVAS;
    sctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
    for (const s of stars) {
      const tw = s.a * (0.75 + 0.25 * Math.sin(starT * 40 + s.x));
      sctx.beginPath();
      sctx.fillStyle = s.c + tw + ')';
      sctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      sctx.fill();
      s.x += s.speed * 0.15;
      if (s.x > window.innerWidth + 2) s.x = -2;
    }
    requestAnimationFrame(drawStars);
  }

  /* ---------- State ---------- */
  let rawNodes = [];
  let rawLinks = [];
  let communities = [];
  let highlightIds = new Set();
  let focusIds = new Set();
  let selectedId = null;
  let showCommunities = true;
  let selectedDomain = '';
  let minWeight = 0;
  let isDemo = false;
  let neighborIds = new Set();

  const root = document.getElementById('graph');
  const domainSelect = document.getElementById('domainSelect');
  const weightSlider = document.getElementById('weightSlider');
  const weightLabel = document.getElementById('weightLabel');
  const commToggle = document.getElementById('commToggle');
  const badge = document.getElementById('badge');
  const statNodes = document.getElementById('statNodes');
  const statLinks = document.getElementById('statLinks');

  const Graph = ForceGraph()(root)
    .backgroundColor('rgba(0,0,0,0)')
    .nodeId('id')
    .nodeLabel((n) => n.name || n.id)
    .linkDirectionalArrowLength((l) => {
      const t = (l.type || l.relationshipType || '').toUpperCase();
      return (t === 'PREREQUISITE_OF' || t === 'BUILDS_ON' || t === 'PART_OF' || t === 'SUBTOPIC_OF') ? 4.5 : 0;
    })
    .linkDirectionalArrowRelPos(0.92)
    .linkDirectionalParticles((l) => (l.__hot ? 2 : 0))
    .linkDirectionalParticleWidth((l) => (l.__hot ? 2.2 : 1.1))
    .linkDirectionalParticleSpeed(0.0045)
    .cooldownTicks(90)
    .d3AlphaDecay(0.022)
    .d3VelocityDecay(0.35)
    .onNodeClick((n) => {
      selectedId = n.id;
      recomputeNeighbors();
      applyGraph();
      post({ id: n.id });
    })
    .onBackgroundClick(() => {
      selectedId = null;
      neighborIds = new Set();
      applyGraph();
      post({ id: null });
    })
    .nodeCanvasObject((node, ctx, globalScale) => {
      const label = node.name || node.id;
      // Web calculateNodeSize maps ~1.5–10; scale for 2D canvas readability.
      const val = node.val || 1;
      const r = Math.max(3.2, Math.min(14, Math.sqrt(val) * 4.8));
      const isSel = selectedId === node.id;
      const isHl = highlightIds.has(node.id) || neighborIds.has(node.id) || focusIds.has(node.id);
      const dimmed = focusIds.size > 0 && !focusIds.has(node.id) && !isSel;
      const color = node.__highlight ? ACCENT : (node.color || domainColor(node.domain));

      ctx.save();
      if (dimmed) ctx.globalAlpha = 0.22;

      // glow bloom (web UnrealBloom stand-in)
      const glow = ctx.createRadialGradient(node.x, node.y, r * 0.2, node.x, node.y, r * (isSel ? 3.4 : 2.35));
      glow.addColorStop(0, color + 'dd');
      glow.addColorStop(0.4, color + '66');
      glow.addColorStop(1, color + '00');
      ctx.beginPath();
      ctx.fillStyle = glow;
      ctx.arc(node.x, node.y, r * (isSel ? 3.4 : 2.35), 0, Math.PI * 2);
      ctx.fill();

      // emissive core
      ctx.beginPath();
      ctx.fillStyle = color;
      ctx.arc(node.x, node.y, r * (isSel ? 1.35 : isHl ? 1.15 : 1), 0, Math.PI * 2);
      ctx.fill();

      // soft inner highlight
      ctx.beginPath();
      ctx.fillStyle = 'rgba(255,255,255,0.22)';
      ctx.arc(node.x - r * 0.25, node.y - r * 0.25, r * 0.35, 0, Math.PI * 2);
      ctx.fill();

      if (isSel) {
        ctx.beginPath();
        ctx.strokeStyle = ACCENT;
        ctx.lineWidth = 1.6 / globalScale;
        ctx.arc(node.x, node.y, r * 1.75, 0, Math.PI * 2);
        ctx.stroke();
      }

      const fontSize = Math.max(10 / globalScale, 2.6);
      if (!dimmed && (globalScale > 0.55 || isSel || isHl)) {
        ctx.font = `${isSel ? 600 : 500} ${fontSize}px -apple-system, system-ui, sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillStyle = isSel || isHl ? '#ffffff' : 'rgba(255,255,255,0.78)';
        ctx.strokeStyle = 'rgba(0,0,0,0.75)';
        ctx.lineWidth = 3 / globalScale;
        const text = label.length > 28 ? label.slice(0, 28) + '…' : label;
        ctx.strokeText(text, node.x, node.y + r + 2);
        ctx.fillText(text, node.x, node.y + r + 2);
      }
      ctx.restore();
    })
    .nodePointerAreaPaint((node, color, ctx) => {
      const r = Math.max(4, Math.sqrt(node.val || 1) * 6);
      ctx.beginPath();
      ctx.fillStyle = color;
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
      ctx.fill();
    })
    .linkColor((l) => {
      if (l.__hot) return 'rgba(255,255,255,0.9)';
      const t = (l.type || l.relationshipType || '').toUpperCase();
      const c = REL_COLORS[t];
      if (c) {
        if (c === '#FFFFFF') return 'rgba(255,255,255,0.45)';
        return c + '99';
      }
      return 'rgba(182,255,46,0.28)';
    })
    .linkWidth((l) => {
      // web: max(0.2, min(2.5, weight * 0.15)); 2D needs a larger scale factor
      const w = l.strength != null ? l.strength : 0.5;
      const base = Math.max(0.5, Math.min(3.2, w * 2.2));
      return l.__hot ? base * 1.7 : base;
    })
    .onRenderFramePre((ctx, globalScale) => {
      if (!showCommunities || !communities.length) return;
      const nodesById = {};
      for (const n of Graph.graphData().nodes) nodesById[n.id] = n;
      communities.forEach((comm, idx) => {
        const ids = comm.entity_ids || comm.entityIds || [];
        const pts = ids.map((id) => nodesById[id]).filter((n) => n && typeof n.x === 'number');
        if (pts.length < 2) return;
        let cx = 0, cy = 0;
        for (const p of pts) { cx += p.x; cy += p.y; }
        cx /= pts.length; cy /= pts.length;
        let maxR = 0;
        for (const p of pts) {
          const d = Math.hypot(p.x - cx, p.y - cy);
          if (d > maxR) maxR = d;
        }
        const color = COMM_PALETTE[idx % COMM_PALETTE.length];
        const pad = 18;
        // soft community glow (web CommunityGlow)
        const g = ctx.createRadialGradient(cx, cy, maxR * 0.2, cx, cy, maxR + pad);
        g.addColorStop(0, color + '22');
        g.addColorStop(1, color + '00');
        ctx.beginPath();
        ctx.fillStyle = g;
        ctx.arc(cx, cy, maxR + pad, 0, Math.PI * 2);
        ctx.fill();
        // wireframe-ish ring (CommunityBoundary)
        ctx.beginPath();
        ctx.strokeStyle = color + '55';
        ctx.lineWidth = 1.2 / globalScale;
        ctx.setLineDash([4 / globalScale, 4 / globalScale]);
        ctx.arc(cx, cy, maxR + pad * 0.6, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
      });
    });

  function recomputeNeighbors() {
    neighborIds = new Set();
    if (!selectedId) return;
    for (const l of rawLinks) {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      if (s === selectedId) neighborIds.add(t);
      if (t === selectedId) neighborIds.add(s);
    }
  }

  function filteredPayload() {
    let nodes = rawNodes.map((n) => Object.assign({}, n, {
      __highlight: highlightIds.has(n.id) || focusIds.has(n.id),
      color: n.color || domainColor(n.domain),
      val: n.val || n.size || Math.max(1.5, Math.min(10, 2 + (n.degree || 1) * 0.4 + 0.2))
    }));
    if (selectedDomain) nodes = nodes.filter((n) => n.domain === selectedDomain);
    const idSet = new Set(nodes.map((n) => n.id));
    let links = rawLinks
      .map((l) => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        const strength = l.strength != null ? l.strength : (l.weight != null ? l.weight : 0.5);
        const hot = selectedId && (s === selectedId || t === selectedId);
        return Object.assign({}, l, { source: s, target: t, strength, __hot: !!hot });
      })
      .filter((l) => idSet.has(l.source) && idSet.has(l.target) && (l.strength || 0) >= minWeight);
    return { nodes, links };
  }

  function refreshDomainOptions() {
    const domains = Array.from(new Set(rawNodes.map((n) => n.domain).filter(Boolean))).sort();
    const prev = domainSelect.value;
    domainSelect.innerHTML = '<option value="">All Domains</option>';
    domains.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d; opt.textContent = d;
      domainSelect.appendChild(opt);
    });
    if (domains.includes(prev)) domainSelect.value = prev;
  }

  function applyGraph(centerOnHighlight) {
    const data = filteredPayload();
    Graph.graphData(data);
    statNodes.textContent = `Nodes: ${data.nodes.length} / ${rawNodes.length}`;
    statLinks.textContent = `Links: ${data.links.length} / ${rawLinks.length}`;
    badge.classList.toggle('show', !!isDemo);
    if (centerOnHighlight && highlightIds.size === 1) {
      const id = [...highlightIds][0];
      const node = data.nodes.find((n) => n.id === id);
      if (node) {
        Graph.centerAt(node.x || 0, node.y || 0, 650);
        Graph.zoom(2.2, 650);
      }
    }
  }

  function resize() {
    Graph.width(window.innerWidth).height(window.innerHeight);
    resizeStars();
  }

  domainSelect.addEventListener('change', () => {
    selectedDomain = domainSelect.value || '';
    applyGraph();
    post({ type: 'filter', domain: selectedDomain || null, minWeight, showCommunities });
  });
  weightSlider.addEventListener('input', () => {
    minWeight = parseInt(weightSlider.value, 10) / 100;
    weightLabel.textContent = Math.round(minWeight * 100) + '%';
    applyGraph();
  });
  commToggle.addEventListener('click', () => {
    showCommunities = !showCommunities;
    commToggle.textContent = showCommunities ? 'On' : 'Off';
    commToggle.className = showCommunities ? 'on' : 'off';
    applyGraph();
  });
  document.getElementById('commRecompute').addEventListener('click', () => {
    // Re-layout: bump alpha so hulls settle again
    Graph.d3ReheatSimulation();
    post({ type: 'communities.recompute' });
  });

  window.addEventListener('resize', resize);
  resize();
  drawStars();

  function demoGraph() {
    return {
      nodes: [
        { id: 'n1', name: 'GraphRAG', definition: 'Retrieval over a knowledge graph', domain: 'Machine Learning', val: 1.6, color: '#7C3AED' },
        { id: 'n2', name: 'SM-2', definition: 'Spaced repetition algorithm', domain: 'Learning Science', val: 1.2, color: '#2EFFE6' },
        { id: 'n3', name: 'Neo4j', definition: 'Property graph store', domain: 'Database Systems', val: 1.3, color: '#F59E0B' },
        { id: 'n4', name: 'LangGraph', definition: 'Agent orchestration', domain: 'Machine Learning', val: 1.4, color: '#7C3AED' },
        { id: 'n5', name: 'Active Recall', definition: 'Practice by retrieving', domain: 'Learning Science', val: 1.1, color: '#2EFFE6' },
        { id: 'n6', name: 'Embeddings', definition: 'Vector representations', domain: 'Machine Learning', val: 1.25, color: '#7C3AED' },
        { id: 'n7', name: 'Cypher', definition: 'Graph query language', domain: 'Database Systems', val: 1.05, color: '#F59E0B' },
        { id: 'n8', name: 'Bloom', definition: 'Graph visualization', domain: 'Database Systems', val: 0.95, color: '#F59E0B' },
        { id: 'n9', name: 'Interleaving', definition: 'Mix practice topics', domain: 'Learning Science', val: 1.0, color: '#2EFFE6' },
        { id: 'n10', name: 'Force Layout', definition: 'Physics-based placement', domain: 'Computer Science', val: 1.15, color: '#10B981' }
      ],
      links: [
        { source: 'n1', target: 'n3', type: 'USES', strength: 0.9 },
        { source: 'n1', target: 'n4', type: 'ORCHESTRATED_BY', strength: 0.85 },
        { source: 'n1', target: 'n6', type: 'USES', strength: 0.8 },
        { source: 'n2', target: 'n5', type: 'SUPPORTS', strength: 0.88 },
        { source: 'n5', target: 'n1', type: 'RELATED_TO', strength: 0.6 },
        { source: 'n4', target: 'n3', type: 'RELATED_TO', strength: 0.55 },
        { source: 'n3', target: 'n7', type: 'PART_OF', strength: 0.7 },
        { source: 'n3', target: 'n8', type: 'RELATED_TO', strength: 0.5 },
        { source: 'n5', target: 'n9', type: 'RELATED_TO', strength: 0.65 },
        { source: 'n10', target: 'n1', type: 'RELATED_TO', strength: 0.45 },
        { source: 'n6', target: 'n4', type: 'BUILDS_ON', strength: 0.6 }
      ],
      communities: [
        { id: 'c1', title: 'Graph Stack', level: 0, entity_ids: ['n1', 'n3', 'n4', 'n6', 'n7', 'n8'], size: 6 },
        { id: 'c2', title: 'Learning Science', level: 0, entity_ids: ['n2', 'n5', 'n9'], size: 3 },
        { id: 'c3', title: 'Layout', level: 0, entity_ids: ['n10'], size: 1 }
      ]
    };
  }

  window.setGraphData = function (data, hlIds, opts) {
    opts = opts || {};
    const incoming = data || {};
    const nodes = incoming.nodes || [];
    const links = incoming.links || incoming.edges || [];
    isDemo = !!opts.demo || nodes.length === 0;
    const payload = isDemo ? demoGraph() : incoming;
    rawNodes = (payload.nodes || []).map((n) => Object.assign({}, n));
    rawLinks = (payload.links || payload.edges || []).map((l) => Object.assign({}, l));
    communities = payload.communities || [];
    highlightIds = new Set(hlIds || []);
    focusIds = new Set(opts.focusIds || []);
    if (opts.selectedId) selectedId = opts.selectedId;
    if (typeof opts.showCommunities === 'boolean') {
      showCommunities = opts.showCommunities;
      commToggle.textContent = showCommunities ? 'On' : 'Off';
      commToggle.className = showCommunities ? 'on' : 'off';
    }
    refreshDomainOptions();
    recomputeNeighbors();
    applyGraph(true);
  };

  window.setGraphFilters = function (opts) {
    opts = opts || {};
    if (typeof opts.showCommunities === 'boolean') {
      showCommunities = opts.showCommunities;
      commToggle.textContent = showCommunities ? 'On' : 'Off';
      commToggle.className = showCommunities ? 'on' : 'off';
    }
    if (opts.domain !== undefined) {
      selectedDomain = opts.domain || '';
      domainSelect.value = selectedDomain;
    }
    if (typeof opts.minWeight === 'number') {
      minWeight = opts.minWeight;
      weightSlider.value = String(Math.round(minWeight * 100));
      weightLabel.textContent = Math.round(minWeight * 100) + '%';
    }
    applyGraph();
  };

  // If native never pushes data, show demo after a beat
  setTimeout(function () {
    if (!rawNodes.length) {
      window.setGraphData(null, [], { demo: true });
    }
  }, 900);

  post({ type: 'ready' });
})();
