import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Text, Sphere, Line } from "@react-three/drei";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/examples/jsm/postprocessing/ShaderPass.js";

import { calculateLinkThickness } from "../../lib/forceSimulation3d";
import type { GraphLayout, Node3D, Link3D } from "../../lib/forceSimulation3d";
import type { Community } from "../../lib/graphData";
import GalaxyBackground from "./GalaxyBackground";

const BLOOM_SCENE = 1;

// Threshold: links with weight >= this get energy tube treatment
const ENERGY_TUBE_WEIGHT_THRESHOLD = 0.7;

// Parent/child coloring
const PARENT_COLOR = "#3B82F6";  // blue
const CHILD_COLOR = "#10B981";   // green
const MERGE_TARGET_COLOR = "#F97316"; // orange for merge targets

function useBillboard() {
  const ref = useRef<THREE.Object3D>(null);
  useFrame(({ camera }) => {
    if (ref.current) {
      ref.current.lookAt(camera.position);
    }
  });
  return ref;
}

function Node({
  node,
  isSelected,
  isHighlighted,
  isMergeTarget,
  colorOverride,
  onClick,
  onPointerOver,
  onPointerOut,
  onContextMenu,
  showLabel,
  springTarget,
}: {
  node: Node3D;
  isSelected: boolean;
  isHighlighted: boolean;
  isMergeTarget?: boolean;
  colorOverride?: string;
  onClick: (node: Node3D) => void;
  onPointerOver: (node: Node3D) => void;
  onPointerOut: () => void;
  onContextMenu?: () => void;
  showLabel: boolean;
  springTarget?: THREE.Vector3 | null;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const groupRef = useRef<THREE.Group>(null);
  const textRef = useBillboard();
  const originalPos = useRef(new THREE.Vector3(node.x, node.y, node.z));

  // Update original position when node data changes
  useEffect(() => {
    originalPos.current.set(node.x, node.y, node.z);
  }, [node.x, node.y, node.z]);

  const nodeColor = colorOverride || node.computedColor;

  useFrame(() => {
    if (meshRef.current) {
      const scale = isSelected ? 1.5 : isHighlighted || isMergeTarget ? 1.2 : 1.0;
      meshRef.current.scale.setScalar(scale);
    }

    // Spring animation: pull connected nodes closer to selected
    if (groupRef.current) {
      if (springTarget && !isSelected) {
        // Move 35% closer to the selected node
        const desired = originalPos.current.clone().lerp(springTarget, 0.35);
        groupRef.current.position.lerp(desired, 0.06);
      } else {
        // Lerp back to original position
        groupRef.current.position.lerp(originalPos.current, 0.06);
      }
    }
  });

  return (
    <group ref={groupRef} position={[node.x, node.y, node.z]}>
      <Sphere
        ref={meshRef}
        args={[node.computedSize, 24, 24]}
        onClick={() => onClick(node)}
        onPointerOver={() => onPointerOver(node)}
        onPointerOut={onPointerOut}
        onContextMenu={(event) => {
          event.stopPropagation();
          event.nativeEvent.preventDefault();
          onContextMenu?.();
        }}
        onUpdate={(m) => {
          m.layers.enable(BLOOM_SCENE);
        }}
      >
        <meshStandardMaterial
          color={nodeColor}
          emissive={nodeColor}
          emissiveIntensity={isMergeTarget ? 0.5 : 0.25}
        />
      </Sphere>
      {/* Merge target ring */}
      {isMergeTarget && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[node.computedSize * 1.4, node.computedSize * 1.7, 32]} />
          <meshBasicMaterial color={MERGE_TARGET_COLOR} transparent opacity={0.7} side={THREE.DoubleSide} />
        </mesh>
      )}
      {showLabel && (
        <group ref={textRef} position={[0, node.computedSize + 2.5, 0]}>
          <Text
            fontSize={Math.max(0.8, node.computedSize * 0.6)}
            color={isSelected || isHighlighted ? "white" : "rgba(255,255,255,0.8)"}
            outlineWidth={0.05}
            outlineColor="black"
            anchorX="center"
            anchorY="middle"
            maxWidth={40}
            textAlign="center"
            userData={{ isText: true }}
          >
            {node.title.length > 30 ? `${node.title.substring(0, 30)}...` : node.title}
          </Text>
        </group>
      )}
    </group>
  );
}

