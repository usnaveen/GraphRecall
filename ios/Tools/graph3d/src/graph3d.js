/*
 * GraphRecall iOS 3D Galaxy Scene — inspired by the web GraphVisualizer + GalaxyBackground.
 * Build: `npm run build` in ios/Tools/graph3d → ios/WebAssets/graph3d.bundle.js
 *
 * Four clean hierarchical levels:
 *   0. SUBJECTS    — Spaced 3D glowing subject nebulae (~8–18 coarse themes) on a deep starfield
 *                    with small borderless subject labels. Tap/pinch into a subject to open it.
 *   1. COMMUNITIES — All other subjects vanish completely. Shows ONLY that subject's named
 *                    communities spaced in 3D (single-community subjects skip straight to Level 2).
 *   2. CONCEPTS    — All other communities vanish. The active community expands into an airy
 *                    dedicated 3D constellation with small borderless labels and directed edges.
 *   3. FOCUS       — Interactive 3D focus around one concept (`controls.enableRotate = true`):
 *                    prerequisites above, unlocks below, related around the equator, persistent
 *                    legend, no arrowheads on RELATED_TO, and small non-overlapping labels.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import * as d3 from 'd3-force-3d';

/* ---------------------------------------------------------------- constants */

const BACKGROUND = '#07080E';
const ACCENT = '#B6FF2E';
const MERGE_TARGET_COLOR = '#F97316';
const FALLBACK_COLOR = '#7DE1FF';

/// Relationship colours and wording — kept in step with GraphRelationshipStyle.swift.
const REL_META = {
  PREREQUISITE_OF: { color: '#2EFFE6', label: 'prerequisite of' },
  SUBTOPIC_OF: { color: '#B07CD8', label: 'subtopic of' },
  BUILDS_ON: { color: '#F59E0B', label: 'builds on' },
  APPLIES_TO: { color: '#38BDF8', label: 'applies to' },
  RELATED_TO: { color: '#94A3B8', label: 'related to' },
  PART_OF: { color: '#EC4899', label: 'part of' },
  USES: { color: '#60A5FA', label: 'uses' },
  ORCHESTRATED_BY: { color: '#A78BFA', label: 'orchestrated by' },
  SUPPORTS: { color: '#34D399', label: 'supports' },
};
const relColor = (type) => (REL_META[type] || REL_META.RELATED_TO).color;
const UNDIRECTED_TYPES = new Set(['RELATED_TO']);

const MASTERY_COLORS = { unseen: '#6B7280', weak: '#F87171', learning: '#F59E0B', strong: '#34D399' };
const COMMUNITY_PALETTE = [
  '#7C3AED', '#3B82F6', '#10B981', '#F59E0B', '#EF4444',
  '#06B6D4', '#EC4899', '#84CC16', '#8B5CF6', '#14B8A6',
];

const NODE_MIN_PX = 4.5;
const NODE_MAX_PX = 18;
const COMMUNITY_LABEL_CAP = 26;
const DIM_OPACITY = 0.14;
const MAX_ARROWS = 450;
const FOCUS = { radius: 98, ringGap: 50, lerp: 0.16, perShell: 7 };
const FOCUS_CAP = { needs: 5, unlocks: 5, related: 3 };

function post(message) {
  try { window.webkit.messageHandlers.graphBridge.postMessage(message); } catch (e) { /* not in WKWebView */ }
}

function masteryColor(mastery) {
  if (mastery == null || mastery <= 0) return MASTERY_COLORS.unseen;
  if (mastery < 0.4) return MASTERY_COLORS.weak;
  if (mastery < 0.7) return MASTERY_COLORS.learning;
  return MASTERY_COLORS.strong;
}

const nodeRadius = (node) => 1.5 + (node.size ?? 1) * 1.05 + Math.min(node.degree, 12) * 0.16;

function stableColor(key) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return COMMUNITY_PALETTE[(h >>> 0) % COMMUNITY_PALETTE.length];
}

/* ---------------------------------------------------------------- data */

const SUBJECT_RULES = [
  ['Machine Learning', ['machine learning', 'deep learning', 'natural language processing', 'nlp', 'llm', 'large language', 'transformer', 'attention', 'neural network', 'reinforcement learning', 'computer vision', 'generative ai', 'ai', 'ml', 'rag']],
  ['Mathematics', ['math', 'geometry', 'linear algebra', 'calculus', 'probability', 'statistics', 'optimization', 'number theory', 'discrete math']],
  ['LeetCode Patterns', ['leetcode', 'coding interview', 'competitive programming', 'sliding window', 'two pointers']],
  ['Computer Science', ['computer science', 'algorithm', 'data structure', 'compiler', 'operating system', 'theory']],
  ['Systems & Infrastructure', ['system design', 'distributed', 'networking', 'architecture', 'cloud', 'kubernetes', 'docker']],
  ['Databases', ['database', 'sql', 'postgres', 'neo4j', 'storage engine', 'indexing']],
  ['Software Engineering', ['software', 'programming', 'python', 'swift', 'ios', 'typescript', 'backend', 'frontend', 'testing']],
  ['Product & Research', ['product', 'research', 'writing', 'reading', 'economics', 'finance', 'biology']],
];

