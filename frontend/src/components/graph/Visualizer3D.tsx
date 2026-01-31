"use client";

import React, { useCallback, useRef } from 'react';
import dynamic from 'next/dynamic';
import { useStore } from '@/lib/store';
import { Graph3DNode } from '@/lib/api';
import SpriteText from 'three-spritetext';
import * as THREE from 'three';

// Dynamically import ForceGraph3D to avoid SSR issues
const ForceGraph3D = dynamic(() => import('react-force-graph-3d'), {
    ssr: false,
    loading: () => (
        <div className="flex items-center justify-center h-full text-slate-400">
            Loading 3D Engine...
        </div>
    )
});

export interface ForceGraphNode extends Graph3DNode {
    val?: number;
}

export interface ForceGraphLink {
    source: string;
    target: string;
    relationship_type?: string;
    strength?: number;
}

interface Visualizer3DProps {
    data: {
        nodes: ForceGraphNode[];
        links: ForceGraphLink[];
    };
}

// The library uses a loose node type internally; we cast in callbacks
type NodeObject = Record<string, any>;

export default function Visualizer3D({ data }: Visualizer3DProps) {
    // ForceGraph3D is dynamically imported, no exported ref type available
    const fgRef = useRef<any>(null);
    const { setSelectedConcept } = useStore();

    const handleNodeClick = useCallback((raw: NodeObject) => {
        const node = raw as ForceGraphNode;
        // Aim at node from outside it
        const distance = 40;
        const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);

        if (fgRef.current) {
            fgRef.current.cameraPosition(
                { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
                node,
                3000
            );
        }

        setSelectedConcept({
            id: node.id,
            name: node.name,
            definition: node.definition,
            domain: node.domain,
            complexity_score: node.complexity_score
        });
    }, [setSelectedConcept]);

    return (
        <div className="w-full h-full bg-[#0A0A0B]">
            <ForceGraph3D
                ref={fgRef}
                graphData={data}
                nodeLabel="name"
                nodeColor={(raw: NodeObject) => (raw as ForceGraphNode).color || "#8b5cf6"}
                nodeVal={(raw: NodeObject) => Math.pow(((raw as ForceGraphNode).complexity_score || 5), 1.5)}
                nodeResolution={32}
                nodeOpacity={0.9}
                linkWidth={(raw: Record<string, any>) => { const l = raw as ForceGraphLink; return l.strength ? l.strength * 1.5 : 1; }}
                linkColor={() => "rgba(255, 255, 255, 0.2)"}
                linkOpacity={0.3}
                backgroundColor="#0A0A0B"
                showNavInfo={false}
                onNodeClick={handleNodeClick}

                // Custom Node Object (Glowing spheres)
                nodeThreeObject={(raw: NodeObject) => {
                    const node = raw as ForceGraphNode;
                    const group = new THREE.Group();

                    // Sphere
                    const geometry = new THREE.SphereGeometry(Math.pow((node.complexity_score || 5), 0.8), 32, 32);
                    const material = new THREE.MeshPhongMaterial({
                        color: node.color || "#8b5cf6",
                        emissive: node.color || "#8b5cf6",
                        emissiveIntensity: 0.6,
                        shininess: 100
                    });
                    const sphere = new THREE.Mesh(geometry, material);
                    group.add(sphere);

                    // Label (Text Sprite)
                    const sprite = new SpriteText(node.name);
                    sprite.color = 'rgba(255, 255, 255, 0.9)';
                    sprite.textHeight = 4 + (node.mastery_level || 0) * 2;
                    sprite.position.set(0, 8, 0);
                    sprite.fontFace = "Space Grotesk";
                    group.add(sprite);

                    return group;
                }}

                // Particle effects on links for "active" flow
                linkDirectionalParticles={2}
                linkDirectionalParticleSpeed={0.005}
                linkDirectionalParticleWidth={1.5}
                linkDirectionalParticleColor={() => "#B6FF2E"}
            />
        </div>
    );
}
