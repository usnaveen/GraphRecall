/*
 * GraphRecall iOS graph scene — a calm, touch-first take on the web GraphVisualizer.
 * Build: `npm run build` in ios/Tools/graph3d → ios/WebAssets/graph3d.bundle.js
 *
 * Two states:
 *   Overview — the 3D force layout (d3-force-3d), orbit camera, links tinted by relationship type.
 *   Focus    — tap a concept and the scene flattens to 2D: that concept centres, its connections
 *              fan out on one plane facing the camera (what it needs above, what it unlocks below,
 *              everything else to the sides), each edge arrowed for direction and coloured by type;
 *              the native legend names the colours. Rotation locks; pan and zoom stay. Deselecting
 *              animates back to the 3D overview.
 *
 * Bridge (native → page):
 *   window.setGraphData(raw)      /api/graph3d shape: { nodes, edges, communities }
 *   window.setGraphState(state)   { selectedId, highlightIds, visibleIds, domain, minWeight,
 *                                   colorMode, mergeMode, mergeTargetIds }
 *   window.setGraphInsets(bottom) fraction of the canvas covered by native UI at the bottom
 *   window.resetCamera()
 * Bridge (page → native, via webkit.messageHandlers.graphBridge):
 *   { type: 'ready' } · { type: 'select', id } · { type: 'mergeToggle', id }
 *   { type: 'createAt', x, y, z } · { type: 'layout', running, nodes }
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import * as d3 from 'd3-force-3d';

/* ---------------------------------------------------------------- constants */

const BACKGROUND = '#0a0a0f';
const ACCENT = '#B6FF2E';
const MERGE_TARGET_COLOR = '#F97316';
const FALLBACK_COLOR = '#7DE1FF';

/// Relationship colours and wording — kept in step with GraphRelationshipStyle.swift.
const REL_META = {
  PREREQUISITE_OF: { color: '#2EFFE6', label: 'prerequisite of' },
  SUBTOPIC_OF: { color: '#B07CD8', label: 'subtopic of' },
  BUILDS_ON: { color: '#F59E0B', label: 'builds on' },
  RELATED_TO: { color: '#E5E7EB', label: 'related to' },
  PART_OF: { color: '#EC4899', label: 'part of' },
  USES: { color: '#60A5FA', label: 'uses' },
  ORCHESTRATED_BY: { color: '#A78BFA', label: 'orchestrated by' },
  SUPPORTS: { color: '#34D399', label: 'supports' },
};
const relColor = (type) => (REL_META[type] || REL_META.RELATED_TO).color;

// Matches GraphViewModel.weakThreshold (0.4) and the native mastery legend.
const MASTERY_COLORS = { unseen: '#6B7280', weak: '#F87171', learning: '#F59E0B', strong: '#34D399' };
const COMMUNITY_PALETTE = [
  '#7C3AED', '#3B82F6', '#10B981', '#F59E0B', '#EF4444',
  '#06B6D4', '#EC4899', '#84CC16', '#8B5CF6', '#14B8A6',
];

const NODE_MIN_PX = 5;   // on-screen radius floor, so distant concepts stay visible and tappable
const NODE_MAX_PX = 20;  // ceiling, so zooming in never fills the screen with one sphere
const LABEL_LIMIT = 36;
const DIM_OPACITY = 0.14;
/// 2D focus layout: ring radius, extra ring spacing when crowded, and how fast things settle.
const FOCUS = { radius: 48, ringGap: 30, lerp: 0.16, perRing: 7 };

function post(message) {
  try { window.webkit.messageHandlers.graphBridge.postMessage(message); } catch (e) { /* not in WKWebView */ }
}

function masteryColor(mastery) {
  if (mastery == null || mastery <= 0) return MASTERY_COLORS.unseen;
  if (mastery < 0.4) return MASTERY_COLORS.weak;
  if (mastery < 0.7) return MASTERY_COLORS.learning;
  return MASTERY_COLORS.strong;
}

const nodeRadius = (node) => 1.6 + (node.size ?? 1) * 1.1 + Math.min(node.degree, 12) * 0.18;

/* ---------------------------------------------------------------- data */