function normalizeSubject(domain) {
  const raw = String(domain || '').trim();
  const low = raw.toLowerCase();
  if (!raw || low === 'general' || low === 'uncategorized') return 'General';
  for (const [subject, keywords] of SUBJECT_RULES) {
    for (const kw of keywords) {
      if (kw.length <= 3) {
        const escaped = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        if (new RegExp(`\\b${escaped}\\b`, 'i').test(low)) return subject;
      } else if (low.includes(kw)) {
        return subject;
      }
    }
  }
  return raw.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatClusterTitle(title, fallbackDomain, shareDomain) {
  const t = String(title || '').trim();
  const domain = String(fallbackDomain || 'General').trim();
  if (!t) return domain;
  if (t.includes(':')) {
    const colon = t.indexOf(':');
    const prefix = t.slice(0, colon).trim() || domain;
    const sub = t.slice(colon + 1).split(',').map((x) => x.trim()).filter(Boolean)[0];
    if (!shareDomain || !sub) return prefix;
    return `${prefix} · ${sub}`;
  }
  return t;
}

function adaptGraph(raw) {
  const rawNodes = (raw && raw.nodes) || [];
  const rawEdges = (raw && (raw.edges || raw.links)) || [];
  const nodes = rawNodes.map((n) => ({
    id: String(n.id),
    title: n.name || n.label || 'Concept',
    domain: n.domain || 'General',
    subject: normalizeSubject(n.domain || 'General'),
    color: n.color || FALLBACK_COLOR,
    mastery: typeof n.mastery_level === 'number' ? n.mastery_level : null,
    size: typeof n.size === 'number' ? n.size : 1,
    communityIndex: -1,
    subjectIndex: 0,
    colorKey: n.domain || 'General',
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

  const communities = ((raw && raw.communities) || []).slice().sort((a, b) => (a.level ?? 0) - (b.level ?? 0));
  const leafCommunities = communities.filter((c) => (c.entity_ids || []).length > 0);
  leafCommunities.forEach((community, index) => {
    const key = String(community.id ?? community.title ?? index);
    for (const id of community.entity_ids || []) {
      const node = byId.get(String(id));
      if (node && node.communityIndex < 0) {
        node.communityIndex = index;
        node.colorKey = key;
      }
    }
  });

  const assignedCommunities = new Set(nodes.map((n) => n.communityIndex).filter((i) => i >= 0));
  let clusterCount = 0;
  const clusterTitles = [];
  if (assignedCommunities.size >= 2) {
    const remap = new Map([...assignedCommunities].sort((a, b) => a - b).map((oldIdx, newIdx) => [oldIdx, newIdx]));
    clusterCount = remap.size;
    const domainCountsByCluster = new Map();
    const bestNodeByCluster = new Map();
    for (const node of nodes) {
      if (node.communityIndex >= 0 && remap.has(node.communityIndex)) {
        const ci = remap.get(node.communityIndex);
        if (!domainCountsByCluster.has(ci)) domainCountsByCluster.set(ci, new Map());
        const dc = domainCountsByCluster.get(ci);
        dc.set(node.domain, (dc.get(node.domain) || 0) + 1);
        const cur = bestNodeByCluster.get(ci);
        if (!cur || node.degree > cur.degree) bestNodeByCluster.set(ci, node);
      }
    }
    const domFreq = new Map();
    const domByCluster = new Map();
    for (const [ci, dc] of domainCountsByCluster) {
      const topDom = [...dc.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || 'General';
      domByCluster.set(ci, topDom);
      domFreq.set(topDom, (domFreq.get(topDom) || 0) + 1);
    }
    for (const [oldIdx, newIdx] of remap) {
      const topDom = domByCluster.get(newIdx) || 'General';
      clusterTitles[newIdx] = formatClusterTitle(
        leafCommunities[oldIdx]?.title,
        topDom,
        (domFreq.get(topDom) || 1) > 1,
      );
    }
    const titleCounts = new Map();
    for (const t of clusterTitles) if (t) titleCounts.set(t, (titleCounts.get(t) || 0) + 1);
    for (let ci = 0; ci < clusterTitles.length; ci++) {
      const base = clusterTitles[ci];
      if (base && (titleCounts.get(base) || 0) > 1 && !base.includes('·')) {
        const lead = bestNodeByCluster.get(ci)?.title;
        if (lead && lead.toLowerCase() !== base.toLowerCase()) {
          const shortLead = lead.length > 15 ? `${lead.slice(0, 14)}…` : lead;
          clusterTitles[ci] = `${base} · ${shortLead}`;
        }
      }
    }
    let fallbackCluster = -1;
    for (const node of nodes) {
      if (node.communityIndex >= 0 && remap.has(node.communityIndex)) {
        node.clusterIndex = remap.get(node.communityIndex);
      } else {
        if (fallbackCluster < 0) {
          fallbackCluster = clusterCount++;
          clusterTitles[fallbackCluster] = node.domain || 'General';
        }
        node.clusterIndex = fallbackCluster;
      }
    }
  } else {
    const domainCounts = new Map();
    for (const node of nodes) domainCounts.set(node.domain, (domainCounts.get(node.domain) || 0) + 1);
    const orderedDomains = [...domainCounts.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([d]) => d);
    const domainIdx = new Map(orderedDomains.map((d, i) => [d, i]));
    clusterCount = Math.max(orderedDomains.length, 1);
    orderedDomains.forEach((d, i) => { clusterTitles[i] = d; });
    for (const node of nodes) {
      const idx = domainIdx.get(node.domain) ?? 0;
      node.clusterIndex = idx;
      if (node.communityIndex < 0) node.communityIndex = idx;
    }
  }

  // Roll communities up into coarse Subject buckets matching backend normalize_subject rules.
  const clusterSubjectCounts = new Map();
  const clusterMemberCounts = new Map();
  for (const node of nodes) {
    const ci = node.clusterIndex ?? 0;
    clusterMemberCounts.set(ci, (clusterMemberCounts.get(ci) || 0) + 1);
    if (!clusterSubjectCounts.has(ci)) clusterSubjectCounts.set(ci, new Map());
    const sc = clusterSubjectCounts.get(ci);
    sc.set(node.subject, (sc.get(node.subject) || 0) + 1);
  }
  const clusterSubjectName = new Map();
  const subjectNodeCounts = new Map();
  const subjectClusterLists = new Map();
  for (let ci = 0; ci < clusterCount; ci++) {
    const sc = clusterSubjectCounts.get(ci);
    const subj = sc && sc.size
      ? [...sc.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0]
      : 'General';
    clusterSubjectName.set(ci, subj);
    subjectNodeCounts.set(subj, (subjectNodeCounts.get(subj) || 0) + (clusterMemberCounts.get(ci) || 0));
    if (!subjectClusterLists.has(subj)) subjectClusterLists.set(subj, []);
    subjectClusterLists.get(subj).push(ci);
  }
  const orderedSubjects = [...subjectClusterLists.keys()].sort(
    (a, b) => (subjectNodeCounts.get(b) || 0) - (subjectNodeCounts.get(a) || 0) || a.localeCompare(b),
  );
  const subjects = orderedSubjects.map((title, index) => ({
    index,
    title,
    clusterIndices: subjectClusterLists.get(title) || [],
  }));
  const subjectIdxByName = new Map(subjects.map((s) => [s.title, s.index]));
  const clusterToSubject = [];
  for (let ci = 0; ci < clusterCount; ci++) {
    clusterToSubject[ci] = subjectIdxByName.get(clusterSubjectName.get(ci) || 'General') ?? 0;
  }
  for (const node of nodes) {
    node.subjectIndex = clusterToSubject[node.clusterIndex ?? 0] ?? 0;
  }

  return { nodes, links, clusterCount, clusterTitles, subjects, clusterToSubject };
}

/* ---------------------------------------------------------------- layout */

const yieldToPage = () => new Promise((resolve) => setTimeout(resolve, 0));

async function layoutGraph(graph, previous, isStale) {
  const { nodes, links, clusterCount = 1, subjects = [] } = graph;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const kClusters = Math.max(clusterCount, 1);

  const sizes = new Map();
  for (const node of nodes) sizes.set(node.clusterIndex ?? 0, (sizes.get(node.clusterIndex ?? 0) || 0) + 1);
  const byPlace = [...Array(kClusters).keys()].sort((a, b) => (sizes.get(b) || 0) - (sizes.get(a) || 0));
  const islandRadius = (n) => Math.max(24, 16 * Math.cbrt(n || 1));

  // Place coarse Subject centers far apart first, then cluster communities locally inside each Subject.
  const kSubjects = Math.max(subjects.length, 1);
  const subjectCenters = new Array(kSubjects);
  const subjectSpacing = Math.max(420, 13.5 * Math.max(...byPlace.map((c) => islandRadius(sizes.get(c))), 28));
  for (let si = 0; si < kSubjects; si++) {
    if (kSubjects === 1) { subjectCenters[si] = { x: 0, y: 0, z: 0 }; continue; }
    const t = si / Math.max(kSubjects - 1, 1);
    const r = subjectSpacing * (0.45 + 0.78 * Math.sqrt(t));
    const phi = Math.acos(1 - 2 * ((si + 0.5) / kSubjects));
    const theta = si * golden;
    subjectCenters[si] = {
      x: r * Math.sin(phi) * Math.cos(theta) * 0.80,
      y: r * Math.sin(phi) * Math.sin(theta) * 1.36,
      z: r * Math.cos(phi) * 0.44,
    };
  }

  const clusterCenters = new Array(kClusters);
  if (subjects.length >= 2) {
    subjects.forEach((subj, si) => {
      const sCenter = subjectCenters[si] || { x: 0, y: 0, z: 0 };
      const cids = subj.clusterIndices.slice().sort((a, b) => (sizes.get(b) || 0) - (sizes.get(a) || 0));
      const subSpread = cids.length <= 1 ? 0 : Math.max(78, 38 * Math.cbrt(cids.length));
      cids.forEach((c, idx) => {
        if (cids.length === 1) { clusterCenters[c] = { ...sCenter }; return; }
        const t = (idx + 0.5) / cids.length;
        const r = subSpread * (0.45 + 0.65 * Math.sqrt(t));
        const phi = Math.acos(1 - 2 * t);
        const theta = idx * golden;
        clusterCenters[c] = {
          x: sCenter.x + r * Math.sin(phi) * Math.cos(theta),
          y: sCenter.y + r * Math.sin(phi) * Math.sin(theta),
          z: sCenter.z + r * Math.cos(phi) * 0.65,
        };
      });
    });
  } else {
    const spacing = Math.max(290, 10.2 * Math.max(...byPlace.map((c) => islandRadius(sizes.get(c))), 28));
    byPlace.forEach((c, i) => {
      if (kClusters === 1) { clusterCenters[c] = { x: 0, y: 0, z: 0 }; return; }
      const t = i / Math.max(kClusters - 1, 1);
      const r = spacing * (0.42 + 0.78 * Math.sqrt(t));
      const phi = Math.acos(1 - 2 * ((i + 0.5) / kClusters));
      const theta = i * golden;
      clusterCenters[c] = {
        x: r * Math.sin(phi) * Math.cos(theta) * 0.78,
        y: r * Math.sin(phi) * Math.sin(theta) * 1.38,
        z: r * Math.cos(phi) * 0.42,
      };
    });
  }

  const clusterMembers = new Map();
  for (const node of nodes) {
    const idx = node.clusterIndex ?? 0;
    if (!clusterMembers.has(idx)) clusterMembers.set(idx, []);
    clusterMembers.get(idx).push(node);
  }

  let reused = 0;
  for (const [idx, members] of clusterMembers.entries()) {
    const center = clusterCenters[idx] || { x: 0, y: 0, z: 0 };
    const localSpread = Math.max(24, 16 * Math.cbrt(members.length));
    members.forEach((node, i) => {
      node.clusterCenter = center;
      const prev = previous.get(node.id);
      if (prev) {
        node.x = prev.x; node.y = prev.y; node.z = prev.z;
        reused += 1;
      } else {
        const t = (i + 0.5) / Math.max(members.length, 1);
        const r = localSpread * Math.cbrt(t);
        const phi = Math.acos(1 - 2 * t);
        node.x = center.x + r * Math.sin(phi) * Math.cos(golden * i);
        node.y = center.y + r * Math.sin(phi) * Math.sin(golden * i);
        node.z = center.z + r * Math.cos(phi);
      }
    });
  }

  // Initial overview settle (keeps each cluster tidy; entering a community runs a spacious dedicated layout).
  const simulation = d3.forceSimulation(nodes, 3)
    .stop()
    .alphaDecay(0.04)
    .alphaMin(0.004)
    .force('charge', d3.forceManyBody().strength((d) => -75 - Math.min(d.degree, 16) * 5).distanceMax(180))
    .force('link', d3.forceLink(links)
      .distance((l) => (l.source.clusterIndex === l.target.clusterIndex ? 30 : 200))
      .strength((l) => (l.source.clusterIndex === l.target.clusterIndex ? 0.28 : 0)))
    .force('collide', d3.forceCollide().radius((d) => nodeRadius(d) + 6).iterations(1))
    .force('x', d3.forceX((d) => d.clusterCenter.x).strength(0.24))
    .force('y', d3.forceY((d) => d.clusterCenter.y).strength(0.24))
    .force('z', d3.forceZ((d) => d.clusterCenter.z).strength(0.24));
  if (nodes.length && reused === nodes.length) simulation.alpha(0.2);

  for (let i = 0; i < 240;) {
    const sliceEnd = Math.min(240, i + 30);
    for (; i < sliceEnd; i++) {
      simulation.tick();
      if (simulation.alpha() < 0.004) { i = 240; break; }
    }
    if (isStale()) return null;
    if (i < 240) await yieldToPage();
  }
  return graph;
}

/** Airy, dedicated 3D layout for ONE community so its concepts spread comfortably without clumping. */
function computeExpandedCommunity(view) {
  const origin = view.activeCentre || view.centre;
  if (view.expandedPositions && view.expandedOrigin && view.expandedOrigin.equals(origin)) {
    return view.expandedPositions;
  }
  const members = [...view.members].map((id) => objects.get(id)?.node).filter(Boolean);
  const memberSet = view.members;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const c = origin;

  const tempNodes = members.map((n, i) => {
    const t = (i + 0.5) / Math.max(members.length, 1);
    const r = Math.max(55, 24 * Math.cbrt(members.length)) * Math.cbrt(t);
    const phi = Math.acos(1 - 2 * t);
    return {
      id: n.id,
      degree: n.degree || 0,
      size: n.size ?? 1,
      x: c.x + r * Math.sin(phi) * Math.cos(golden * i),
      y: c.y + r * Math.sin(phi) * Math.sin(golden * i),
      z: c.z + r * Math.cos(phi),
    };
  });
  const tempById = new Map(tempNodes.map((n) => [n.id, n]));
  const intraLinks = [];
  for (const link of graph.links) {
    if (UNDIRECTED_TYPES.has(link.type)) continue;
    if (!memberSet.has(link.source.id) || !memberSet.has(link.target.id)) continue;
    const s = tempById.get(link.source.id);
    const t = tempById.get(link.target.id);
    if (s && t) intraLinks.push({ source: s, target: t, weight: link.weight });
  }

  const sim = d3.forceSimulation(tempNodes, 3)
    .stop()
    .alphaDecay(0.03)
    .force('charge', d3.forceManyBody().strength((d) => -210 - Math.min(d.degree, 14) * 14).distanceMax(280))
    .force('link', d3.forceLink(intraLinks).distance(58).strength(0.32))
    .force('collide', d3.forceCollide().radius((d) => nodeRadius(d) + 15).iterations(2))
    .force('x', d3.forceX(c.x).strength(0.055))
    .force('y', d3.forceY(c.y).strength(0.055))
    .force('z', d3.forceZ(c.z).strength(0.055));

  for (let i = 0; i < 160; i++) sim.tick();

  const positions = new Map();
  let maxDist = 65;
  for (const tn of tempNodes) {
    const v = new THREE.Vector3(tn.x, tn.y, tn.z);
    positions.set(tn.id, v);
    maxDist = Math.max(maxDist, v.distanceTo(c));
  }
  view.expandedPositions = positions;
  view.expandedOrigin = origin.clone();
  view.expandedRadius = maxDist + 14;
  return positions;
}

/** Spacious dedicated 3D sphere of community orbs for ONE expanded Subject. */
function computeExpandedSubject(subjectView) {
  const childViews = subjectView.communityIndices
    .map((ci) => clusterViews.find((v) => v.index === ci))
    .filter(Boolean)
    .sort((a, b) => b.members.size - a.members.size);
  if (!childViews.length) return;

  if (!subjectView.expandedCentres) {
    const golden = Math.PI * (3 - Math.sqrt(5));
    const maxOrbR = Math.max(...childViews.map((v) => v.orbRadius), 24);
    const spacing = childViews.length <= 1 ? 0 : Math.max(122, 4.6 * maxOrbR + 18 * Math.cbrt(childViews.length));
    const centres = new Map();
    let maxDist = maxOrbR + 30;
    childViews.forEach((v, i) => {
      let pos;
      if (childViews.length === 1) {
        pos = subjectView.centre.clone();
      } else {
        const t = (i + 0.5) / childViews.length;
        const r = spacing * (0.48 + 0.72 * Math.sqrt(t));
        const phi = Math.acos(1 - 2 * t);
        const theta = i * golden;
        pos = new THREE.Vector3(
          subjectView.centre.x + r * Math.sin(phi) * Math.cos(theta) * 0.85,
          subjectView.centre.y + r * Math.sin(phi) * Math.sin(theta) * 1.15,
          subjectView.centre.z + r * Math.cos(phi) * 0.52,
        );
      }
      centres.set(v.index, pos);
      maxDist = Math.max(maxDist, pos.distanceTo(subjectView.centre) + v.orbRadius);
    });
    subjectView.expandedCentres = centres;
    subjectView.expandedRadius = maxDist + 24;
  }

  for (const v of childViews) {
    const p = subjectView.expandedCentres.get(v.index) || v.centre;
    v.activeCentre.copy(p);
    v.group.position.copy(p);
    v.sprite.position.copy(p);
  }
}

function restoreCommunityPositions() {
  for (const v of clusterViews) {
    v.activeCentre.copy(v.centre);
    v.group.position.copy(v.centre);
    v.sprite.position.copy(v.centre);
  }
}

/* ---------------------------------------------------------------- renderer & galaxy backdrop */

const container = document.getElementById('graph');
const labelsEl = document.getElementById('labels');
const statusEl = document.getElementById('status');

const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.setClearColor(BACKGROUND, 1);
container.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(BACKGROUND);
const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 6000);
camera.position.set(0, 0, 260);
scene.add(camera);

scene.add(new THREE.AmbientLight(0xffffff, 1.05));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
keyLight.position.set(0.4, 0.8, 1);
camera.add(keyLight);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.rotateSpeed = 0.9;
controls.zoomSpeed = 1.2;
controls.panSpeed = 0.8;
controls.minDistance = 8;
controls.maxDistance = 4200;

const starLayer = new THREE.Group();
const haloLayer = new THREE.Group();
const clusterEntityLayer = new THREE.Group();
const linkLayer = new THREE.Group();
const arrowLayer = new THREE.Group();
const nodeLayer = new THREE.Group();
const ringLayer = new THREE.Group();
scene.add(starLayer, haloLayer, clusterEntityLayer, linkLayer, arrowLayer, nodeLayer, ringLayer);

// Subtle deep-space starfield matching GalaxyBackground.tsx (stationary, no distracting swirl).
(() => {
  const count = 1400;
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const r = 1400 + Math.random() * 900;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = r * Math.cos(phi);
    const t = Math.random();
    colors[i * 3] = 0.35 + 0.25 * t;
    colors[i * 3 + 1] = 0.60 + 0.25 * t;
    colors[i * 3 + 2] = 0.88 + 0.12 * t;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const mat = new THREE.PointsMaterial({
    size: 2.4,
    transparent: true,
    opacity: 0.38,
    vertexColors: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });
  const stars = new THREE.Points(geo, mat);
  stars.raycast = () => {};
  starLayer.add(stars);
})();

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.28, 0.45, 0.30);
composer.addPass(bloomPass);
composer.addPass(new OutputPass());

const haloTexture = (() => {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,0.60)');
  g.addColorStop(0.42, 'rgba(255,255,255,0.20)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
})();

const starDotTexture = (() => {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.28, 'rgba(255,255,255,0.75)');
  g.addColorStop(0.65, 'rgba(255,255,255,0.16)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
})();

function createNebulaShellMaterial(colour) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: colour.clone() },
      uOpacity: { value: 1.0 },
    },
    vertexShader: `
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        vec4 mvPos = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vViewDir = normalize(-mvPos.xyz);
        gl_Position = projectionMatrix * mvPos;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      uniform float uOpacity;
      varying vec3 vNormal;
      varying vec3 vViewDir;
      void main() {
        float fresnel = pow(1.0 - abs(dot(normalize(vNormal), normalize(vViewDir))), 2.2);
        float alpha = (0.045 + fresnel * 0.34) * uOpacity;
        vec3 col = mix(uColor, vec3(1.0), fresnel * 0.28);
        gl_FragColor = vec4(col, alpha);
      }
    `,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.FrontSide,
  });
}

