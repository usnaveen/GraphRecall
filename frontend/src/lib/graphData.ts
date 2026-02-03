export interface Entity {
  id: string;
  title: string;
  type: string;
  description: string;
  frequency: number;
  degree: number;
  size?: number;
  color?: string;
  x?: number;
  y?: number;
  z?: number;
  domain?: string;
}

export interface Relationship {
  id: string;
  source: string;
  target: string;
  description: string;
  weight: number;
}

export interface Community {
  id: string;
  title: string;
  level: number;
  parent?: string;
  children: string[];
  entity_ids: string[];
  size: number;
  computedBounds?: {
    center: [number, number, number];
    size: [number, number, number];
    padding: number;
  };
  computedHierarchy?: {
    parentCommunities: Community[];
    childCommunities: Community[];
  };
  computedColor?: string;
  computedOpacity?: number;
}

export interface GraphData {
  entities: Entity[];
  relationships: Relationship[];
  communities: Community[];
}

export const ENTITY_COLORS: Record<string, string> = {
  concept: "#7de1ff",
  unnamed: "#9aa0a6",
};
