// @ts-nocheck
import * as d3 from "d3-force-3d";
import type { Entity, Community, GraphData } from "./graphData";
import { ENTITY_COLORS } from "./graphData";

export interface Node3D extends Entity {
  x: number;
  y: number;
  z: number;
  vx?: number;
  vy?: number;
  vz?: number;
  community?: Community;
  communityLevel: number;
  computedSize: number;
  computedColor: string;
}

export interface Link3D {
  id: string;
  source: Node3D;
  target: Node3D;
  weight: number;
  description: string;
}

export interface GraphLayout {
  nodes: Node3D[];
  links: Link3D[];
  communities: Community[];
}

export interface ForceConfig {
  chargeStrength: number;
  linkDistance: number;
  linkStrength: number;
  collisionRadius: number;
  communityStrength: number;
  centerStrength: number;
  spread3D: number;
  levelSpacing: number;
  sphericalConstraint: number;
}

export const defaultForceConfig: ForceConfig = {
  chargeStrength: -100,
  linkDistance: 30,
  linkStrength: 0.2,
  collisionRadius: 6,
  communityStrength: 0.2,
  centerStrength: 0.02,
  spread3D: 150,
  levelSpacing: 40,
  sphericalConstraint: 0.05,
};

export const calculateNodeSize = (degree: number, frequency: number) => {
  const size = Math.max(1.5, Math.min(10, 2 + degree * 0.4 + frequency * 0.2));
  return size * 0.4;
};

export const calculateLinkThickness = (weight: number) => {
  return Math.max(0.2, Math.min(2.5, weight * 0.15));
};

export class ForceSimulation3D {
  private simulation: d3.Simulation<Node3D, undefined>;
  private nodes: Node3D[] = [];
  private links: Link3D[] = [];
  private communities: Community[] = [];
  private config: ForceConfig;
  private communityCenters: Map<string, { x: number; y: number; z: number; radius: number }> =
    new Map();

  constructor(config: ForceConfig = defaultForceConfig) {
    this.config = { ...config };
    this.simulation = d3
      .forceSimulation<Node3D>()
      .force("link", d3.forceLink<Node3D, d3.SimulationLinkDatum<Node3D>>().id((d: unknown) => (d as { id: string }).id))
      .force("charge", d3.forceManyBody())
      .force("center", d3.forceCenter())
      .force("collision", d3.forceCollide())
      .alphaDecay(0.03)
      .alphaMin(0.001);
  }

  generateLayout(graphData: GraphData): Promise<GraphLayout> {
    return new Promise((resolve) => {
      this.preprocessData(graphData);
      this.setupForces();

      let iterationCount = 0;
      const maxIterations = 500;

      this.simulation.on("tick", () => {
        iterationCount++;
        if (iterationCount >= maxIterations || this.simulation.alpha() < 0.001) {
          this.simulation.stop();
          this.precomputeCommunityData();
          resolve({
            nodes: this.nodes,
            links: this.links,
            communities: this.communities,
          });
        }
      });

      this.simulation.nodes(this.nodes);
      const linkForce = this.simulation.force("link") as d3.ForceLink<Node3D, d3.SimulationLinkDatum<Node3D>>;
      linkForce.links(this.links);
      this.simulation.restart();
    });
  }