const sphereGeometry = new THREE.SphereGeometry(1, 20, 14);
const ringGeometry = new THREE.RingGeometry(1.3, 1.6, 48);
const ARROW_HEIGHT = 1.0;
const arrowGeometry = new THREE.ConeGeometry(0.24, ARROW_HEIGHT, 8);

let width = 1;
let height = 1;
let needsRender = true;
const invalidate = () => { needsRender = true; };
let prevCameraDist = camera.position.distanceTo(controls.target);
controls.addEventListener('change', () => {
  const curDist = camera.position.distanceTo(controls.target);
  const delta = curDist - prevCameraDist;
  prevCameraDist = curDist;
  // Auto-transition by zoom ONLY during an explicit two-finger pinch gesture (not damped/programmatic movement).
  if (!cameraFlight && pointers.size >= 2 && graph && !focusView && !state.selectedId && !state.mergeMode && performance.now() > navCooldownUntil) {
    const level = getViewLevel();
    if (delta < -0.5 && (level === 'subjects' || level === 'communities')) {
      const views = level === 'subjects'
        ? subjectViews.filter((v) => v.orb.visible)
        : clusterViews.filter((v) => v.orb.visible);
      let closest = null;
      let minD = Infinity;
      for (const view of views) {
        const anchor = view.activeCentre || view.centre;
        const d = camera.position.distanceTo(anchor);
        if (d < Math.max(165, view.orbRadius * 4.5) && d < minD) {
          minD = d;
          closest = view;
        }
      }
      if (closest) {
        if (level === 'subjects') enterSubject(closest.index);
        else enterCluster(closest.index);
      }
    } else if (delta > 0.5 && (level === 'concepts' || level === 'communities')) {
      if (level === 'concepts' && activeClusterIndex !== null) {
        const view = clusterViews.find((v) => v.index === activeClusterIndex);
        if (view && curDist > Math.max(460, (view.expandedRadius || 110) * 4.8)) {
          exitLevel();
        }
      } else if (level === 'communities' && activeSubjectIndex !== null) {
        const sView = subjectViews.find((v) => v.index === activeSubjectIndex);
        if (sView && curDist > Math.max(520, (sView.expandedRadius || 140) * 4.2)) {
          exitLevel();
        }
      }
    }
  }
  invalidate();
});