function adaptGraph(raw) {
  const rawNodes = (raw && raw.nodes) || [];
  const rawEdges = (raw && (raw.edges || raw.links)) || [];
  const nodes = rawNodes.map((n) => ({
    id: String(n.id),
    title: n.name || n.label || 'Concept',
    domain: n.domain || 'General',
    color: n.color || FALLBACK_COLOR,
    mastery: typeof n.mastery_level === 'number' ? n.mastery_level : null,
    size: typeof n.size === 'number' ? n.size : 1,
    seed: typeof n.x === 'number' && typeof n.y === 'number' && typeof n.z === 'number'
      ? { x: n.x, y: n.y, z: n.z }
      : null,
    communityIndex: -1,
    degree: 0,
  }));
  const byId = new Map(nodes.map((n) => [n.id, n]));

  const links = [];
  for (const e of rawEdges) {
    const source = byId.get(String(e.source));
    const target = byId.get(String(e.target));
    if (!source || !target || source === target) continue;
    source.degree += 1;
    target.degree += 1;
    links.push({
      id: String(e.id || `${e.source}-${e.target}`),
      source,
      target,
      type: String(e.relationship_type || e.type || 'RELATED_TO').toUpperCase(),
      weight: typeof e.strength === 'number' ? e.strength : 0.6,
    });
  }

  // Community colour mode uses each concept's most specific (lowest-level) community.
  const communities = ((raw && raw.communities) || []).slice().sort((a, b) => (a.level ?? 0) - (b.level ?? 0));
  communities.forEach((community, index) => {
    for (const id of community.entity_ids || []) {
      const node = byId.get(String(id));
      if (node && node.communityIndex < 0) node.communityIndex = index;
    }
  });
  return { nodes, links };
}

/* ---------------------------------------------------------------- layout */

// A timer rather than requestAnimationFrame: rAF pauses while the web view is off screen, which
// would stall a layout that started before the user switched tabs.
const yieldToPage = () => new Promise((resolve) => setTimeout(resolve, 0));

async function layoutGraph(graph, previous, isStale) {
  const { nodes, links } = graph;
  const count = Math.max(nodes.length, 1);
  const golden = Math.PI * (3 - Math.sqrt(5));
  let reused = 0;
  nodes.forEach((node, i) => {
    const prev = previous.get(node.id);
    if (prev) {
      node.x = prev.x; node.y = prev.y; node.z = prev.z;
      reused += 1;
    } else if (node.seed) {
      // Backend positions come from a 400-unit spring layout; shrink them into a compact seed.
      node.x = node.seed.x * 0.25; node.y = node.seed.y * 0.25; node.z = node.seed.z * 0.25;
    } else {
      const t = (i + 0.5) / count;
      const r = 60 * Math.cbrt(t);
      const phi = Math.acos(1 - 2 * t);
      node.x = r * Math.sin(phi) * Math.cos(golden * i);
      node.y = r * Math.sin(phi) * Math.sin(golden * i);
      node.z = r * Math.cos(phi);
    }
  });

  const simulation = d3.forceSimulation(nodes, 3)
    .stop()
    .alphaDecay(0.03)
    .alphaMin(0.002)
    .force('charge', d3.forceManyBody().strength((d) => -45 - Math.min(d.degree, 20) * 4).distanceMax(160))
    .force('link', d3.forceLink(links)
      .distance((l) => 18 + 14 * (1 - Math.min(1, l.weight)))
      .strength((l) => 0.25 + 0.35 * Math.min(1, l.weight)))
    .force('collide', d3.forceCollide().radius((d) => nodeRadius(d) + 3).iterations(2))
    .force('x', d3.forceX(0).strength(0.035))
    .force('y', d3.forceY(0).strength(0.035))
    .force('z', d3.forceZ(0).strength(0.035));
  if (nodes.length && reused === nodes.length) simulation.alpha(0.2);

  for (let i = 0; i < 500;) {
    const sliceEnd = Math.min(500, i + 25);
    for (; i < sliceEnd; i++) {
      simulation.tick();
      if (simulation.alpha() < 0.002) { i = 500; break; }
    }
    if (isStale()) return null;
    if (i < 500) await yieldToPage();
  }
  return graph;
}

/* ---------------------------------------------------------------- renderer */

const container = document.getElementById('graph');
const labelsEl = document.getElementById('labels');
const statusEl = document.getElementById('status');

const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setClearColor(BACKGROUND, 1);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 5000);
camera.position.set(0, 0, 220);
scene.add(camera);

scene.add(new THREE.AmbientLight(0xffffff, 1.1));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.4);
keyLight.position.set(0.4, 0.8, 1);
camera.add(keyLight); // lit from the viewer, so shading reads the same from every angle

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.rotateSpeed = 0.9;
controls.zoomSpeed = 1.2;
controls.panSpeed = 0.8;
controls.minDistance = 8;
controls.maxDistance = 3000;

const nodeLayer = new THREE.Group();
const linkLayer = new THREE.Group();
const arrowLayer = new THREE.Group();
const ringLayer = new THREE.Group();
scene.add(linkLayer, arrowLayer, nodeLayer, ringLayer);

const sphereGeometry = new THREE.SphereGeometry(1, 20, 14);
const ringGeometry = new THREE.RingGeometry(1.3, 1.6, 48);
const arrowGeometry = new THREE.ConeGeometry(0.42, 1.25, 10);

let width = 1;
let height = 1;
let needsRender = true;
const invalidate = () => { needsRender = true; };
controls.addEventListener('change', invalidate);

/* ---------------------------------------------------------------- state */