function Link({ link, isHighlighted, sourceNodeId, targetNodeId }: { link: Link3D; isHighlighted: boolean; sourceNodeId?: string; targetNodeId?: string }) {
  const lineRef = useRef<any>(null);
  const points = useMemo(() => {
    return [
      new THREE.Vector3(link.source.x, link.source.y, link.source.z),
      new THREE.Vector3(link.target.x, link.target.y, link.target.z),
    ];
  }, [link.source.x, link.source.y, link.source.z, link.target.x, link.target.y, link.target.z]);

  const thickness = useMemo(() => calculateLinkThickness(link.weight), [link.weight]);
  const baseOpacity = isHighlighted ? 0.9 : 0.5;

  // Determine color based on relationship type and direction
  const REL_COLORS: Record<string, string> = {
    PREREQUISITE_OF: "#2EFFE6",
    SUBTOPIC_OF: "#9B59B6",
    BUILDS_ON: "#F59E0B",
    RELATED_TO: "#FFFFFF",
    PART_OF: "#EC4899",
  };
  let color = isHighlighted ? "#ffffff" : "#888888";
  if (isHighlighted) {
    // Color by relationship type first, fallback to direction-based
    const relType = link.description?.toUpperCase();
    if (relType && REL_COLORS[relType]) {
      color = REL_COLORS[relType];
    } else if (sourceNodeId && link.source.id === sourceNodeId) {
      color = "#2EFFE6";
    } else if (targetNodeId && link.target.id === targetNodeId) {
      color = "#DF2EFF";
    }
  }

  useFrame(({ clock }) => {
    if (!lineRef.current) return;
    const t = (Math.sin(clock.elapsedTime * 3) + 1) / 2;
    const pulse = isHighlighted ? t : 0;
    lineRef.current.material.opacity = baseOpacity + pulse * 0.35;
    if (lineRef.current.material.linewidth !== undefined) {
      lineRef.current.material.linewidth = (isHighlighted ? thickness * 2 : thickness) * (1 + pulse * 0.4);
    }
    lineRef.current.material.color.set(color);
  });
  return (
    <Line
      ref={lineRef}
      points={points}
      color={color}
      lineWidth={isHighlighted ? thickness * 2.5 : thickness}
      transparent
      opacity={baseOpacity}
    />
  );
}

// Animated energy tube for strong relationships
function EnergyEdge({ link }: { link: Link3D }) {
  const meshRef = useRef<THREE.Mesh>(null);

  const curve = useMemo(() => {
    const src = new THREE.Vector3(link.source.x, link.source.y, link.source.z);
    const tgt = new THREE.Vector3(link.target.x, link.target.y, link.target.z);
    return new THREE.CatmullRomCurve3([src, tgt]);
  }, [link.source.x, link.source.y, link.source.z, link.target.x, link.target.y, link.target.z]);

  const tubularSegments = 32;
  const radius = useMemo(() => Math.max(0.06, calculateLinkThickness(link.weight) * 0.25), [link.weight]);
  const radialSegments = 6;
  const closed = false;

  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        uniforms: {
          time: { value: 0.0 },
          c1: { value: new THREE.Color("#6be6ff") },
          c2: { value: new THREE.Color("#ff8bcb") },
        },
        vertexShader: `
      varying float vLen;
      void main(){ vLen = position.y; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }
    `,
        fragmentShader: `
      uniform float time; uniform vec3 c1,c2; varying float vLen;
      void main(){
        float t = fract(vLen*0.1 - time*0.8);
        float band = smoothstep(0.0,0.05,t)*smoothstep(0.2,0.15,t);
        vec3 col = mix(c1,c2, t);
        gl_FragColor = vec4(col*(0.5+band*2.0), 0.7);
      }
    `,
      }),
    []
  );

  useFrame((state) => {
    (mat.uniforms.time as { value: number }).value = state.clock.getElapsedTime();
  });

  return (
    <mesh ref={meshRef} onUpdate={(m) => m.layers.enable(BLOOM_SCENE)}>
      <tubeGeometry args={[curve, tubularSegments, radius, radialSegments, closed]} />
      <primitive object={mat} attach="material" />
    </mesh>
  );
}

