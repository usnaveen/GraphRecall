import { create } from 'zustand';
import type { FeedItem, ChatMessage, UserStats, TabType } from '../types';
import { feedService, chatService, notesService, conceptsService } from '../services/api';

interface NoteItem {
  id: string;
  title: string;
  content_text: string;
  source_type: string;
  created_at: string;
}

interface ConceptItem {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity_score: number;
}

interface AppState {
  // Navigation State
  activeTab: TabType;
  feedTopicFilter: string | null;

  // Feed State
  feedItems: FeedItem[];
  currentFeedIndex: number;
  likedItems: Set<string>;
  savedItems: Set<string>;
  itemsReviewedToday: number;
  dailyItemLimit: number;
  isLoading: boolean;

  // Chat State
  chatMessages: ChatMessage[];

  // User State
  userStats: UserStats;

  // Notes & Concepts lists
  notesList: NoteItem[];
  conceptsList: ConceptItem[];

  // Actions
  setActiveTab: (tab: TabType) => void;
  navigateToFeedWithTopic: (topic: string) => void;
  clearFeedTopicFilter: () => void;
  fetchFeed: () => Promise<void>;
  fetchStats: () => Promise<void>;
  fetchNotes: () => Promise<void>;
  fetchConcepts: () => Promise<void>;
  nextFeedItem: () => void;
  prevFeedItem: () => void;
  toggleLike: (itemId: string, itemType: string) => Promise<void>;
  toggleSave: (itemId: string, itemType: string) => Promise<void>;
  addChatMessage: (message: ChatMessage) => void;
  clearChatMessages: () => void;
  sendMessage: (text: string) => Promise<void>;
  resetFeed: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // Initial State
  activeTab: 'feed',
  feedTopicFilter: null,
  feedItems: [],
  currentFeedIndex: 0,
  likedItems: new Set(),
  savedItems: new Set(),
  itemsReviewedToday: 0,
  dailyItemLimit: 20,
  isLoading: false,
  chatMessages: [],
  notesList: [],
  conceptsList: [],
  userStats: {
    conceptsLearned: 0,
    notesAdded: 0,
    accuracy: 0,
    streakDays: 0
  },

  // Navigation Actions
  setActiveTab: (tab: TabType) => {
    set({ activeTab: tab });
  },

  navigateToFeedWithTopic: (topic: string) => {
    set({ activeTab: 'feed', feedTopicFilter: topic, currentFeedIndex: 0 });
  },

  clearFeedTopicFilter: () => {
    set({ feedTopicFilter: null });
  },

  // Data Fetching Actions
  fetchFeed: async () => {
    set({ isLoading: true });
    try {
      // Create a timeout promise
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Request timed out')), 10000);
      });

      // Race against the actual fetch
      const data: any = await Promise.race([
        feedService.getFeed(),
        timeoutPromise
      ]);

      // Transform backend items to frontend types
      const transformedItems: FeedItem[] = data.items.map((item: any) => {
        const { item_type, content, concept_id, concept_name, domain } = item;

        switch (item_type) {
          case 'flashcard':
            return {
              id: item.id,
              type: 'flashcard',
              concept: {
                id: concept_id,
                name: concept_name,
                definition: content.back || content.definition || 'No definition',
                domain: domain || 'General',
                complexity: content.complexity || 5,
                prerequisites: content.prerequisites || [],
                related: content.related_concepts || [],
                mastery: content.mastery || 0
              }
            };
          case 'mcq':
            return {
              id: item.id,
              type: 'quiz',
              question: content.question,
              options: content.options.map((o: any) => ({
                id: o.id,
                text: o.text,
                isCorrect: o.is_correct
              })),
              explanation: content.explanation,
              relatedConcept: concept_name
            };
          case 'fill_blank':
            return {
              id: item.id,
              type: 'fillblank',
              sentence: content.sentence,
              answer: content.answers ? content.answers[0] : '',
              hint: content.hint,
              relatedConcept: concept_name
            };
          case 'screenshot':
          case 'infographic':
          case 'user_upload':
            return {
              id: item.id,
              type: 'screenshot',
              imageUrl: content.file_url,
              linkedConcepts: content.linked_concepts || [],
              addedAt: new Date(item.created_at)
            };
          case 'mermaid_diagram':
            return {
              id: item.id,
              type: 'diagram',
              mermaidCode: content.mermaid_code,
              caption: content.title,
              sourceNote: content.source_note_id || 'Note'
            };
          case 'concept_showcase':
            return {
              id: item.id,
              type: 'concept_showcase',
              conceptName: content.concept_name || concept_name || 'Concept',
              definition: content.definition || 'No definition available',
              domain: content.domain || domain || 'General',
              complexityScore: content.complexity_score || 5,
              tagline: content.tagline || '',
              visualMetaphor: content.visual_metaphor || '',
              keyPoints: content.key_points || [],
              realWorldExample: content.real_world_example || '',
              connectionsNote: content.connections_note || '',
              emojiIcon: content.emoji_icon || '📚',
              prerequisites: content.prerequisites || [],
              relatedConcepts: content.related_concepts || [],
            };
          default:
            return {
              id: item.id,
              type: 'flashcard',
              concept: {
                id: concept_id,
                name: concept_name,
                definition: content.definition || 'No description available',
                domain: domain || 'General',
                complexity: 5,
                prerequisites: [],
                related: [],
                mastery: 0
              }
            };
        }
      });