let graph = null;            // { nodes, links }
let objects = new Map();     // id -> { node, mesh, origin, target, radius, visible, dimmed, emphasis, pxRadius, label, ring }
let linkBatches = [];        // { mesh, links }
let arrows = [];             // { mesh, link }
let neighborIds = new Set();
let shownLabels = new Set();
let dataGeneration = 0;
let cameraFlight = null;     // { target, position, onArrive }
let viewShift = 0;
let insetBottom = 0;
let settling = false;        // node positions are animating

/// 2D focus: { id, targets: Map<id, Vector3>, members: Set<id>, links: [], radius }
let focusView = null;
let preFocusCamera = null;   // { position, target } to restore when leaving focus

const state = {
  selectedId: null,
  highlightIds: new Set(),
  visibleIds: null,
  domain: null,
  minWeight: 0,
  colorMode: 'domain',
  mergeMode: false,
  mergeTargetIds: new Set(),
};

const selectionRing = new THREE.Mesh(
  ringGeometry,
  new THREE.MeshBasicMaterial({ color: ACCENT, transparent: true, depthTest: false, side: THREE.DoubleSide }),
);
selectionRing.visible = false;
selectionRing.renderOrder = 10;
ringLayer.add(selectionRing);

function selectedObject() {
  return state.selectedId ? objects.get(state.selectedId) || null : null;
}

function isVisibleNode(node) {
  if (state.visibleIds && !state.visibleIds.has(node.id)) return false;
  if (state.domain && node.domain !== state.domain) return false;
  return true;
}

function linkPasses(link) {
  if (state.minWeight > 0 && link.weight < state.minWeight) return false;
  const source = objects.get(link.source.id);
  const target = objects.get(link.target.id);
  return !!source && !!target && isVisibleNode(link.source) && isVisibleNode(link.target);
}

function baseColor(node) {
  if (state.colorMode === 'mastery') return masteryColor(node.mastery);
  if (state.colorMode === 'community') {
    return node.communityIndex >= 0 ? COMMUNITY_PALETTE[node.communityIndex % COMMUNITY_PALETTE.length] : MASTERY_COLORS.unseen;
  }
  return node.color;
}

/* ---------------------------------------------------------------- scene building */

function disposeLinks() {
  for (const batch of linkBatches) {
    linkLayer.remove(batch.mesh);
    batch.mesh.geometry.dispose();
    batch.mesh.material.dispose();
  }
  linkBatches = [];
}

function disposeArrows() {
  for (const arrow of arrows) {
    arrowLayer.remove(arrow.mesh);
    arrow.mesh.material.dispose();
  }
  arrows = [];
}

function disposeScene() {
  for (const obj of objects.values()) {
    obj.mesh.material.dispose();
    if (obj.ring) { ringLayer.remove(obj.ring); obj.ring.material.dispose(); }
    if (obj.label) obj.label.remove();
  }
  nodeLayer.clear();
  disposeLinks();
  disposeArrows();
  objects = new Map();
  shownLabels = new Set();
}

function buildScene(newGraph) {
  disposeScene();
  graph = newGraph;
  for (const node of graph.nodes) {
    const mesh = new THREE.Mesh(sphereGeometry, new THREE.MeshLambertMaterial({ color: node.color, transparent: true }));
    mesh.position.set(node.x, node.y, node.z);
    mesh.userData.nodeId = node.id;
    nodeLayer.add(mesh);
    objects.set(node.id, {
      node,
      mesh,
      origin: new THREE.Vector3(node.x, node.y, node.z),
      target: new THREE.Vector3(node.x, node.y, node.z),
      radius: nodeRadius(node),
      visible: true,
      dimmed: false,
      emphasis: 1,
      pxRadius: NODE_MIN_PX,
      label: null,
      ring: null,
    });
  }
  applyState();
}

function setTargetRing(obj, on) {
  if (on && !obj.ring) {
    obj.ring = new THREE.Mesh(
      ringGeometry,
      new THREE.MeshBasicMaterial({ color: MERGE_TARGET_COLOR, transparent: true, depthTest: false, side: THREE.DoubleSide }),
    );
    obj.ring.renderOrder = 9;
    ringLayer.add(obj.ring);
  } else if (!on && obj.ring) {
    ringLayer.remove(obj.ring);
    obj.ring.material.dispose();
    obj.ring = null;
  }
}

/* ---------------------------------------------------------------- 2D focus view */

/** 0 = this concept comes first (a prerequisite / parent), 1 = it follows, 2 = related. */
function focusGroup(link, id) {
  const outgoing = link.source.id === id;
  switch (link.type) {
    case 'PREREQUISITE_OF':
    case 'USES':
      return outgoing ? 1 : 0;
    case 'BUILDS_ON':
    case 'SUBTOPIC_OF':
    case 'PART_OF':
      return outgoing ? 0 : 1;
    default:
      return 2;
  }
}

