/**
 * Zustand store for GraphRecall state management
 * Updated for Instagram-style app with all features
 */

import { create } from 'zustand';
import {
  Concept,
  GraphData,
  Note,
  FeedItem,
  FeedResponse,
  ConceptReviewSession,
  ConceptReviewItem,
  ChatMessage,
  ChatResponse,
  Graph3DNode,
  Graph3DResponse,
  UserStats,
} from './api';
import type { ForceGraphNode, ForceGraphLink } from '@/components/graph/Visualizer3D';

export interface ForceGraphData {
  nodes: ForceGraphNode[];
  links: ForceGraphLink[];
}

// ============================================================================
// Navigation
// ============================================================================

export type AppTab = 'feed' | 'graph' | 'create' | 'chat' | 'profile';

// ============================================================================
// Store Interface
// ============================================================================

interface GraphRecallState {
  // Navigation
  activeTab: AppTab;
  setActiveTab: (tab: AppTab) => void;

  // Graph data (2D legacy)
  graphData: GraphData | null;
  setGraphData: (data: GraphData | null) => void;
  isGraphLoading: boolean;
  setGraphLoading: (loading: boolean) => void;
  graphError: string | null;
  setGraphError: (error: string | null) => void;

  // 3D Graph
  graph3DData: Graph3DResponse | null;
  setGraph3DData: (data: Graph3DResponse | null) => void;
  forceGraphData: ForceGraphData | null;
  setForceGraphData: (data: ForceGraphData | null) => void;
  focusedConcept: Graph3DNode | null;
  setFocusedConcept: (concept: Graph3DNode | null) => void;
  graphSearchQuery: string;
  setGraphSearchQuery: (query: string) => void;

  // Selected concept (for panel)
  selectedConcept: Concept | null;
  setSelectedConcept: (concept: Concept | null) => void;

  // Notes
  notes: Note[];
  setNotes: (notes: Note[]) => void;
  selectedNote: Note | null;
  setSelectedNote: (note: Note | null) => void;
  isNotesLoading: boolean;
  setNotesLoading: (loading: boolean) => void;

  // Feed
  feedData: FeedResponse | null;
  setFeedData: (data: FeedResponse | null) => void;
  currentFeedIndex: number;
  setCurrentFeedIndex: (index: number) => void;
  isFeedLoading: boolean;
  setFeedLoading: (loading: boolean) => void;
  feedFilters: {
    itemTypes?: string[];
    domains?: string[];
  };
  setFeedFilters: (filters: { itemTypes?: string[]; domains?: string[] }) => void;

  // Human-in-the-loop Review
  reviewSession: ConceptReviewSession | null;
  setReviewSession: (session: ConceptReviewSession | null) => void;
  isReviewLoading: boolean;
  setReviewLoading: (loading: boolean) => void;
  pendingReviewCount: number;
  setPendingReviewCount: (count: number) => void;

  // Ingestion state
  isIngesting: boolean;
  setIngesting: (ingesting: boolean) => void;
  ingestProgress: string | null;
  setIngestProgress: (progress: string | null) => void;

  // Chat
  chatMessages: ChatMessage[];
  addChatMessage: (message: ChatMessage) => void;
  clearChatMessages: () => void;
  isChatLoading: boolean;
  setChatLoading: (loading: boolean) => void;
  chatSuggestions: string[];
  setChatSuggestions: (suggestions: string[]) => void;

  // User stats
  userStats: UserStats | null;
  setUserStats: (stats: UserStats | null) => void;

  // UI state
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  showConceptPanel: boolean;
  setShowConceptPanel: (show: boolean) => void;

  // Helpers
  updateReviewConcept: (conceptId: string, updates: Partial<ConceptReviewItem>) => void;
  toggleReviewConceptSelection: (conceptId: string) => void;
}

// ============================================================================
// Store Implementation
// ============================================================================

export const useStore = create<GraphRecallState>((set, get) => ({
  // Navigation
  activeTab: 'feed',
  setActiveTab: (tab) => set({ activeTab: tab }),

  // Graph data (2D legacy)
  graphData: null,
  setGraphData: (data) => set({ graphData: data }),
  isGraphLoading: false,
  setGraphLoading: (loading) => set({ isGraphLoading: loading }),
  graphError: null,
  setGraphError: (error) => set({ graphError: error }),

  // 3D Graph
  graph3DData: null,
  setGraph3DData: (data) => set({ graph3DData: data }),
  forceGraphData: null,
  setForceGraphData: (data) => set({ forceGraphData: data }),
  focusedConcept: null,
  setFocusedConcept: (concept) => set({ focusedConcept: concept }),
  graphSearchQuery: '',
  setGraphSearchQuery: (query) => set({ graphSearchQuery: query }),

  // Selected concept
  selectedConcept: null,
  setSelectedConcept: (concept) => set({ selectedConcept: concept, showConceptPanel: !!concept }),

  // Notes
  notes: [],
  setNotes: (notes) => set({ notes }),
  selectedNote: null,
  setSelectedNote: (note) => set({ selectedNote: note }),
  isNotesLoading: false,
  setNotesLoading: (loading) => set({ isNotesLoading: loading }),

  // Feed
  feedData: null,
  setFeedData: (data) => set({ feedData: data }),
  currentFeedIndex: 0,
  setCurrentFeedIndex: (index) => set({ currentFeedIndex: index }),
  isFeedLoading: false,
  setFeedLoading: (loading) => set({ isFeedLoading: loading }),
  feedFilters: {},
  setFeedFilters: (filters) => set({ feedFilters: filters }),

  // Human-in-the-loop Review
  reviewSession: null,
  setReviewSession: (session) => set({ reviewSession: session }),
  isReviewLoading: false,
  setReviewLoading: (loading) => set({ isReviewLoading: loading }),
  pendingReviewCount: 0,
  setPendingReviewCount: (count) => set({ pendingReviewCount: count }),

  // Ingestion
  isIngesting: false,
  setIngesting: (ingesting) => set({ isIngesting: ingesting }),
  ingestProgress: null,
  setIngestProgress: (progress) => set({ ingestProgress: progress }),

  // Chat
  chatMessages: [],
  addChatMessage: (message) => set((state) => ({ 
    chatMessages: [...state.chatMessages, message] 
  })),
  clearChatMessages: () => set({ chatMessages: [] }),
  isChatLoading: false,
  setChatLoading: (loading) => set({ isChatLoading: loading }),
  chatSuggestions: [],
  setChatSuggestions: (suggestions) => set({ chatSuggestions: suggestions }),

  // User stats
  userStats: null,
  setUserStats: (stats) => set({ userStats: stats }),

  // UI state
  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  showConceptPanel: false,
  setShowConceptPanel: (show) => set({ showConceptPanel: show }),

  // Helpers
  updateReviewConcept: (conceptId, updates) => {
    const session = get().reviewSession;
    if (!session) return;
    
    set({
      reviewSession: {
        ...session,
        concepts: session.concepts.map((c) =>
          c.id === conceptId ? { ...c, ...updates, user_modified: true } : c
        ),
      },
    });
  },

  toggleReviewConceptSelection: (conceptId) => {
    const session = get().reviewSession;
    if (!session) return;
    
    set({
      reviewSession: {
        ...session,
        concepts: session.concepts.map((c) =>
          c.id === conceptId ? { ...c, is_selected: !c.is_selected, user_modified: true } : c
        ),
      },
    });
  },
}));