/* ---------------------------------------------------------------- state */

let graph = null;
let objects = new Map();
let linkBatches = [];
let arrows = [];
let neighborIds = new Set();
let shownLabels = new Set();
let subjectViews = [];     // { index, group, orb, stars, constellationLines, sprite, label, titleText, colourHex, centre, activeCentre, radius, orbRadius, members, communityIndices, expandedCentres, expandedRadius }
let clusterViews = [];     // { index, subjectIndex, group, orb, stars, constellationLines, sprite, label, titleText, colourHex, centre, activeCentre, radius, orbRadius, members, expandedPositions, expandedOrigin, expandedRadius }
let activeSubjectIndex = null;
let activeClusterIndex = null;
let skippedCommunities = false;
let navCooldownUntil = 0;
let dataGeneration = 0;
let cameraFlight = null;
let viewShift = 0;
let insetBottom = 0;
let settling = false;

let focusView = null;
let preFocusCamera = null;
let pendingClusterQuery = null;

const state = {
  selectedId: null,
  highlightIds: new Set(),
  visibleIds: null,
  domain: null,
  minWeight: 0,
  colorMode: 'community',
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
    return node.communityIndex >= 0 ? stableColor(node.colorKey) : MASTERY_COLORS.unseen;
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

function disposeViewList(views) {
  for (const view of views) {
    haloLayer.remove(view.sprite);
    view.sprite.material.dispose();
    clusterEntityLayer.remove(view.group);
    view.orb.material.dispose();
    if (view.stars) {
      view.stars.geometry.dispose();
      view.stars.material.dispose();
    }
    if (view.constellationLines) {
      view.constellationLines.geometry.dispose();
      view.constellationLines.material.dispose();
    }
    view.label.remove();
  }
}

function disposeScene() {
  for (const obj of objects.values()) {
    obj.mesh.material.dispose();
    if (obj.ring) { ringLayer.remove(obj.ring); obj.ring.material.dispose(); }
    if (obj.label) obj.label.remove();
  }
  disposeViewList(subjectViews);
  subjectViews = [];
  disposeViewList(clusterViews);
  clusterViews = [];
  nodeLayer.clear();
  disposeLinks();
  disposeArrows();
  objects = new Map();
  shownLabels = new Set();
}

function buildScene(newGraph) {
  disposeScene();
  graph = newGraph;
  activeSubjectIndex = null;
  activeClusterIndex = null;
  skippedCommunities = false;
  for (const node of graph.nodes) {
    const mesh = new THREE.Mesh(
      sphereGeometry,
      new THREE.MeshLambertMaterial({ color: node.color, transparent: true }),
    );
    mesh.position.set(node.x, node.y, node.z);
    mesh.userData.nodeId = node.id;
    nodeLayer.add(mesh);
    objects.set(node.id, {
      node,
      mesh,
      origin: new THREE.Vector3(node.x, node.y, node.z),
      target: new THREE.Vector3(node.x, node.y, node.z),
      radius: nodeRadius(node),
      passesFilters: true,
      visible: false,
      dimmed: false,
      emphasis: 1,
      pxRadius: NODE_MIN_PX,
      label: null,
      ring: null,
    });
  }
  buildClusterViews();
  buildSubjectViews();
  applyState();
}

/** Shared builder for both Subject nebulae (Level 0) and Community nebulae (Level 1). */
function createNebulaView({ index, titleText, colourKey, members, orbMin, orbMax, starSize, onTap, extra }) {
  const centre = new THREE.Vector3();
  for (const n of members) centre.add(new THREE.Vector3(n.x, n.y, n.z));
  centre.divideScalar(members.length);
  const distances = members.map((n) => centre.distanceTo(new THREE.Vector3(n.x, n.y, n.z))).sort((a, b) => a - b);
  const radius = Math.max(24, distances[Math.floor(distances.length * 0.85)] || 24);
  const maxDist = Math.max(distances[distances.length - 1] || 24, 1);
  const orbRadius = THREE.MathUtils.clamp(orbMin + Math.cbrt(members.length) * 4.8, orbMin + 2, orbMax);
  const colourHex = stableColor(colourKey);
  const colour = new THREE.Color(colourHex);

  const group = new THREE.Group();
  group.position.copy(centre);
  clusterEntityLayer.add(group);

  const orb = new THREE.Mesh(sphereGeometry, createNebulaShellMaterial(colour));
  orb.scale.setScalar(orbRadius);
  orb.userData.viewIndex = index;
  group.add(orb);

  // Inner glowing star-cluster points + gossamer constellation filaments (in group-local coords).
  const starPositions = new Float32Array(members.length * 3);
  const starColors = new Float32Array(members.length * 3);
  const memberMiniPos = new Map();
  const starCol = new THREE.Color();
  const innerScale = (orbRadius * 0.78) / maxDist;
  members.forEach((n, i) => {
    const mx = (n.x - centre.x) * innerScale;
    const my = (n.y - centre.y) * innerScale;
    const mz = (n.z - centre.z) * innerScale;
    starPositions[i * 3] = mx;
    starPositions[i * 3 + 1] = my;
    starPositions[i * 3 + 2] = mz;
    memberMiniPos.set(n.id, [mx, my, mz]);

    const brightness = Math.min(1, (n.degree || 0) / 8);
    starCol.copy(colour).lerp(new THREE.Color('#ffffff'), 0.45 + 0.35 * brightness);
    starColors[i * 3] = starCol.r;
    starColors[i * 3 + 1] = starCol.g;
    starColors[i * 3 + 2] = starCol.b;
  });
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
  starGeo.setAttribute('color', new THREE.BufferAttribute(starColors, 3));
  const stars = new THREE.Points(
    starGeo,
    new THREE.PointsMaterial({
      map: starDotTexture,
      size: starSize,
      vertexColors: true,
      transparent: true,
      opacity: 0.92,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      sizeAttenuation: true,
    }),
  );
  stars.raycast = () => {};
  group.add(stars);

  const intraPairs = [];
  for (const link of graph.links) {
    if (intraPairs.length >= 45) break;
    const a = memberMiniPos.get(link.source.id);
    const b = memberMiniPos.get(link.target.id);
    if (a && b) intraPairs.push([a, b]);
  }
  let constellationLines = null;
  if (intraPairs.length > 0) {
    const linePositions = new Float32Array(intraPairs.length * 6);
    intraPairs.forEach(([a, b], i) => {
      const o = i * 6;
      linePositions[o] = a[0]; linePositions[o + 1] = a[1]; linePositions[o + 2] = a[2];
      linePositions[o + 3] = b[0]; linePositions[o + 4] = b[1]; linePositions[o + 5] = b[2];
    });
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    constellationLines = new THREE.LineSegments(
      lineGeo,
      new THREE.LineBasicMaterial({
        color: colour,
        transparent: true,
        opacity: 0.16,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    constellationLines.raycast = () => {};
    group.add(constellationLines);
  }

  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: haloTexture, color: colour, transparent: true, opacity: 0.24,
    blending: THREE.AdditiveBlending, depthWrite: false,
  }));
  sprite.position.copy(centre);
  sprite.scale.setScalar(orbRadius * 2.9);
  sprite.renderOrder = -5;
  haloLayer.add(sprite);

  const clippedTitle = titleText.length > 26 ? `${titleText.slice(0, 24)}…` : titleText;
  const label = document.createElement('div');
  label.className = 'cluster-label';
  label.textContent = clippedTitle;
  label.style.color = '#E2E8F0';
  label.style.opacity = '0';
  label.style.pointerEvents = 'none';
  labelsEl.appendChild(label);

  label.addEventListener('click', (e) => {
    e.stopPropagation();
    if (label.style.opacity === '0') return;
    onTap();
  });

  return {
    index,
    group,
    orb,
    stars,
    constellationLines,
    sprite,
    label,
    titleText: clippedTitle,
    colourHex,
    centre,
    activeCentre: centre.clone(),
    radius,
    orbRadius,
    members: new Set(members.map((n) => n.id)),
    ...extra,
  };
}

function buildClusterViews() {
  disposeViewList(clusterViews);
  clusterViews = [];
  if (!graph || (graph.clusterCount || 0) < 2) return;

  const groups = new Map();
  for (const node of graph.nodes) {
    const idx = node.clusterIndex ?? 0;
    if (!groups.has(idx)) groups.set(idx, []);
    groups.get(idx).push(node);
  }

  for (const [index, members] of groups) {
    if (members.length < 2) continue;
    const rawTitle = (graph.clusterTitles && graph.clusterTitles[index]) || members[0].domain || 'Group';
    const colourKey = members[0].colorKey || String(index);
    const subjectIndex = graph.clusterToSubject ? (graph.clusterToSubject[index] ?? 0) : 0;
    const view = createNebulaView({
      index,
      titleText: rawTitle,
      colourKey,
      members,
      orbMin: 15,
      orbMax: 31,
      starSize: 5.5,
      onTap: () => enterCluster(index),
      extra: {
        subjectIndex,
        expandedPositions: null,
        expandedOrigin: null,
        expandedRadius: 65,
      },
    });
    clusterViews.push(view);
  }
}

function buildSubjectViews() {
  disposeViewList(subjectViews);
  subjectViews = [];
  if (!graph || !graph.subjects || graph.subjects.length < 2) return;

  const builtClusterIndices = new Set(clusterViews.map((v) => v.index));
  const membersBySubject = new Map();
  for (const node of graph.nodes) {
    const si = node.subjectIndex ?? 0;
    if (!membersBySubject.has(si)) membersBySubject.set(si, []);
    membersBySubject.get(si).push(node);
  }

  for (const subj of graph.subjects) {
    const members = membersBySubject.get(subj.index) || [];
    if (!members.length) continue;
    const communityIndices = subj.clusterIndices.filter((ci) => builtClusterIndices.has(ci));
    const view = createNebulaView({
      index: subj.index,
      titleText: subj.title,
      colourKey: `subject:${subj.title}`,
      members,
      orbMin: 21,
      orbMax: 42,
      starSize: 6.2,
      onTap: () => enterSubject(subj.index),
      extra: {
        communityIndices,
        expandedCentres: null,
        expandedRadius: 140,
      },
    });
    subjectViews.push(view);
  }
}

function viewPassesFilter(view) {
  for (const id of view.members) {
    const obj = objects.get(id);
    if (obj && isVisibleNode(obj.node)) return true;
  }
  return false;
}

function getViewLevel() {
  if (!graph) return 'concepts';
  if (focusView || state.selectedId) return 'focus';
  if (state.mergeMode || state.visibleIds || state.domain || state.highlightIds.size > 0) return 'concepts';
  if (activeClusterIndex !== null) return 'concepts';
  if (activeSubjectIndex !== null && subjectViews.length >= 2) return 'communities';
  if (subjectViews.length >= 2) return 'subjects';
  if (clusterViews.length >= 2) return 'communities';
  return 'concepts';
}

function isOverviewMode() {
  const level = getViewLevel();
  return level === 'subjects' || level === 'communities';
}

function postNavState() {
  const level = getViewLevel();
  const sView = activeSubjectIndex !== null ? subjectViews.find((v) => v.index === activeSubjectIndex) || null : null;
  const cView = activeClusterIndex !== null ? clusterViews.find((v) => v.index === activeClusterIndex) || null : null;
  let title = null;
  let backLabel = null;
  if (cView && (level === 'concepts' || level === 'focus')) {
    title = cView.titleText;
    if (sView && !skippedCommunities) {
      backLabel = `${sView.titleText} · ${cView.titleText}`;
    } else if (subjectViews.length >= 2) {
      backLabel = `All subjects · ${cView.titleText}`;
    } else {
      backLabel = `All groups · ${cView.titleText}`;
    }
  } else if (sView && level === 'communities') {
    title = sView.titleText;
    backLabel = `All subjects · ${sView.titleText}`;
  }
  post({ type: 'clusterChanged', level, title, backLabel, index: activeClusterIndex });
}

function flyToVantage(centre, spanRadius) {
  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const distance = Math.max(95, (spanRadius * 1.18) / Math.tan(Math.min(vFov, hFov) / 2));
  const vantage = new THREE.Vector3(0.18, 0.14, 0.97).normalize();
  cameraFlight = {
    target: centre.clone(),
    position: centre.clone().addScaledVector(vantage, distance),
  };
}

function enterSubject(index) {
  const sView = subjectViews.find((v) => v.index === index);
  if (!sView) return;
  navCooldownUntil = performance.now() + 550;
  focusView = null;
  state.selectedId = null;

  if (sView.communityIndices.length <= 1) {
    const onlyIdx = sView.communityIndices[0];
    const cView = onlyIdx !== undefined ? clusterViews.find((v) => v.index === onlyIdx) : null;
    if (cView) {
      activeSubjectIndex = index;
      skippedCommunities = true;
      cView.activeCentre.copy(sView.centre);
      cView.group.position.copy(sView.centre);
      cView.sprite.position.copy(sView.centre);
      enterCluster(cView.index);
      return;
    }
  }

  activeSubjectIndex = index;
  activeClusterIndex = null;
  skippedCommunities = false;
  computeExpandedSubject(sView);
  clusterEntityLayer.updateMatrixWorld(true);
  applyState();
  flyToVantage(sView.centre, sView.expandedRadius);
  postNavState();
  invalidate();
}

function enterCluster(index) {
  const view = clusterViews.find((v) => v.index === index);
  if (!view) return;
  navCooldownUntil = performance.now() + 550;
  focusView = null;
  if (activeSubjectIndex === null && subjectViews.length >= 2) {
    activeSubjectIndex = view.subjectIndex;
    const sView = subjectViews.find((v) => v.index === activeSubjectIndex);
    skippedCommunities = !sView || sView.communityIndices.length <= 1;
  }
  activeClusterIndex = index;
  computeExpandedCommunity(view);

  applyState();
  const anchor = view.activeCentre || view.centre;
  view.sprite.position.copy(anchor);
  flyToVantage(anchor, view.expandedRadius);
  postNavState();
  invalidate();
}

function exitLevel() {
  navCooldownUntil = performance.now() + 550;
  if (focusView || state.selectedId) {
    focusView = null;
    preFocusCamera = null;
    state.selectedId = null;
    applyState();
    postNavState();
    post({ type: 'select', id: null });
    invalidate();
    return;
  }
  if (activeClusterIndex !== null) {
    state.selectedId = null;
    activeClusterIndex = null;
    if (skippedCommunities) {
      activeSubjectIndex = null;
      skippedCommunities = false;
      restoreCommunityPositions();
    } else if (activeSubjectIndex !== null) {
      const sView = subjectViews.find((v) => v.index === activeSubjectIndex);
      if (sView) computeExpandedSubject(sView);
    }
    clusterEntityLayer.updateMatrixWorld(true);
    applyState();
    if (activeSubjectIndex !== null) {
      const sView = subjectViews.find((v) => v.index === activeSubjectIndex);
      if (sView) flyToVantage(sView.centre, sView.expandedRadius);
    } else {
      frameAll(true);
    }
    postNavState();
    post({ type: 'select', id: null });
    invalidate();
    return;
  }
  if (activeSubjectIndex !== null) {
    state.selectedId = null;
    activeSubjectIndex = null;
    skippedCommunities = false;
    restoreCommunityPositions();
    clusterEntityLayer.updateMatrixWorld(true);
    applyState();
    frameAll(true);
    postNavState();
    post({ type: 'select', id: null });
    invalidate();
  }
}

const exitCluster = exitLevel;

/* ---------------------------------------------------------------- interactive 3D concept focus */

function focusGroup(link, id) {
  const outgoing = link.source.id === id;
  switch (link.type) {
    case 'PREREQUISITE_OF':
    case 'USES':
    case 'APPLIES_TO':
      return outgoing ? 1 : 0;
    case 'BUILDS_ON':
    case 'SUBTOPIC_OF':
    case 'PART_OF':
      return outgoing ? 0 : 1;
    default:
      return 2;
  }
}

function placeSphericalBand(members, origin, yMin, yMax, baseRadius, thetaOffset, targets) {
  const n = members.length;
  if (!n) return;
  const golden = Math.PI * (3 - Math.sqrt(5));
  members.forEach((member, i) => {
    const shell = Math.floor(i / FOCUS.perShell);
    const r = baseRadius + shell * FOCUS.ringGap;
    const t = n === 1 ? 0.5 : i / (n - 1);
    const ny = THREE.MathUtils.lerp(yMin, yMax, t);
    const ringR = Math.sqrt(Math.max(0.08, 1 - ny * ny));
    const theta = thetaOffset + i * golden * 1.35;
    targets.set(member.other.id, new THREE.Vector3(
      origin.x + Math.cos(theta) * ringR * r,
      origin.y + ny * r,
      origin.z + Math.sin(theta) * ringR * r,
    ));
  });
}

function buildFocusView(id) {
  const centre = objects.get(id);
  if (!centre || !graph) return null;
  const origin = centre.target.clone();

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
  const members = [...byOther.values()].sort((a, b) => (a.group === 2) - (b.group === 2) || b.link.weight - a.link.weight);
  const targets = new Map([[id, origin.clone()]]);

  const needs = members.filter((m) => m.group === 0).slice(0, FOCUS_CAP.needs);
  const unlocks = members.filter((m) => m.group === 1).slice(0, FOCUS_CAP.unlocks);
  const related = members.filter((m) => m.group === 2).slice(0, FOCUS_CAP.related);
  const shown = [...needs, ...unlocks, ...related];

  placeSphericalBand(needs, origin, 0.44, 0.88, FOCUS.radius, 0.3, targets);
  placeSphericalBand(unlocks, origin, -0.88, -0.44, FOCUS.radius, 2.1, targets);
  placeSphericalBand(related, origin, -0.18, 0.18, FOCUS.radius + 14, 1.1, targets);

  const maxShell = Math.max(
    Math.ceil(Math.max(needs.length, unlocks.length, related.length) / FOCUS.perShell),
    1,
  );
  return {
    id,
    origin,
    targets,
    members: new Set([id, ...shown.map((m) => m.other.id)]),
    links: shown.map((m) => m.link),
    radius: FOCUS.radius + 18 + (maxShell - 1) * FOCUS.ringGap,
  };
}

function enterFocus(id) {
  const view = buildFocusView(id);
  if (!view) return;
  if (!focusView) {
    preFocusCamera = { position: camera.position.clone(), target: controls.target.clone() };
  }
  focusView = view;
  controls.enableRotate = true;
  settling = true;

  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const span = view.radius + 32;
  const distance = Math.max(115, span / Math.tan(Math.min(vFov, hFov) / 2));
  const vantage = new THREE.Vector3(0.24, 0.18, 0.96).normalize();
  cameraFlight = {
    target: view.origin.clone(),
    position: view.origin.clone().addScaledVector(vantage, distance),
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

  if (selectedId && !state.mergeMode) {
    if (!focusView || focusView.id !== selectedId) enterFocus(selectedId);
  } else if (focusView) {
    exitFocus();
  }

  const level = getViewLevel();
  const inSubjects = level === 'subjects';
  const inCommunities = level === 'communities';
  const inOrbOverview = inSubjects || inCommunities;
  const activeView = activeClusterIndex !== null ? clusterViews.find((v) => v.index === activeClusterIndex) || null : null;
  const activeSet = activeView ? activeView.members : null;
  const focusing = level === 'focus';
  const searching = !inOrbOverview && !focusing && state.highlightIds.size > 0;

  // Level 0 (SUBJECTS): show Subject nebulae only.
  // Level 1 (COMMUNITIES): show only the active Subject's Community nebulae.
  // Level 2 (CONCEPTS) & 3 (FOCUS): hide all nebula orbs; expand ONLY activeSet/focusView!
  for (const sView of subjectViews) {
    const showSubjectOrb = inSubjects && viewPassesFilter(sView);
    sView.orb.visible = showSubjectOrb;
    if (sView.stars) sView.stars.visible = showSubjectOrb;
    if (sView.constellationLines) sView.constellationLines.visible = showSubjectOrb;
    sView.sprite.visible = showSubjectOrb;
    if (!showSubjectOrb) {
      sView.label.style.opacity = '0';
      sView.label.style.pointerEvents = 'none';
    }
  }

  for (const view of clusterViews) {
    const belongsToSubject = activeSubjectIndex === null || view.subjectIndex === activeSubjectIndex;
    const showOrb = inCommunities && belongsToSubject && viewPassesFilter(view);
    const isIsolatedCloud = level === 'concepts' && activeView && view.index === activeView.index;
    view.orb.visible = showOrb;
    if (view.stars) view.stars.visible = showOrb;
    if (view.constellationLines) view.constellationLines.visible = showOrb;
    view.sprite.visible = showOrb || isIsolatedCloud;
    view.sprite.material.opacity = showOrb ? 0.24 : 0.08;
    view.sprite.scale.setScalar(showOrb ? view.orbRadius * 2.9 : (view.expandedRadius || view.radius) * 2.0);
    if (!showOrb) {
      view.label.style.opacity = '0';
      view.label.style.pointerEvents = 'none';
    }
  }

  for (const obj of objects.values()) {
    const { node, mesh } = obj;
    obj.passesFilters = isVisibleNode(node);

    if (focusing) {
      obj.visible = obj.passesFilters && focusView.members.has(node.id);
      obj.target.copy(focusView.targets.get(node.id) || obj.origin);
    } else if (inOrbOverview) {
      obj.visible = false;
      obj.target.copy(obj.origin);
    } else if (activeSet) {
      obj.visible = obj.passesFilters && activeSet.has(node.id);
      const exp = activeView.expandedPositions?.get(node.id);
      obj.target.copy(exp || obj.origin);
      // If just entering from an orb, start smoothly at that orb's centre.
      if (obj.visible && mesh.visible === false && exp) {
        mesh.position.copy(activeView.activeCentre || activeView.centre);
      }
    } else {
      obj.visible = obj.passesFilters;
      obj.target.copy(obj.origin);
    }

    mesh.visible = obj.visible;
    const isTarget = state.mergeTargetIds.has(node.id);
    obj.dimmed = obj.visible && searching && !state.highlightIds.has(node.id);
    const tint = isTarget ? MERGE_TARGET_COLOR : baseColor(node);
    mesh.material.color.set(tint);
    if (mesh.material.emissive) {
      mesh.material.emissive.set(tint);
      mesh.material.emissiveIntensity = node.id === selectedId ? 0.35 : 0.14;
    }
    mesh.material.opacity = obj.dimmed ? DIM_OPACITY : 1;
    mesh.material.depthWrite = !obj.dimmed;
    mesh.renderOrder = obj.dimmed ? 0 : 1;
    obj.emphasis = node.id === selectedId ? 1.38 : isTarget || state.highlightIds.has(node.id) ? 1.15 : 1;
    setTargetRing(obj, obj.visible && isTarget);
  }

  selectionRing.visible = !!selected && selected.visible;
  settling = true;
  rebuildLinks(selectedId, searching, inOrbOverview, activeSet);
  invalidate();
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

/* ---------------------------------------------------------------- links & arrows */

const resolution = new THREE.Vector2(1, 1);

function rebuildLinks(selectedId, searching, overview, activeSet) {
  disposeLinks();
  disposeArrows();
  if (!graph || overview) return; // Overview shows clean orbs only — zero hairball edges.

  if (focusView) {
    addLinkBatch(focusView.links, 1.8, 0.80, (link) => relColor(link.type));
    for (const link of focusView.links) {
      if (UNDIRECTED_TYPES.has(link.type)) continue; // RELATED_TO never gets an arrowhead.
      const mesh = new THREE.Mesh(
        arrowGeometry,
        new THREE.MeshBasicMaterial({ color: relColor(link.type), transparent: true, opacity: 0.78 }),
      );
      mesh.raycast = () => {};
      arrowLayer.add(mesh);
      arrows.push({ mesh, link });
    }
    return;
  }

  const idle = [];
  const faint = [];
  for (const link of graph.links) {
    if (!linkPasses(link)) continue;
    const sObj = objects.get(link.source.id);
    const tObj = objects.get(link.target.id);
    if (!sObj?.visible || !tObj?.visible) continue;
    if (UNDIRECTED_TYPES.has(link.type)) continue;
    if (activeSet && (!activeSet.has(link.source.id) || !activeSet.has(link.target.id))) continue;
    if (searching && !(state.highlightIds.has(link.source.id) && state.highlightIds.has(link.target.id))) {
      faint.push(link);
    } else {
      idle.push(link);
    }
  }

  addLinkBatch(faint, 0.9, 0.10, (link) => relColor(link.type));
  addLinkBatch(idle, 1.2, 0.58, (link) => relColor(link.type));
  let budget = MAX_ARROWS;
  for (const link of idle) {
    if (budget-- <= 0) break;
    const mesh = new THREE.Mesh(
      arrowGeometry,
      new THREE.MeshBasicMaterial({ color: relColor(link.type), transparent: true, opacity: 0.58 }),
    );
    mesh.raycast = () => {};
    arrowLayer.add(mesh);
    arrows.push({ mesh, link });
  }
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
    const worldPerPx = target.mesh.scale.x / Math.max(target.pxRadius, 0.001);
    const headLength = (focusView ? 7.2 : 4.8) * worldPerPx;
    mesh.scale.setScalar(headLength / ARROW_HEIGHT);
    const back = target.mesh.scale.x + headLength * 0.58;
    mesh.position.copy(target.mesh.position).addScaledVector(arrowDirection, -back);
    mesh.quaternion.setFromUnitVectors(arrowUp, arrowDirection);
  }
}

/* ---------------------------------------------------------------- borderless labels */

const measureContext = document.createElement('canvas').getContext('2d');
const projected = new THREE.Vector3();
const clusterScreen = new THREE.Vector3();
const clusterDown = new THREE.Vector3();

function placeClusterLabels() {
  const level = getViewLevel();
  const activeViews = level === 'subjects'
    ? subjectViews
    : level === 'communities'
      ? clusterViews.filter((v) => activeSubjectIndex === null || v.subjectIndex === activeSubjectIndex)
      : [];

  for (const view of subjectViews) {
    if (level !== 'subjects') {
      view.label.style.opacity = '0';
      view.label.style.pointerEvents = 'none';
    }
  }
  for (const view of clusterViews) {
    if (level !== 'communities' || (activeSubjectIndex !== null && view.subjectIndex !== activeSubjectIndex)) {
      view.label.style.opacity = '0';
      view.label.style.pointerEvents = 'none';
    }
  }
  if (!activeViews.length) return;

  const placedRects = [];
  const tanHalf = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  const ordered = activeViews.slice().sort((a, b) => b.members.size - a.members.size);

  // Reserve screen circles around visible orbs so no nebula name ever crosses another orb.
  for (const view of ordered) {
    if (!view.orb.visible) continue;
    const anchor = view.activeCentre || view.centre;
    clusterScreen.copy(anchor).project(camera);
    if (clusterScreen.z > 1) continue;
    const dist = Math.max(1, camera.position.distanceTo(anchor));
    const pr = (view.orbRadius * height) / (2 * dist * tanHalf) + 4;
    const sx = (clusterScreen.x * 0.5 + 0.5) * width;
    const sy = (-clusterScreen.y * 0.5 + 0.5) * height;
    placedRects.push({ l: sx - pr, r: sx + pr, t: sy - pr, b: sy + pr });
  }

  for (const view of ordered) {
    if (!view.orb.visible || !view.titleText) {
      view.label.style.opacity = '0';
      view.label.style.pointerEvents = 'none';
      continue;
    }
    const anchor = view.activeCentre || view.centre;
    clusterScreen.copy(anchor).project(camera);
    if (clusterScreen.z > 1 || clusterScreen.x < -1.08 || clusterScreen.x > 1.08 || clusterScreen.y < -1.08 || clusterScreen.y > 1.08) {
      view.label.style.opacity = '0';
      view.label.style.pointerEvents = 'none';
      continue;
    }
    const dist = Math.max(1, camera.position.distanceTo(anchor));
    const pxRadius = (view.orbRadius * height) / (2 * dist * tanHalf);
    const w = view.label.offsetWidth || 96;
    const h = 15;
    const sx = (clusterScreen.x * 0.5 + 0.5) * width;
    const sy = (-clusterScreen.y * 0.5 + 0.5) * height;
    const candidates = [
      [sx, sy + pxRadius + 18],
      [sx, sy - pxRadius - 18],
      [sx + pxRadius + w / 2 + 12, sy],
      [sx - pxRadius - w / 2 - 12, sy],
    ];
    let placedPos = null;
    for (const [cxRaw, cyRaw] of candidates) {
      const cx = THREE.MathUtils.clamp(cxRaw, w / 2 + 8, width - w / 2 - 8);
      const cy = THREE.MathUtils.clamp(cyRaw, 66, height - 46);
      const rect = { l: cx - w / 2 - 5, r: cx + w / 2 + 5, t: cy - h / 2 - 4, b: cy + h / 2 + 4 };
      if (!placedRects.some((o) => rect.l < o.r && rect.r > o.l && rect.t < o.b && rect.b > o.t)) {
        placedPos = { cx, cy, rect };
        break;
      }
    }
    if (!placedPos) {
      view.label.style.opacity = '0';
      view.label.style.pointerEvents = 'none';
      continue;
    }
    placedRects.push(placedPos.rect);
    view.label.style.transform = `translate3d(${placedPos.cx.toFixed(1)}px, ${placedPos.cy.toFixed(1)}px, 0) translate(-50%, -50%)`;
    view.label.style.opacity = '0.94';
    view.label.style.pointerEvents = 'auto';
  }
}

function labelFor(obj) {
  if (!obj.label) {
    const title = obj.node.title;
    const text = title.length > 26 ? `${title.slice(0, 25)}…` : title;
    const el = document.createElement('div');
    el.className = 'label';
    el.textContent = text;
    labelsEl.appendChild(el);
    measureContext.font = '600 10px -apple-system, system-ui, sans-serif';
    el.__width = measureContext.measureText(text).width + 4;
    el.__class = 'label';
    obj.label = el;
  }
  return obj.label;
}

const overlapArea = (a, b) => {
  const ix = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
  const iy = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
  return ix * iy;
};

function placeLabels() {
  if (isOverviewMode()) {
    for (const obj of shownLabels) if (obj.label) obj.label.style.display = 'none';
    shownLabels = new Set();
    return;
  }

  const selected = selectedObject();
  const selectedId = selected ? selected.node.id : null;
  const candidates = [];
  for (const obj of objects.values()) {
    if (!obj.visible || obj.dimmed) continue;
    const id = obj.node.id;
    const score = id === selectedId ? 1e6
      : (selectedId && neighborIds.has(id)) ? 1e5 + obj.node.degree
      : state.highlightIds.has(id) ? 5e4 + obj.node.degree
      : obj.node.degree * 10 + (obj.node.size ?? 1) * 5 + obj.pxRadius * 2;
    candidates.push([score, obj]);
  }
  candidates.sort((a, b) => b[0] - a[0] || (a[1].node.id < b[1].node.id ? -1 : 1));

  const placed = [];
  const shown = new Set();
  const cap = focusView ? 20 : COMMUNITY_LABEL_CAP;
  let centerScreenX = width * 0.5;
  let centerScreenY = height * 0.45;
  if (selected && selected.visible) {
    projected.copy(selected.mesh.position).project(camera);
    centerScreenX = ((projected.x + 1) / 2) * width;
    centerScreenY = ((1 - projected.y) / 2) * height;
  }

  // Reserve all visible spheres so labels never overlap another concept dot.
  for (const [, obj] of candidates) {
    projected.copy(obj.mesh.position).project(camera);
    if (projected.z <= 1) {
      const sx = ((projected.x + 1) / 2) * width;
      const sy = ((1 - projected.y) / 2) * height;
      const r = obj.pxRadius + 3;
      placed.push([sx - r, sy - r, sx + r, sy + r]);
    }
  }

  for (const [, obj] of candidates) {
    const isSelected = obj.node.id === selectedId;
    const isProtected = isSelected || (selectedId && neighborIds.has(obj.node.id)) || state.highlightIds.has(obj.node.id);
    if (!isProtected && shown.size >= cap) continue;
    if (shown.size >= 40) break;

    projected.copy(obj.mesh.position).project(camera);
    if (projected.z > 1 || projected.x < -1.06 || projected.x > 1.06 || projected.y < -1.06 || projected.y > 1.06) continue;

    const label = labelFor(obj);
    const labelW = label.__width * (isSelected ? 1.15 : 1);
    const labelH = isSelected ? 15 : 13;
    const sx = ((projected.x + 1) / 2) * width;
    const sy = ((1 - projected.y) / 2) * height;
    const pad = obj.pxRadius + 6;
    const outX = sx >= centerScreenX ? 1 : -1;
    const outY = sy >= centerScreenY ? 1 : -1;

    const slotCenters = [
      [sx, sy - (pad + labelH / 2)],
      [sx, sy + (pad + labelH / 2)],
      [sx + outX * (pad + labelW / 2), sy],
      [sx - outX * (pad + labelW / 2), sy],
      [sx + outX * (pad + labelW * 0.45), sy + outY * (pad + labelH * 0.7)],
      [sx - outX * (pad + labelW * 0.45), sy + outY * (pad + labelH * 0.7)],
    ];

    let chosen = null;
    let bestFallback = null;
    let bestOverlap = Infinity;
    for (const [cxRaw, cyRaw] of slotCenters) {
      const cx = THREE.MathUtils.clamp(cxRaw, labelW / 2 + 6, width - labelW / 2 - 6);
      const cy = THREE.MathUtils.clamp(cyRaw, 58, height - 20);
      const rect = [cx - labelW / 2 - 5, cy - labelH / 2 - 4, cx + labelW / 2 + 5, cy + labelH / 2 + 4];
      let area = 0;
      for (const p of placed) area += overlapArea(rect, p);
      if (area === 0) {
        chosen = { cx, cy, rect };
        break;
      }
      if (area < bestOverlap) {
        bestOverlap = area;
        bestFallback = { cx, cy, rect };
      }
    }

    if (!chosen) {
      if (!isSelected) continue;
      chosen = bestFallback;
    }

    placed.push(chosen.rect);
    shown.add(obj);
    const className = isSelected ? 'label selected' : (selectedId && neighborIds.has(obj.node.id)) ? 'label neighbor' : 'label';
    if (label.__class !== className) { label.className = className; label.__class = className; }
    label.style.transform = `translate3d(${chosen.cx.toFixed(1)}px, ${(chosen.cy - labelH / 2).toFixed(1)}px, 0) translateX(-50%)`;
    label.style.display = 'block';
  }
  for (const obj of shownLabels) if (!shown.has(obj) && obj.label) obj.label.style.display = 'none';
  shownLabels = shown;
}

/* ---------------------------------------------------------------- render loop */

const forward = new THREE.Vector3();
const offset = new THREE.Vector3();

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
  composer.render();
  placeLabels();
  placeClusterLabels();
}

function applyViewOffset() {
  if (viewShift <= 0) camera.clearViewOffset();
  else camera.setViewOffset(width, height, 0, height * viewShift, width, height);
}

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
    if (camera.position.distanceTo(cameraFlight.position) < 0.35) {
      camera.position.copy(cameraFlight.position);
      controls.target.copy(cameraFlight.target);
      cameraFlight = null;
      prevCameraDist = camera.position.distanceTo(controls.target);
    }
    animating = true;
  }
  const moved = controls.update();
  if (updateViewShift()) animating = true;
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