function placeArc(members, origin, arcCentre, spread, targets) {
  const perRing = FOCUS.perRing;
  const rings = Math.ceil(members.length / perRing) || 1;
  for (let ring = 0; ring < rings; ring++) {
    const slice = members.slice(ring * perRing, (ring + 1) * perRing);
    const radius = FOCUS.radius + ring * FOCUS.ringGap;
    slice.forEach((member, i) => {
      const t = slice.length === 1 ? 0.5 : i / (slice.length - 1);
      const angle = arcCentre - spread / 2 + t * spread;
      targets.set(member.other.id, new THREE.Vector3(
        origin.x + Math.cos(angle) * radius,
        origin.y + Math.sin(angle) * radius,
        origin.z,
      ));
    });
  }
}

/** Lays the selected concept's neighbourhood out on one plane: needs above, unlocks below, related to the sides. */
function buildFocusView(id) {
  const centre = objects.get(id);
  if (!centre || !graph) return null;
  const origin = centre.mesh.position.clone();

  // One entry per neighbour, keeping its strongest link.
  const byOther = new Map();
  for (const link of graph.links) {
    if (link.source.id !== id && link.target.id !== id) continue;
    if (!linkPasses(link)) continue;
    const other = link.source.id === id ? link.target : link.source;
    const existing = byOther.get(other.id);
    if (!existing || link.weight > existing.link.weight) {
      byOther.set(other.id, { link, other, group: focusGroup(link, id) });
    }
  }
  const members = [...byOther.values()].sort((a, b) => b.link.weight - a.link.weight);
  const targets = new Map([[id, origin.clone()]]);

  const needs = members.filter((m) => m.group === 0);
  const unlocks = members.filter((m) => m.group === 1);
  const related = members.filter((m) => m.group === 2);
  const right = related.filter((_, i) => i % 2 === 0);
  const left = related.filter((_, i) => i % 2 === 1);

  placeArc(needs, origin, Math.PI / 2, Math.PI * 0.62, targets);        // top
  placeArc(unlocks, origin, -Math.PI / 2, Math.PI * 0.62, targets);     // bottom
  placeArc(right, origin, 0, Math.PI * 0.42, targets);                  // right
  placeArc(left, origin, Math.PI, Math.PI * 0.42, targets);             // left

  const rings = Math.max(
    Math.ceil(needs.length / FOCUS.perRing),
    Math.ceil(unlocks.length / FOCUS.perRing),
    Math.ceil(right.length / FOCUS.perRing),
    Math.ceil(left.length / FOCUS.perRing),
    1,
  );
  return {
    id,
    origin,
    targets,
    members: new Set([id, ...byOther.keys()]),
    links: members.map((m) => m.link),
    radius: FOCUS.radius + (rings - 1) * FOCUS.ringGap,
  };
}

function enterFocus(id) {
  const view = buildFocusView(id);
  if (!view) return;
  if (!focusView) {
    preFocusCamera = { position: camera.position.clone(), target: controls.target.clone() };
  }
  focusView = view;
  // A flat view has nothing to orbit; keep pan and zoom.
  controls.enableRotate = false;
  settling = true;

  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const span = view.radius + 26;
  const distance = Math.max(70, span / Math.tan(Math.min(vFov, hFov) / 2));
  cameraFlight = {
    target: view.origin.clone(),
    position: view.origin.clone().add(new THREE.Vector3(0, 0, distance)),
  };
  invalidate();
}

function exitFocus() {
  if (!focusView) return;
  focusView = null;
  controls.enableRotate = true;
  settling = true;
  if (preFocusCamera) {
    cameraFlight = { target: preFocusCamera.target.clone(), position: preFocusCamera.position.clone() };
    preFocusCamera = null;
  }
  invalidate();
}

/* ---------------------------------------------------------------- state application */

function applyState() {
  if (!graph) return;
  const selected = selectedObject();
  const selectedId = selected ? selected.node.id : null;

  neighborIds = new Set();
  if (selectedId) {
    for (const link of graph.links) {
      if (link.source.id === selectedId) neighborIds.add(link.target.id);
      else if (link.target.id === selectedId) neighborIds.add(link.source.id);
    }
  }

  // Selection flattens the scene; deselection returns to the 3D overview.
  if (selectedId && !state.mergeMode) {
    if (!focusView || focusView.id !== selectedId) enterFocus(selectedId);
  } else if (focusView) {
    exitFocus();
  }

  const focusing = !!focusView;
  const searching = !selectedId && state.highlightIds.size > 0;

  for (const obj of objects.values()) {
    const { node, mesh } = obj;
    const passesFilters = isVisibleNode(node);
    // In focus the neighbourhood is the whole story — everything else steps out of the way.
    obj.visible = passesFilters && (!focusing || focusView.members.has(node.id));
    mesh.visible = obj.visible;
    obj.target.copy(focusing && focusView.targets.has(node.id) ? focusView.targets.get(node.id) : obj.origin);

    const isTarget = state.mergeTargetIds.has(node.id);
    obj.dimmed = obj.visible && !focusing && searching && !state.highlightIds.has(node.id);
    mesh.material.color.set(isTarget ? MERGE_TARGET_COLOR : baseColor(node));
    mesh.material.opacity = obj.dimmed ? DIM_OPACITY : 1;
    mesh.material.depthWrite = !obj.dimmed;
    mesh.renderOrder = obj.dimmed ? 0 : 1;
    obj.emphasis = node.id === selectedId ? 1.35 : isTarget || state.highlightIds.has(node.id) ? 1.15 : 1;
    setTargetRing(obj, isTarget && obj.visible);
  }
  selectionRing.visible = !!selected && selected.visible;

  settling = true;
  rebuildLinks(selectedId, searching);
  invalidate();
}