  private preprocessData(graphData: GraphData): void {
    this.communities = graphData.communities;

    const entityToCommunity = new Map<string, Community>();
    graphData.communities.forEach((community) => {
      community.entity_ids.forEach((entityId) => {
        entityToCommunity.set(entityId, community);
      });
    });

    const degrees = new Map<string, number>();
    graphData.relationships.forEach((rel) => {
      degrees.set(rel.source, (degrees.get(rel.source) || 0) + 1);
      degrees.set(rel.target, (degrees.get(rel.target) || 0) + 1);
    });

    this.nodes = graphData.entities.map((entity, index) => {
      const community = entityToCommunity.get(entity.id);
      const communityLevel = community ? community.level : 0;

      const abstractionScore = (degrees.get(entity.id) || entity.degree || 0) + (entity.frequency || 1) * 0.5;
      const maxAbstraction = Math.max(
        ...graphData.entities.map((e) => (degrees.get(e.id) || e.degree || 0) + (e.frequency || 1) * 0.5),
        1
      );
      const minAbstraction = Math.min(
        ...graphData.entities.map((e) => (degrees.get(e.id) || e.degree || 0) + (e.frequency || 1) * 0.5),
        0
      );

      const normalizedAbstraction =
        maxAbstraction > minAbstraction ? (abstractionScore - minAbstraction) / (maxAbstraction - minAbstraction) : 0.5;

      const minRadius = this.config.spread3D * 0.1;
      const maxRadius = this.config.spread3D;
      const radius = minRadius + (1 - normalizedAbstraction) * (maxRadius - minRadius);
      const communityOffset = communityLevel * this.config.levelSpacing * 0.3;
      const finalRadius = radius + communityOffset;

      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      const phi = Math.acos(1 - 2 * (index / Math.max(graphData.entities.length, 1)));
      const theta = goldenAngle * index;
      const randomFactor = 0.9 + Math.random() * 0.2;
      const adjustedRadius = finalRadius * randomFactor;

      const degree = degrees.get(entity.id) || entity.degree || 0;
      const frequency = entity.frequency || 1;

      return {
        ...entity,
        degree,
        frequency,
        x: entity.x ?? adjustedRadius * Math.sin(phi) * Math.cos(theta),
        y: entity.y ?? adjustedRadius * Math.sin(phi) * Math.sin(theta),
        z: entity.z ?? adjustedRadius * Math.cos(phi),
        community,
        communityLevel,
        computedSize: entity.size ?? calculateNodeSize(degree, frequency),
        computedColor:
          community?.computedColor ||
          entity.color ||
          ENTITY_COLORS[entity.type] ||
          ENTITY_COLORS.unnamed,
      } as Node3D;
    });

    const nodeMap = new Map<string, Node3D>();
    this.nodes.forEach((node) => {
      nodeMap.set(node.id, node);
      nodeMap.set(node.title, node);
    });

    this.links = graphData.relationships
      .map((rel) => {
        const sourceNode = nodeMap.get(rel.source);
        const targetNode = nodeMap.get(rel.target);
        if (!sourceNode || !targetNode) return null;
        return {
          id: rel.id,
          source: sourceNode,
          target: targetNode,
          weight: rel.weight,
          description: rel.description,
        };
      })
      .filter((link): link is Link3D => link !== null);
  }

  private setupForces(): void {
    const nodeChargeStrength = (d: Node3D) => {
      return this.config.chargeStrength - d.degree * 5;
    };

    const linkDistance = (d: Link3D) => {
      const weightFactor = 1 / (d.weight * 0.05 + 1);
      return this.config.linkDistance * weightFactor;
    };

    const linkStrength = (d: Link3D) => {
      return this.config.linkStrength * (d.weight * 0.3 + 0.7);
    };

    const collisionRadius = (d: Node3D) => {
      return this.config.collisionRadius + d.computedSize * 0.8;
    };

    const centerStrength = this.config.centerStrength;
    const communityStrength = this.config.communityStrength;

    this.simulation
      .force("charge", d3.forceManyBody().strength(nodeChargeStrength))
      .force("link", d3.forceLink<Node3D, d3.SimulationLinkDatum<Node3D>>().id((d: unknown) => (d as { id: string }).id).distance(linkDistance).strength(linkStrength))
      .force("collision", d3.forceCollide<Node3D>().radius(collisionRadius).iterations(2))
      .force("center", d3.forceCenter(0, 0, 0).strength(centerStrength))
      .force("community", () => {
        this.nodes.forEach((node) => {
          if (!node.community) return;
          const communityId = node.community.id;
          const center = this.communityCenters.get(communityId) || { x: 0, y: 0, z: 0, radius: 0 };
          node.vx = (node.vx || 0) + (center.x - node.x) * communityStrength * 0.01;
          node.vy = (node.vy || 0) + (center.y - node.y) * communityStrength * 0.01;
          node.vz = (node.vz || 0) + (center.z - node.z) * communityStrength * 0.01;
        });
      });
  }

  private precomputeCommunityData(): void {
    const communities = this.communities;
    const communityMap = new Map<string, Node3D[]>();
    communities.forEach((community) => {
      communityMap.set(community.id, []);
    });
    this.nodes.forEach((node) => {
      if (node.community) {
        const list = communityMap.get(node.community.id);
        if (list) list.push(node);
      }
    });

    communities.forEach((community) => {
      const nodes = communityMap.get(community.id) || [];
      if (nodes.length === 0) return;

      const xs = nodes.map((n) => n.x);
      const ys = nodes.map((n) => n.y);
      const zs = nodes.map((n) => n.z);
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      const minZ = Math.min(...zs);
      const maxZ = Math.max(...zs);

      const padding = 6 + Math.min(20, nodes.length * 0.15);
      const center: [number, number, number] = [(minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2];
      const size: [number, number, number] = [maxX - minX + padding, maxY - minY + padding, maxZ - minZ + padding];

      community.computedBounds = { center, size, padding };
      community.computedOpacity = Math.min(0.2, 0.08 + nodes.length / 500);
      this.communityCenters.set(community.id, { x: center[0], y: center[1], z: center[2], radius: Math.max(...size) });
    });

    communities.forEach((community) => {
      const parents = communities.filter((c) => community.parent && c.id === community.parent);
      const children = communities.filter((c) => c.parent === community.id);
      community.computedHierarchy = { parentCommunities: parents, childCommunities: children };
    });
  }
}