function frameAll(animated) {
  const box = new THREE.Box3();
  const level = getViewLevel();
  if (level === 'subjects') {
    for (const v of subjectViews) if (v.orb.visible) box.expandByPoint(v.centre);
  } else if (level === 'communities') {
    for (const v of clusterViews) if (v.orb.visible) box.expandByPoint(v.activeCentre || v.centre);
  } else {
    for (const obj of objects.values()) if (obj.visible) box.expandByPoint(obj.mesh.position);
  }
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const half = box.getSize(new THREE.Vector3()).multiplyScalar(0.5).addScalar(58);
  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);
  const distance = Math.max(80, half.x / Math.tan(hFov / 2) + half.z, half.y / Math.tan(vFov / 2) + half.z);
  controls.maxDistance = Math.max(1200, distance * 2.8);
  camera.far = Math.max(4000, distance * 4);
  camera.updateProjectionMatrix();
  const position = center.clone().add(new THREE.Vector3(0, 0, distance));
  if (animated) {
    cameraFlight = { target: center, position };
  } else {
    cameraFlight = null;
    camera.position.copy(position);
    controls.target.copy(center);
    controls.update();
    prevCameraDist = distance;
  }
  invalidate();
}

/* ---------------------------------------------------------------- touch interaction */

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

function pickCluster(clientX, clientY) {
  const level = getViewLevel();
  if (level !== 'subjects' && level !== 'communities') return null;
  const kind = level === 'subjects' ? 'subject' : 'community';
  const pool = level === 'subjects' ? subjectViews : clusterViews;
  const rect = ndcFrom(clientX, clientY);
  raycaster.setFromCamera(pointerNdc, camera);
  const orbs = pool.filter((v) => v.orb.visible).map((v) => v.orb);
  const hit = raycaster.intersectObjects(orbs, false)[0];
  if (hit) {
    const idx = hit.object.userData.viewIndex;
    const view = pool.find((v) => v.index === idx) || null;
    return view ? { kind, view } : null;
  }
  // Generous screen-space tap radius on nebula orbs.
  let best = null;
  let bestDist = Infinity;
  for (const view of pool) {
    if (!view.orb.visible) continue;
    const anchor = view.activeCentre || view.centre;
    projected.copy(anchor).project(camera);
    if (projected.z > 1) continue;
    const sx = rect.left + ((projected.x + 1) / 2) * rect.width;
    const sy = rect.top + ((1 - projected.y) / 2) * rect.height;
    const d = Math.hypot(sx - clientX, sy - clientY);
    if (d < 40 && d < bestDist) {
      bestDist = d;
      best = view;
    }
  }
  return best ? { kind, view: best } : null;
}

