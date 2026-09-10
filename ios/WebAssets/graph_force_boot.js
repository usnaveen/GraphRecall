const root = document.getElementById('graph');
const Graph = ForceGraph()(root)
  .backgroundColor('#07070A')
  .nodeId('id')
  .nodeLabel(n => n.name || n.id)
  .nodeColor(n => n.__highlight ? '#B6FF2E' : (n.color || '#7C3AED'))
  .nodeVal(n => n.val || 1)
  .linkColor(() => 'rgba(182,255,46,0.28)')
  .linkWidth(l => Math.max(0.6, (l.strength || 0.5) * 2))
  .linkDirectionalParticles(1)
  .linkDirectionalParticleWidth(1.2)
  .onNodeClick(n => {
    try { window.webkit.messageHandlers.graphBridge.postMessage({ id: n.id }); } catch (e) {}
  })
  .onBackgroundClick(() => {
    try { window.webkit.messageHandlers.graphBridge.postMessage({ id: null }); } catch (e) {}
  });

function resize() {
  Graph.width(window.innerWidth).height(window.innerHeight);
}
window.addEventListener('resize', resize);
resize();

window.setGraphData = function(data, highlightIds) {
  const hl = new Set(highlightIds || []);
  const nodes = (data.nodes || []).map(n => Object.assign({}, n, { __highlight: hl.has(n.id) }));
  const links = (data.links || []).map(l => Object.assign({}, l));
  Graph.graphData({ nodes, links });
  if (hl.size === 1) {
    const id = [...hl][0];
    const node = nodes.find(n => n.id === id);
    if (node) Graph.centerAt(node.x || 0, node.y || 0, 600);
  }
};

try { window.webkit.messageHandlers.graphBridge.postMessage({ type: 'ready' }); } catch (e) {}