function CommunityBoundary({ community }: { community: Community }) {
  if (!community.computedBounds) return null;
  const bounds = community.computedBounds;
  return (
    <mesh position={bounds.center}>
      <boxGeometry args={bounds.size} />
      <meshBasicMaterial
        color={community.computedColor || "#95a5a6"}
        transparent
        opacity={community.computedOpacity || 0.12}
        wireframe
      />
    </mesh>
  );
}

function CommunityGlow({ community }: { community: Community }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const { camera } = useThree();

  if (!community.computedBounds) return null;
  const bounds = community.computedBounds;

  const radius = Math.max(...bounds.size) * 0.6;

  useFrame(() => {
    if (meshRef.current) {
      // Global Zoom Check: visible only when zoomed out (Overview Mode)
      const distToOrigin = camera.position.length();
      // Fade out between 200 (visible) and 100 (hidden)
      const fade = Math.min(1, Math.max(0, (distToOrigin - 100) / 100));

      if (fade <= 0.01) {
        meshRef.current.visible = false;
      } else {
        meshRef.current.visible = true;
        const t = Date.now() * 0.001;
        const pulse = 0.9 + Math.sin(t) * 0.1;
        meshRef.current.scale.setScalar(pulse);
        (meshRef.current.material as THREE.MeshBasicMaterial).opacity = 0.15 * fade;
      }
    }
  });

  return (
    <mesh ref={meshRef} position={bounds.center}>
      <sphereGeometry args={[radius, 32, 32]} />
      <meshBasicMaterial
        color={community.computedColor || "#2A2A35"}
        transparent
        opacity={0.1}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </mesh>
  );
}

// Enhanced post-processing: Bloom + Vignette
function PostProcessing({ strength, isMobile }: { strength: number; isMobile: boolean }) {
  const { gl, scene, camera, size } = useThree();
  const composerRef = useRef<EffectComposer | null>(null);

  useEffect(() => {
    const comp = new EffectComposer(gl);
    comp.setSize(size.width, size.height);

    // Render pass
    const renderPass = new RenderPass(scene, camera);
    comp.addPass(renderPass);

    // Bloom pass with tuned settings
    const bloomPass = new UnrealBloomPass(
      new THREE.Vector2(size.width, size.height),
      strength,
      isMobile ? 0.4 : 0.8, // radius
      0.2 // threshold
    );
    comp.addPass(bloomPass);

    // Vignette pass - darkens screen edges for cinematic look
    if (!isMobile) {
      const VignetteShader = {
        uniforms: {
          tDiffuse: { value: null },
          strength: { value: 0.18 },
        },
        vertexShader: `
          varying vec2 vUv;
          void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }
        `,
        fragmentShader: `
          uniform sampler2D tDiffuse; uniform float strength; varying vec2 vUv;
          void main(){
            vec4 c = texture2D(tDiffuse, vUv);
            float d = distance(vUv, vec2(0.5));
            float v = smoothstep(0.6, 0.98, d);
            c.rgb *= (1.0 - v * strength);
            gl_FragColor = c;
          }
        `,
      };
      const vignettePass = new ShaderPass(VignetteShader);
      comp.addPass(vignettePass);
    }

    composerRef.current = comp;

    return () => {
      comp.dispose();
    };
  }, [gl, scene, camera, size.width, size.height, strength, isMobile]);

  useFrame(() => {
    composerRef.current?.render();
  }, 1);

  return null;
}

export type GraphVisualizerProps = {
  layout: GraphLayout | null;
  selectedNode: Node3D | null;
  hoveredNode: Node3D | null;
  onNodeSelect: (node: Node3D | null) => void;
  onNodeHover?: (node: Node3D | null) => void;
  showCommunities: boolean;
  searchTerm: string;
  visibleNodeIds?: Set<string>;
  showLabels: boolean;
  isMobile: boolean;
  onEmptyContextMenu?: (point: { x: number; y: number; z: number }) => void;
  onDoubleClickEmpty?: (point: { x: number; y: number; z: number }) => void;
  focusNodeId?: string | null;
  pulseNodeId?: string | null;
  // Controls props
  minRelationshipWeight?: number;
  selectedDomain?: string | null;
  // Merge mode
  mergeMode?: boolean;
  mergeTargetIds?: Set<string>;
  // Parent/child coloring
  parentNodeIds?: Set<string>;
  childNodeIds?: Set<string>;
  connectedNodeIds?: Set<string>;
};