function pickNode(clientX, clientY) {
  if (isOverviewMode()) return null;
  const rect = ndcFrom(clientX, clientY);
  raycaster.setFromCamera(pointerNdc, camera);
  const meshes = [];
  for (const obj of objects.values()) if (obj.visible) meshes.push(obj.mesh);
  const hit = raycaster.intersectObjects(meshes, false)[0];
  if (hit) return hit.object.userData.nodeId;

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
  const clusterHit = pickCluster(x, y);
  if (clusterHit) {
    lastEmptyTap = null;
    if (clusterHit.kind === 'subject') enterSubject(clusterHit.view.index);
    else enterCluster(clusterHit.view.index);
    return;
  }
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
    if (!isOverviewMode()) {
      const point = worldPointAt(x, y);
      let nearest = null;
      let min = Infinity;
      for (const obj of objects.values()) {
        if (!obj.visible) continue;
        const d = obj.mesh.position.distanceTo(point);
        if (d < min) { min = d; nearest = obj.node.id; }
      }
      if (nearest) flyToNode(nearest);
    }
    return;
  }
  lastEmptyTap = { x, y, time: now };
  if (!state.mergeMode && state.selectedId) selectNode(null);
}

function cancelGesture() {
  if (!gesture) return;
  gesture.cancelled = true;
  clearTimeout(gesture.longPressTimer);
}

