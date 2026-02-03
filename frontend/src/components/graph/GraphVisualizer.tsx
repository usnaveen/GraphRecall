import { useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls, Text, Sphere, Line } from "@react-three/drei";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";

import { calculateLinkThickness } from "../../lib/forceSimulation3d";
import type { GraphLayout, Node3D, Link3D } from "../../lib/forceSimulation3d";
import type { Community } from "../../lib/graphData";
import GalaxyBackground from "./GalaxyBackground";

const BLOOM_SCENE = 1;

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
  onClick,
  onPointerOver,
  onPointerOut,
  onContextMenu,
  showLabel,
}: {
  node: Node3D;
  isSelected: boolean;
  isHighlighted: boolean;
  onClick: (node: Node3D) => void;
  onPointerOver: (node: Node3D) => void;
  onPointerOut: () => void;
  onContextMenu?: () => void;
  showLabel: boolean;
}) {
  const meshRef = useRef<THREE.Mesh>(null);
  const textRef = useBillboard();

  useFrame(() => {
    if (meshRef.current) {
      const scale = isSelected ? 1.5 : isHighlighted ? 1.2 : 1.0;
      meshRef.current.scale.setScalar(scale);
    }
  });

  return (
    <group position={[node.x, node.y, node.z]}>
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
        <meshStandardMaterial color={node.computedColor} emissive={node.computedColor} emissiveIntensity={0.25} />
      </Sphere>
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

function Link({ link, isHighlighted }: { link: Link3D; isHighlighted: boolean }) {
  const lineRef = useRef<any>(null);
  const points = useMemo(() => {
    return [
      new THREE.Vector3(link.source.x, link.source.y, link.source.z),
      new THREE.Vector3(link.target.x, link.target.y, link.target.z),
    ];
  }, [link.source.x, link.source.y, link.source.z, link.target.x, link.target.y, link.target.z]);

  const thickness = useMemo(() => calculateLinkThickness(link.weight), [link.weight]);
  const baseOpacity = isHighlighted ? 0.9 : 0.5;

  useFrame(({ clock }) => {
    if (!lineRef.current) return;
    const t = (Math.sin(clock.elapsedTime * 3) + 1) / 2;
    const pulse = isHighlighted ? t : 0;
    lineRef.current.material.opacity = baseOpacity + pulse * 0.35;
    if (lineRef.current.material.linewidth !== undefined) {
      lineRef.current.material.linewidth = (isHighlighted ? thickness * 2 : thickness) * (1 + pulse * 0.4);
    }
  });
  return (
    <Line
      ref={lineRef}
      points={points}
      color={isHighlighted ? "#ffffff" : "#888888"}
      lineWidth={isHighlighted ? thickness * 2 : thickness}
      transparent
      opacity={baseOpacity}
    />
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

function Bloom({ strength }: { strength: number }) {
  const { gl, scene, camera, size } = useThree();
  const composer = useMemo(() => {
    const comp = new EffectComposer(gl);
    comp.addPass(new RenderPass(scene, camera));
    const bloomPass = new UnrealBloomPass(new THREE.Vector2(size.width, size.height), strength, 0.6, 0.2);
    comp.addPass(bloomPass);
    return comp;
  }, [gl, scene, camera, size.width, size.height, strength]);

  useFrame(() => {
    composer.render();
  }, 1);

  return null;
}

type GraphVisualizerProps = {
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
  focusNodeId?: string | null;
  pulseNodeId?: string | null;
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
  focusNodeId,
  pulseNodeId,
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
    if (!visibleNodeIds) return nodes;
    return nodes.filter((n) => visibleNodeIds.has(n.id));
  }, [nodes, visibleNodeIds]);

  const visibleLinks = useMemo(() => {
    if (!visibleNodeIds) return links;
    return links.filter((l) => visibleNodeIds.has(l.source.id) && visibleNodeIds.has(l.target.id));
  }, [links, visibleNodeIds]);

  const visibleCommunities = useMemo(() => {
    if (!layout?.communities) return [];
    if (!visibleNodeIds) return layout.communities;
    return layout.communities.filter((community) =>
      community.entity_ids.some((id) => visibleNodeIds.has(id))
    );
  }, [layout?.communities, visibleNodeIds]);

  const focusNode = useMemo(() => {
    if (!focusNodeId) return null;
    return nodes.find((n) => n.id === focusNodeId) || null;
  }, [nodes, focusNodeId]);

  const { camera } = useThree();

  useEffect(() => {
    if (!focusNode) return;
    const controls = controlsRef.current;
    const target = new THREE.Vector3(focusNode.x, focusNode.y, focusNode.z);
    const currentTarget = controls?.target ? controls.target.clone() : new THREE.Vector3(0, 0, 0);
    const currentDistance = camera.position.distanceTo(currentTarget);
    const distance = Math.min(320, Math.max(80, currentDistance || 120));
    const direction = camera.position.clone().sub(currentTarget).normalize();
    const desiredPosition = target.clone().add(direction.multiplyScalar(distance));
    focusRef.current = { target, position: desiredPosition, active: true };
  }, [focusNode, camera]);

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

  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[100, 100, 100]} intensity={1.2} />
      <GalaxyBackground />

      <group>
        {onEmptyContextMenu && (
          <mesh
            position={[0, 0, 0]}
            rotation={[-Math.PI / 2, 0, 0]}
            onContextMenu={(event) => {
              event.stopPropagation();
              event.nativeEvent.preventDefault();
              onEmptyContextMenu({ x: event.point.x, y: event.point.y, z: event.point.z });
            }}
          >
            <planeGeometry args={[3000, 3000]} />
            <meshBasicMaterial transparent opacity={0} />
          </mesh>
        )}
        {showCommunities && visibleCommunities.map((c) => <CommunityBoundary key={c.id} community={c} />)}
        {visibleLinks.map((link) => {
          const isHighlighted =
            (selectedNode && (link.source.id === selectedNode.id || link.target.id === selectedNode.id)) ||
            (hoveredNode && (link.source.id === hoveredNode.id || link.target.id === hoveredNode.id));
          const isPulse =
            !!pulseNodeId && (link.source.id === pulseNodeId || link.target.id === pulseNodeId);
          return <Link key={link.id} link={link} isHighlighted={!!isHighlighted || isPulse} />;
        })}
        {visibleNodes.map((node) => (
          <Node
            key={node.id}
            node={node}
            isSelected={selectedNode?.id === node.id}
            isHighlighted={highlightedIds.has(node.id) || hoveredNode?.id === node.id}
            onClick={(n) => onNodeSelect(n)}
            onPointerOver={(n) => onNodeHover?.(n)}
            onPointerOut={() => onNodeHover?.(null)}
            showLabel={showLabels || selectedNode?.id === node.id || hoveredNode?.id === node.id}
          />
        ))}
      </group>

      <OrbitControls ref={controlsRef} enablePan enableZoom enableRotate />
      <Bloom strength={isMobile ? 0.4 : 0.9} />
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