/* ---------------------------------------------------------------- links, arrows, edge labels */

const resolution = new THREE.Vector2(1, 1);

function rebuildLinks(selectedId, searching) {
  disposeLinks();
  disposeArrows();
  if (!graph) return;

  if (focusView) {
    // Focus: only this neighbourhood, each edge in its relationship colour with an arrow for
    // direction. The colours are named by the native legend, not by text on the lines.
    addLinkBatch(focusView.links, 2.4, 0.95, (link) => relColor(link.type));
    for (const link of focusView.links) {
      const mesh = new THREE.Mesh(
        arrowGeometry,
        new THREE.MeshBasicMaterial({ color: relColor(link.type), transparent: true, opacity: 0.95 }),
      );
      mesh.raycast = () => {};
      arrowLayer.add(mesh);
      arrows.push({ mesh, link });
    }
    return;
  }

  const hot = [];
  const idle = [];
  const faint = [];
  for (const link of graph.links) {
    if (!linkPasses(link)) continue;
    if (selectedId && (link.source.id === selectedId || link.target.id === selectedId)) {
      hot.push(link);
    } else if (searching && !(state.highlightIds.has(link.source.id) && state.highlightIds.has(link.target.id))) {
      faint.push(link);
    } else {
      idle.push(link);
    }
  }
  // Tinted by type even in the overview, so the variety of connections is visible at a glance.
  addLinkBatch(faint, 1, 0.06, (link) => relColor(link.type));
  addLinkBatch(idle, 1.2, 0.42, (link) => relColor(link.type));
  addLinkBatch(hot, 2.4, 0.95, (link) => relColor(link.type));
}

function addLinkBatch(links, linewidth, opacity, colorOf) {
  if (!links.length) return;
  const geometry = new LineSegmentsGeometry();
  geometry.setPositions(new Float32Array(links.length * 6));
  const colors = new Float32Array(links.length * 6);
  const color = new THREE.Color();
  links.forEach((link, i) => {
    color.set(colorOf(link));
    colors.set([color.r, color.g, color.b, color.r, color.g, color.b], i * 6);
  });
  geometry.setColors(colors);
  const material = new LineMaterial({ color: 0xffffff, vertexColors: true, linewidth, transparent: true, opacity, depthWrite: false });
  material.resolution.copy(resolution);
  const mesh = new LineSegments2(geometry, material);
  mesh.frustumCulled = false;
  mesh.raycast = () => {};
  linkLayer.add(mesh);
  const batch = { mesh, links };
  linkBatches.push(batch);
  writeLinkPositions(batch);
}

function writeLinkPositions(batch) {
  const buffer = batch.mesh.geometry.attributes.instanceStart.data;
  const array = buffer.array;
  batch.links.forEach((link, i) => {
    const s = objects.get(link.source.id).mesh.position;
    const t = objects.get(link.target.id).mesh.position;
    const o = i * 6;
    array[o] = s.x; array[o + 1] = s.y; array[o + 2] = s.z;
    array[o + 3] = t.x; array[o + 4] = t.y; array[o + 5] = t.z;
  });
  buffer.needsUpdate = true;
}

const arrowDirection = new THREE.Vector3();
const arrowUp = new THREE.Vector3(0, 1, 0);

function updateArrows() {
  for (const { mesh, link } of arrows) {
    const source = objects.get(link.source.id);
    const target = objects.get(link.target.id);
    if (!source || !target) continue;
    arrowDirection.copy(target.mesh.position).sub(source.mesh.position);
    const length = arrowDirection.length();
    if (length < 0.001) continue;
    arrowDirection.divideScalar(length);
    // Sit just off the target node so the head stays visible.
    const back = target.mesh.scale.x + 2.4;
    mesh.position.copy(target.mesh.position).addScaledVector(arrowDirection, -back);
    mesh.quaternion.setFromUnitVectors(arrowUp, arrowDirection);
    const scale = Math.max(1, target.pxRadius / 6);
    mesh.scale.setScalar(scale);
  }
}

/* ---------------------------------------------------------------- labels */

const measureContext = document.createElement('canvas').getContext('2d');