renderer.domElement.addEventListener('pointerdown', (e) => {
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size > 1) { cancelGesture(); return; }
  cameraFlight = null;
  const g = { x: e.clientX, y: e.clientY, time: performance.now(), cancelled: false, longPressed: false };
  g.longPressTimer = setTimeout(() => {
    if (g.cancelled || pointers.size !== 1) return;
    g.longPressed = true;
    if (pickCluster(g.x, g.y) || pickNode(g.x, g.y)) return;
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
  composer.setSize(width, height);
  bloomPass.setSize(width, height);
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
    activeSubjectIndex = null;
    activeClusterIndex = null;
    skippedCommunities = false;
    setStatus('');
    invalidate();
    postNavState();
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
  if (pendingClusterQuery) {
    const q = pendingClusterQuery;
    pendingClusterQuery = null;
    if (window.enterClusterByTitle(q)) {
      post({ type: 'layout', running: false, nodes: result.nodes.length });
      return;
    }
  }
  if (isFirstLayout && !state.selectedId && activeClusterIndex === null && activeSubjectIndex === null) {
    frameAll(false);
  }
  postNavState();
  post({ type: 'layout', running: false, nodes: result.nodes.length });
};

let lastVisibilityKey = '';

window.setGraphState = function setGraphState(next) {
  next = next || {};
  const visArr = Array.isArray(next.visibleIds) ? next.visibleIds.slice().sort() : null;
  const nextVisibilityKey = `${next.domain || '*'}|${visArr ? visArr.join(',') : '*'}`;
  const visibilityChanged = lastVisibilityKey !== '' && lastVisibilityKey !== nextVisibilityKey;
  lastVisibilityKey = nextVisibilityKey;

  if (visibilityChanged && (visArr !== null || (next.domain || null) !== null)) {
    activeSubjectIndex = null;
    activeClusterIndex = null;
    skippedCommunities = false;
    restoreCommunityPositions();
  }

  state.selectedId = next.selectedId || null;
  state.highlightIds = new Set(next.highlightIds || []);
  state.visibleIds = visArr ? new Set(visArr) : null;
  state.domain = next.domain || null;
  state.minWeight = typeof next.minWeight === 'number' ? next.minWeight : 0;
  state.colorMode = next.colorMode || 'community';
  state.mergeMode = !!next.mergeMode;
  state.mergeTargetIds = new Set(next.mergeTargetIds || []);
  applyState();
  postNavState();
  if (visibilityChanged && !state.selectedId && graph) {
    frameAll(true);
  }
};

window.setGraphInsets = function setGraphInsets(bottom) {
  insetBottom = Math.min(0.9, Math.max(0, Number(bottom) || 0));
  invalidate();
};

window.resetCamera = function resetCamera() {
  if (focusView) {
    state.selectedId = null;
    applyState();
    post({ type: 'select', id: null });
  }
  if (activeClusterIndex !== null || activeSubjectIndex !== null) {
    exitLevel();
  } else {
    frameAll(true);
  }
};

window.exitCluster = function() {
  exitLevel();
};

window.enterClusterByTitle = function(query) {
  const q = String(query || '').trim().toLowerCase();
  if (!q) return false;
  if (!clusterViews.length && !subjectViews.length) {
    pendingClusterQuery = q;
    return false;
  }
  const cMatch = clusterViews.find((v) => v.titleText.toLowerCase() === q)
    || clusterViews.find((v) => v.titleText.toLowerCase().includes(q));
  if (cMatch) {
    enterCluster(cMatch.index);
    return true;
  }
  const sMatch = subjectViews.find((v) => v.titleText.toLowerCase() === q)
    || subjectViews.find((v) => v.titleText.toLowerCase().includes(q));
  if (sMatch) {
    enterSubject(sMatch.index);
    return true;
  }
  return false;
};

requestAnimationFrame(tick);
post({ type: 'ready' });