function GraphScene({
  layout,
  selectedNode,
  hoveredNode,
  onNodeSelect,
  onNodeHover,
  showCommunities,
  searchTerm,
  visibleNodeIds,
  showLabels,
  isMobile,
  onEmptyContextMenu,
  onDoubleClickEmpty,
  focusNodeId,
  pulseNodeId,
  minRelationshipWeight = 0,
  selectedDomain,
  mergeMode,
  mergeTargetIds,
  parentNodeIds,
  childNodeIds,
  connectedNodeIds,
}: GraphVisualizerProps) {
  const nodes = layout?.nodes || [];
  const links = layout?.links || [];
  const controlsRef = useRef<any>(null);
  const focusRef = useRef<{ target: THREE.Vector3; position: THREE.Vector3; active: boolean } | null>(null);

  const highlightedIds = useMemo(() => {
    if (!searchTerm) return new Set<string>();
    const lower = searchTerm.toLowerCase();
    return new Set(nodes.filter((n) => n.title.toLowerCase().includes(lower)).map((n) => n.id));
  }, [searchTerm, nodes]);

  const visibleNodes = useMemo(() => {
    let filtered = nodes;
    if (visibleNodeIds) {
      filtered = filtered.filter((n) => visibleNodeIds.has(n.id));
    }
    if (selectedDomain) {
      filtered = filtered.filter((n) => n.domain === selectedDomain);
    }
    return filtered;
  }, [nodes, visibleNodeIds, selectedDomain]);

  const visibleNodeIdSet = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes]);

  const visibleLinks = useMemo(() => {
    let filtered = links.filter(
      (l) => visibleNodeIdSet.has(l.source.id) && visibleNodeIdSet.has(l.target.id)
    );
    if (minRelationshipWeight > 0) {
      filtered = filtered.filter((l) => l.weight >= minRelationshipWeight);
    }
    return filtered;
  }, [links, visibleNodeIdSet, minRelationshipWeight]);

  // Separate strong links for energy tube rendering
  const { regularLinks, energyLinks } = useMemo(() => {
    const regular: Link3D[] = [];
    const energy: Link3D[] = [];
    for (const link of visibleLinks) {
      if (link.weight >= ENERGY_TUBE_WEIGHT_THRESHOLD) {
        energy.push(link);
      }
      // Always render the regular line too (energy is an overlay)
      regular.push(link);
    }
    return { regularLinks: regular, energyLinks: energy };
  }, [visibleLinks]);

  const visibleCommunities = useMemo(() => {
    if (!layout?.communities) return [];
    if (!visibleNodeIds) return layout.communities;
    return layout.communities.filter((community) =>
      community.entity_ids.some((id) => visibleNodeIdSet.has(id))
    );
  }, [layout?.communities, visibleNodeIds, visibleNodeIdSet]);

  const focusNode = useMemo(() => {
    if (!focusNodeId) return null;
    return nodes.find((n) => n.id === focusNodeId) || null;
  }, [nodes, focusNodeId]);

  // Spring target: when a node is selected, connected nodes spring toward it
  const springTarget = useMemo(() => {
    if (!selectedNode) return null;
    return new THREE.Vector3(selectedNode.x, selectedNode.y, selectedNode.z);
  }, [selectedNode]);

  const { camera } = useThree();

  useEffect(() => {
    if (!focusNode) return;
    const controls = controlsRef.current;
    const target = new THREE.Vector3(focusNode.x, focusNode.y, focusNode.z);
    const currentTarget = controls?.target ? controls.target.clone() : new THREE.Vector3(0, 0, 0);

    // Zoom closer for better visibility, especially on mobile
    const distance = isMobile ? 60 : 80;
    const direction = camera.position.clone().sub(currentTarget).normalize();
    const desiredPosition = target.clone().add(direction.multiplyScalar(distance));
    focusRef.current = { target, position: desiredPosition, active: true };
  }, [focusNode, camera, isMobile]);

  useFrame(() => {
    if (!focusRef.current?.active) return;
    const controls = controlsRef.current;
    const target = focusRef.current.target;
    const position = focusRef.current.position;
    camera.position.lerp(position, 0.08);
    if (controls?.target) {
      controls.target.lerp(target, 0.08);
      controls.update();
    }
    if (camera.position.distanceTo(position) < 1.5) {
      focusRef.current.active = false;
    }
  });

  // Compute color overrides for parent/child nodes
  const getNodeColorOverride = (nodeId: string): string | undefined => {
    if (!selectedNode) return undefined;
    if (parentNodeIds?.has(nodeId)) return PARENT_COLOR;
    if (childNodeIds?.has(nodeId)) return CHILD_COLOR;
    if (mergeTargetIds?.has(nodeId)) return MERGE_TARGET_COLOR;
    return undefined;
  };

  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[100, 100, 100]} intensity={1.2} />
      <GalaxyBackground />

      <group>
        {/* Background plane for context menu and double-click navigation */}
        <mesh
          position={[0, 0, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
          onContextMenu={(event) => {
            if (onEmptyContextMenu) {
              event.stopPropagation();
              event.nativeEvent.preventDefault();
              onEmptyContextMenu({ x: event.point.x, y: event.point.y, z: event.point.z });
            }
          }}
          onDoubleClick={(event) => {
            if (onDoubleClickEmpty) {
              event.stopPropagation();
              onDoubleClickEmpty({ x: event.point.x, y: event.point.y, z: event.point.z });
            }
          }}
        >
          <planeGeometry args={[3000, 3000]} />
          <meshBasicMaterial transparent opacity={0} />
        </mesh>
        {showCommunities && visibleCommunities.map((c) => (
          <group key={c.id}>
            <CommunityBoundary community={c} />
            <CommunityGlow community={c} />
          </group>
        ))}
        {regularLinks.map((link) => {
          const isHighlighted =
            (selectedNode && (link.source.id === selectedNode.id || link.target.id === selectedNode.id)) ||
            (hoveredNode && (link.source.id === hoveredNode.id || link.target.id === hoveredNode.id));
          const isPulse =
            !!pulseNodeId && (link.source.id === pulseNodeId || link.target.id === pulseNodeId);
          return <Link key={link.id} link={link} isHighlighted={!!isHighlighted || isPulse} sourceNodeId={selectedNode?.id} targetNodeId={selectedNode?.id} />;
        })}
        {/* Energy tubes overlay for strong relationships */}
        {energyLinks.map((link) => (
          <EnergyEdge key={`energy-${link.id}`} link={link} />
        ))}
        {visibleNodes.map((node) => (
          <Node
            key={node.id}
            node={node}
            isSelected={selectedNode?.id === node.id}
            isHighlighted={highlightedIds.has(node.id) || hoveredNode?.id === node.id}
            isMergeTarget={mergeTargetIds?.has(node.id)}
            colorOverride={getNodeColorOverride(node.id)}
            onClick={(n) => onNodeSelect(n)}
            onPointerOver={(n) => onNodeHover?.(n)}
            onPointerOut={() => onNodeHover?.(null)}
            showLabel={showLabels || selectedNode?.id === node.id || hoveredNode?.id === node.id}
            springTarget={connectedNodeIds?.has(node.id) ? springTarget : null}
          />
        ))}
      </group>

      <OrbitControls
        ref={controlsRef}
        enablePan
        enableZoom
        enableRotate
        minDistance={isMobile ? 5 : 20}
        maxDistance={500}
        zoomSpeed={isMobile ? 2.0 : 1.0}
        rotateSpeed={isMobile ? 1.2 : 0.8}
      />
      <PostProcessing strength={isMobile ? 0.4 : 0.9} isMobile={isMobile} />
    </>
  );
}

export function GraphVisualizer(props: GraphVisualizerProps) {
  const { isMobile, onNodeSelect } = props;
  return (
    <Canvas
      camera={{ position: [0, 0, 220], fov: 55 }}
      dpr={isMobile ? 1 : [1, 2]}
      onPointerMissed={() => onNodeSelect(null)}
      style={{ width: "100%", height: "100%" }}
    >
      <GraphScene {...props} />
    </Canvas>
  );
}