function labelFor(obj) {
  if (!obj.label) {
    const title = obj.node.title;
    const text = title.length > 28 ? `${title.slice(0, 27)}…` : title;
    const el = document.createElement('div');
    el.className = 'label';
    el.textContent = text;
    labelsEl.appendChild(el);
    measureContext.font = '600 11px -apple-system, system-ui, sans-serif';
    el.__width = measureContext.measureText(text).width + 8;
    el.__class = 'label';
    obj.label = el;
  }
  return obj.label;
}

const projected = new THREE.Vector3();

function placeLabels() {
  const selected = selectedObject();
  const selectedId = selected ? selected.node.id : null;
  const candidates = [];
  for (const obj of objects.values()) {
    if (!obj.visible || obj.dimmed) continue;
    const id = obj.node.id;
    let priority;
    if (id === selectedId) priority = 1e6;
    else if (selectedId && neighborIds.has(id)) priority = 1e5 + obj.node.degree;
    else if (state.highlightIds.has(id) || state.mergeTargetIds.has(id)) priority = 5e4 + obj.node.degree;
    else if (selectedId && !focusView) continue;
    else priority = obj.node.degree * 10 + obj.radius;
    candidates.push([priority, obj]);
  }
  candidates.sort((a, b) => b[0] - a[0]);

  const placed = [];
  const shown = new Set();
  // Other labels must not cover the selected concept itself.
  if (selected && selected.visible) {
    projected.copy(selected.mesh.position).project(camera);
    const sx = ((projected.x + 1) / 2) * width;
    const sy = ((1 - projected.y) / 2) * height;
    const r = selected.pxRadius + 4;
    placed.push([sx - r, sy - r, sx + r, sy + r]);
  }

  for (const [, obj] of candidates) {
    if (shown.size >= LABEL_LIMIT) break;
    projected.copy(obj.mesh.position).project(camera);
    if (projected.z > 1 || projected.x < -1.1 || projected.x > 1.1 || projected.y < -1.1 || projected.y > 1.1) continue;
    const isSelected = obj.node.id === selectedId;
    const label = labelFor(obj);
    const labelWidth = label.__width * (isSelected ? 13 / 11 : 1);
    // Keep labels inside the canvas instead of letting edge concepts lose half their name.
    const x = Math.min(Math.max(((projected.x + 1) / 2) * width, labelWidth / 2 + 4), width - labelWidth / 2 - 4);
    const y = ((1 - projected.y) / 2) * height + obj.pxRadius + 3;
    const rect = [x - labelWidth / 2, y, x + labelWidth / 2, y + (isSelected ? 18 : 15)];
    if (!isSelected && placed.some((p) => rect[0] < p[2] && rect[2] > p[0] && rect[1] < p[3] && rect[3] > p[1])) continue;
    placed.push(rect);
    shown.add(obj);
    const className = isSelected ? 'label selected' : neighborIds.has(obj.node.id) ? 'label neighbor' : 'label';
    if (label.__class !== className) { label.className = className; label.__class = className; }
    label.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translateX(-50%)`;
    label.style.display = 'block';
  }
  for (const obj of shownLabels) if (!shown.has(obj) && obj.label) obj.label.style.display = 'none';
  shownLabels = shown;
}

/* ---------------------------------------------------------------- rendering */

const forward = new THREE.Vector3();
const offset = new THREE.Vector3();

/** Eases nodes toward their targets — the flatten into 2D and the return to 3D. */
function animatePositions() {
  if (!settling) return false;
  let moving = false;
  for (const obj of objects.values()) {
    const distance = obj.mesh.position.distanceTo(obj.target);
    if (distance < 0.05) {
      obj.mesh.position.copy(obj.target);
      continue;
    }
    obj.mesh.position.lerp(obj.target, FOCUS.lerp);
    moving = true;
  }
  if (!moving) settling = false;
  return true;
}

function render() {
  const tanHalf = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  camera.getWorldDirection(forward);
  for (const obj of objects.values()) {
    if (!obj.visible) continue;
    const depth = Math.max(0.1, offset.copy(obj.mesh.position).sub(camera.position).dot(forward));
    const worldPerPx = (2 * depth * tanHalf) / height;
    const radius = Math.min(Math.max(obj.radius, NODE_MIN_PX * worldPerPx), NODE_MAX_PX * worldPerPx) * obj.emphasis;
    obj.mesh.scale.setScalar(radius);
    obj.pxRadius = radius / worldPerPx;
    if (obj.ring) {
      obj.ring.position.copy(obj.mesh.position);
      obj.ring.quaternion.copy(camera.quaternion);
      obj.ring.scale.setScalar(radius);
    }
  }
  const selected = selectedObject();
  if (selected && selectionRing.visible) {
    selectionRing.position.copy(selected.mesh.position);
    selectionRing.quaternion.copy(camera.quaternion);
    selectionRing.scale.setScalar(selected.mesh.scale.x);
  }
  for (const batch of linkBatches) writeLinkPositions(batch);
  updateArrows();
  renderer.render(scene, camera);
  placeLabels();
}

function applyViewOffset() {
  if (viewShift <= 0) camera.clearViewOffset();
  else camera.setViewOffset(width, height, 0, height * viewShift, width, height);
}

/** Eases the projection centre up so the focus stays centred in the part of the canvas native UI leaves free. */
function updateViewShift() {
  const goal = Math.min(0.4, Math.max(0, insetBottom / 2));
  if (Math.abs(goal - viewShift) < 0.0005) {
    if (viewShift === goal) return false;
    viewShift = goal;
  } else {
    viewShift += (goal - viewShift) * 0.18;
  }
  applyViewOffset();
  return true;
}

function tick() {
  requestAnimationFrame(tick);
  let animating = animatePositions();
  if (cameraFlight) {
    camera.position.lerp(cameraFlight.position, 0.14);
    controls.target.lerp(cameraFlight.target, 0.14);
    if (camera.position.distanceTo(cameraFlight.position) < 0.3) {
      camera.position.copy(cameraFlight.position);
      controls.target.copy(cameraFlight.target);
      cameraFlight = null;
    }
    animating = true;
  }
  const moved = controls.update();
  if (updateViewShift()) animating = true;
  // Render only while something changes — a still graph costs no GPU or battery.
  if (needsRender || animating || moved) {
    needsRender = false;
    render();
  }
}

/* ---------------------------------------------------------------- camera helpers */

function flyToNode(nodeId) {
  const obj = objects.get(nodeId);
  if (!obj) return;
  const target = obj.mesh.position.clone();
  const direction = camera.position.clone().sub(controls.target);
  const distance = THREE.MathUtils.clamp(direction.length(), 45, 150);
  cameraFlight = { target, position: target.clone().add(direction.normalize().multiplyScalar(distance)) };
  invalidate();
}

/** Frames every visible concept. */
function frameAll(animated) {
  const box = new THREE.Box3();
  for (const obj of objects.values()) if (obj.visible) box.expandByPoint(obj.mesh.position);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const half = box.getSize(new THREE.Vector3()).multiplyScalar(0.5).addScalar(10);
  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const distance = Math.max(40, half.x / Math.tan(hFov / 2) + half.z, half.y / Math.tan(vFov / 2) + half.z);
  controls.maxDistance = Math.max(600, distance * 2.5);
  camera.far = Math.max(2000, distance * 4);
  camera.updateProjectionMatrix();
  const position = center.clone().add(new THREE.Vector3(0, 0, distance));
  if (animated) {
    cameraFlight = { target: center, position };
  } else {
    cameraFlight = null;
    camera.position.copy(position);
    controls.target.copy(center);
    controls.update();
  }
  invalidate();
}

/* ---------------------------------------------------------------- touch: tap select, double-tap fly, long-press create */

const raycaster = new THREE.Raycaster();
const pointerNdc = new THREE.Vector2();
const pointers = new Map();
let gesture = null;
let lastEmptyTap = null;

function ndcFrom(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointerNdc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
  return rect;
}

function pickNode(clientX, clientY) {
  const rect = ndcFrom(clientX, clientY);
  raycaster.setFromCamera(pointerNdc, camera);
  const meshes = [];
  for (const obj of objects.values()) if (obj.visible) meshes.push(obj.mesh);
  const hit = raycaster.intersectObjects(meshes, false)[0];
  if (hit) return hit.object.userData.nodeId;

  // Fingers are bigger than small spheres: fall back to the nearest concept on screen.
  let best = null;
  let bestDistance = Infinity;
  for (const obj of objects.values()) {
    if (!obj.visible) continue;
    projected.copy(obj.mesh.position).project(camera);
    if (projected.z > 1) continue;
    const sx = rect.left + ((projected.x + 1) / 2) * rect.width;
    const sy = rect.top + ((1 - projected.y) / 2) * rect.height;
    const distance = Math.hypot(sx - clientX, sy - clientY);
    if (distance < Math.max(24, obj.pxRadius + 12) && distance < bestDistance) {
      bestDistance = distance;
      best = obj.node.id;
    }
  }
  return best;
}

/** World point under the finger, on the plane through the orbit target facing the camera. */
function worldPointAt(clientX, clientY) {
  ndcFrom(clientX, clientY);
  raycaster.setFromCamera(pointerNdc, camera);
  const normal = camera.getWorldDirection(new THREE.Vector3());
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, controls.target);
  return raycaster.ray.intersectPlane(plane, new THREE.Vector3()) || controls.target.clone();
}

function selectNode(id) {
  if (id === state.selectedId) return;
  state.selectedId = id;
  applyState();
  post({ type: 'select', id });
}

function handleTap(x, y) {
  const id = pickNode(x, y);
  if (id) {
    lastEmptyTap = null;
    if (state.mergeMode) post({ type: 'mergeToggle', id });
    else selectNode(id);
    return;
  }
  const now = performance.now();
  if (lastEmptyTap && now - lastEmptyTap.time < 320 && Math.hypot(x - lastEmptyTap.x, y - lastEmptyTap.y) < 36) {
    lastEmptyTap = null;
    const point = worldPointAt(x, y);
    let nearest = null;
    let min = Infinity;
    for (const obj of objects.values()) {
      if (!obj.visible) continue;
      const d = obj.mesh.position.distanceTo(point);
      if (d < min) { min = d; nearest = obj.node.id; }
    }
    if (nearest) flyToNode(nearest);
    return;
  }
  lastEmptyTap = { x, y, time: now };
  if (!state.mergeMode) selectNode(null);
}

function cancelGesture() {
  if (!gesture) return;
  gesture.cancelled = true;
  clearTimeout(gesture.longPressTimer);
}

renderer.domElement.addEventListener('pointerdown', (e) => {
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size > 1) { cancelGesture(); return; }
  cameraFlight = null; // touching the graph hands the camera back to the user
  const g = { x: e.clientX, y: e.clientY, time: performance.now(), cancelled: false, longPressed: false };
  g.longPressTimer = setTimeout(() => {
    if (g.cancelled || pointers.size !== 1) return;
    g.longPressed = true;
    if (pickNode(g.x, g.y)) return;
    const p = worldPointAt(g.x, g.y);
    post({ type: 'createAt', x: p.x, y: p.y, z: p.z });
  }, 520);
  gesture = g;
});

renderer.domElement.addEventListener('pointermove', (e) => {
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (gesture && !gesture.cancelled && Math.hypot(e.clientX - gesture.x, e.clientY - gesture.y) > 8) cancelGesture();
});

function endPointer(e, cancelled) {
  pointers.delete(e.pointerId);
  if (!gesture) return;
  const g = gesture;
  if (pointers.size === 0) gesture = null;
  clearTimeout(g.longPressTimer);
  if (cancelled || g.cancelled || g.longPressed) return;
  if (performance.now() - g.time > 400) return;
  handleTap(e.clientX, e.clientY);
}
renderer.domElement.addEventListener('pointerup', (e) => endPointer(e, false));
renderer.domElement.addEventListener('pointercancel', (e) => endPointer(e, true));
renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());

/* ---------------------------------------------------------------- sizing */

function resize() {
  width = Math.max(1, container.clientWidth);
  height = Math.max(1, container.clientHeight);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  applyViewOffset();
  resolution.set(width, height);
  for (const batch of linkBatches) batch.mesh.material.resolution.copy(resolution);
  invalidate();
}
new ResizeObserver(resize).observe(container);
resize();

/* ---------------------------------------------------------------- bridge */

function setStatus(text) {
  statusEl.textContent = text || '';
  statusEl.classList.toggle('show', !!text);
}

window.setGraphData = async function setGraphData(raw) {
  const generation = ++dataGeneration;
  const adapted = adaptGraph(raw || {});
  if (!adapted.nodes.length) {
    disposeScene();
    graph = null;
    focusView = null;
    setStatus('');
    invalidate();
    post({ type: 'layout', running: false, nodes: 0 });
    return;
  }
  const previous = new Map();
  for (const obj of objects.values()) previous.set(obj.node.id, obj.origin.clone());
  if (!graph) setStatus('Laying out your graph…');
  post({ type: 'layout', running: true, nodes: adapted.nodes.length });
  const result = await layoutGraph(adapted, previous, () => generation !== dataGeneration);
  if (!result || generation !== dataGeneration) return;
  const isFirstLayout = !graph;
  focusView = null;
  preFocusCamera = null;
  buildScene(result);
  setStatus('');
  if (isFirstLayout && !state.selectedId) frameAll(false);
  post({ type: 'layout', running: false, nodes: result.nodes.length });
};

window.setGraphState = function setGraphState(next) {
  next = next || {};
  state.selectedId = next.selectedId || null;
  state.highlightIds = new Set(next.highlightIds || []);
  state.visibleIds = Array.isArray(next.visibleIds) ? new Set(next.visibleIds) : null;
  state.domain = next.domain || null;
  state.minWeight = typeof next.minWeight === 'number' ? next.minWeight : 0;
  state.colorMode = next.colorMode || 'domain';
  state.mergeMode = !!next.mergeMode;
  state.mergeTargetIds = new Set(next.mergeTargetIds || []);
  applyState();
};

window.setGraphInsets = function setGraphInsets(bottom) {
  insetBottom = Math.min(0.9, Math.max(0, Number(bottom) || 0));
  invalidate();
};

window.resetCamera = function resetCamera() {
  if (focusView) {
    // Reset means "show me everything again".
    state.selectedId = null;
    applyState();
    post({ type: 'select', id: null });
  }
  frameAll(true);
};

requestAnimationFrame(tick);
post({ type: 'ready' });