      set({
        feedItems: transformedItems,
        itemsReviewedToday: data.completed_today,
        dailyItemLimit: data.total_due_today + data.completed_today,
        isLoading: false
      });
    } catch (error) {
      console.error("Failed to fetch feed:", error);
      // Ensure we stop loading even on error
      set({ isLoading: false });
    }
  },

  fetchStats: async () => {
    try {
      const data = await feedService.getStats();
      set({
        userStats: {
          conceptsLearned: data.total_concepts,
          notesAdded: data.total_notes,
          accuracy: data.accuracy_rate * 100,
          streakDays: data.streak_days,
          domainProgress: data.domain_progress,
          dailyActivity: data.daily_activity
        }
      });
    } catch (error) {
      console.error("Failed to fetch stats:", error);
    }
  },

  fetchNotes: async () => {
    try {
      const data = await notesService.listNotes();
      set({ notesList: data.notes || [] });
    } catch (error) {
      console.error("Failed to fetch notes:", error);
    }
  },

  fetchConcepts: async () => {
    try {
      const data = await conceptsService.listConcepts();
      // The graph3d endpoint returns nodes array
      const concepts = (data.nodes || []).map((node: any) => ({
        id: node.id,
        name: node.name || node.label,
        definition: node.definition || '',
        domain: node.domain || 'General',
        complexity_score: node.complexity_score || node.size || 5,
      }));
      set({ conceptsList: concepts });
    } catch (error) {
      console.error("Failed to fetch concepts:", error);
    }
  },

  nextFeedItem: () => {
    const state = get();
    if (state.currentFeedIndex < state.feedItems.length - 1) {
      set({
        currentFeedIndex: state.currentFeedIndex + 1,
        itemsReviewedToday: state.itemsReviewedToday + 1
      });
    }
  },

  prevFeedItem: () => {
    const state = get();
    if (state.currentFeedIndex > 0) {
      set({ currentFeedIndex: state.currentFeedIndex - 1 });
    }
  },

  toggleLike: async (itemId: string, itemType: string) => {
    const state = get();
    try {
      const result = await feedService.likeItem(itemId, itemType); // Need to add to api.ts
      const newLiked = new Set(state.likedItems);
      if (result.is_liked) {
        newLiked.add(itemId);
      } else {
        newLiked.delete(itemId);
      }
      set({ likedItems: newLiked });
    } catch (error) {
      console.error("Failed to toggle like:", error);
    }
  },

  toggleSave: async (itemId: string, itemType: string) => {
    const state = get();
    try {
      const result = await feedService.saveItem(itemId, itemType); // Need to add to api.ts
      const newSaved = new Set(state.savedItems);
      if (result.is_saved) {
        newSaved.add(itemId);
      } else {
        newSaved.delete(itemId);
      }
      set({ savedItems: newSaved });
    } catch (error) {
      console.error("Failed to toggle save:", error);
    }
  },

  addChatMessage: (message: ChatMessage) => {
    set((state: AppState) => {
      const existingIndex = state.chatMessages.findIndex((m: ChatMessage) => m.id === message.id);
      if (existingIndex > -1) {
        const newMessages = [...state.chatMessages];
        newMessages[existingIndex] = message;
        return { chatMessages: newMessages };
      }
      return { chatMessages: [...state.chatMessages, message] };
    });
  },

  clearChatMessages: () => {
    set({ chatMessages: [] });
  },

  sendMessage: async (text: string) => {
    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', content: text };
    get().addChatMessage(userMsg);

    try {
      const response = await chatService.sendMessage(text);
      const assistantMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: response.response,
        sources: response.sources.map((s: any) => s.title || s.name),
        relatedConcepts: response.related_concepts.map((c: any) => c.name)
      };
      get().addChatMessage(assistantMsg);
    } catch (error) {
      console.error("Chat failed:", error);
    }
  },

  resetFeed: () => {
    set({ currentFeedIndex: 0 });
  },
}));
