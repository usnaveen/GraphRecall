import { create } from 'zustand';
import type { FeedItem, ChatMessage, UserStats, TabType } from '../types';
import type { GraphData } from '../lib/graphData';
import type { GraphLayout } from '../lib/forceSimulation3d';
import { feedService, chatService, notesService, conceptsService, uploadsService } from '../services/api';

interface NoteItem {
  id: string;
  title: string;
  content_text: string;
  resource_type: string;
  created_at: string;
}

interface ConceptItem {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity_score: number;
}

interface UploadItem {
  id: string;
  upload_type: string;
  file_url: string;
  thumbnail_url?: string | null;
  title?: string | null;
  description?: string | null;
  created_at: string;
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
  error: string | null;

  // Chat State
  chatMessages: ChatMessage[];

  // User State
  userStats: UserStats;

  // Notes & Concepts lists
  notesList: NoteItem[];
  conceptsList: ConceptItem[];
  uploadsList: UploadItem[];

  // Feed Modes
  feedMode: 'daily' | 'history';
  quizHistory: FeedItem[];
  activeRecallSchedule: { date: string; count: number }[];
  setFeedMode: (mode: 'daily' | 'history') => void;
  fetchSchedule: () => Promise<void>;
  fetchQuizHistory: () => Promise<void>;

  // Graph cache (persist between tab switches)
  graphCache: {
    data: GraphData | null;
    layout: GraphLayout | null;
    loadedAt: number | null;
  };
  setGraphCache: (data: GraphData | null, layout: GraphLayout | null) => void;

  // Actions
  setActiveTab: (tab: TabType) => void;
  navigateToFeedWithTopic: (topic: string) => void;
  clearFeedTopicFilter: () => void;
  fetchFeed: (forceRefresh?: boolean) => Promise<void>;
  fetchStats: () => Promise<void>;
  fetchNotes: () => Promise<void>;
  fetchConcepts: (forceRefresh?: boolean) => Promise<void>;
  fetchUploads: () => Promise<void>;
  nextFeedItem: () => void;
  prevFeedItem: () => void;
  toggleLike: (itemId: string, itemType: string) => Promise<void>;
  toggleSave: (itemId: string, itemType: string) => Promise<void>;
  addChatMessage: (message: ChatMessage) => void;
  clearChatMessages: () => void;
  sendMessage: (text: string) => Promise<void>;
  resetFeed: () => void;
  startQuizForTopic: (topic: string) => Promise<void>;
  deleteNote: (id: string) => Promise<void>;
  deleteConcept: (id: string) => Promise<void>;
  deleteUpload: (id: string) => Promise<void>;
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
  error: null,
  chatMessages: [],
  notesList: [],
  conceptsList: [],
  uploadsList: [],
  graphCache: {
    data: null,
    layout: null,
    loadedAt: null,
  },
  userStats: {
    conceptsLearned: 0,
    notesAdded: 0,
    accuracy: 0,
    streakDays: 0
  },

  feedMode: 'history',
  quizHistory: [],
  activeRecallSchedule: [],

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

  setGraphCache: (data, layout) => {
    set({ graphCache: { data, layout, loadedAt: Date.now() } });
  },

  // Data Fetching Actions
  fetchFeed: async (forceRefresh = false) => {
    const state = get();
    // Prevent refetch if we already have items and not forcing refresh
    if (!forceRefresh && state.feedItems.length > 0) {
      return;
    }

    set({ isLoading: true, error: null });
    try {
      // Create a timeout promise
      const timeoutPromise = new Promise((_, reject) => {
        setTimeout(() => reject(new Error('Request timed out')), 30000);
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
              relatedConcept: concept_name,
              source_url: content.source_url
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
              thumbnailUrl: content.thumbnail_url,
              title: content.title,
              description: content.description,
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
        dailyItemLimit: data.daily_goal !== undefined ? data.daily_goal : (data.total_due_today + data.completed_today),
        isLoading: false,
        error: null
      });
    } catch (error: any) {
      console.error("Failed to fetch feed:", error);
      set({
        isLoading: false,
        error: `Feed Error: ${error.message || 'Unknown error'}`
      });
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

  fetchConcepts: async (forceRefresh = false) => {
    const state = get();
    // Cache check: don't refetch if we have data and aren't forcing a refresh
    if (!forceRefresh && state.conceptsList.length > 0) {
      return;
    }

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

  fetchUploads: async () => {
    try {
      const data = await uploadsService.listUploads();
      set({ uploadsList: data.uploads || [] });
    } catch (error) {
      console.error("Failed to fetch uploads:", error);
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
      const backendType = itemType === 'fillblank' ? 'fill_blank' : itemType === 'quiz' ? 'mcq' : itemType;
      if (!['flashcard', 'mcq', 'fill_blank', 'quiz'].includes(backendType)) {
        return;
      }
      const result = await feedService.likeItem(itemId, backendType);
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
      const backendType = itemType === 'fillblank' ? 'fill_blank' : itemType === 'quiz' ? 'mcq' : itemType;
      if (!['flashcard', 'mcq', 'fill_blank', 'quiz'].includes(backendType)) {
        return;
      }
      const result = await feedService.saveItem(itemId, backendType);
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

  startQuizForTopic: async (topic: string) => {
    set({ activeTab: 'feed', isLoading: true, feedTopicFilter: topic });
    try {
      const data = await feedService.getTopicQuiz(topic);

      const quizItems: FeedItem[] = data.questions.map((q: any, index: number) => ({
        id: `temp-quiz-${Date.now()}-${index}`,
        type: 'quiz',
        question: q.question,
        options: q.options.map((opt: string, i: number) => ({
          id: String.fromCharCode(65 + i), // A, B, C, D
          text: opt,
          isCorrect: opt === q.correct_answer
        })),
        explanation: q.explanation,
        relatedConcept: topic,
        source_url: data.source_url // if available from backend, though backend returns 'research_note_id' currently.
      }));

      set({
        feedItems: quizItems,
        currentFeedIndex: 0,
        isLoading: false
      });
    } catch (error) {
      console.error("Failed to start quiz:", error);
      set({ isLoading: false });
    }
  },

  deleteNote: async (id: string) => {
    const previousNotes = get().notesList;
    // Optimistic update
    set({ notesList: previousNotes.filter(n => n.id !== id) });
    try {
      await notesService.deleteNote(id);
      // Also refresh stats/concepts as they might have changed
      get().fetchStats();
      get().fetchConcepts(true);
    } catch (error) {
      console.error("Failed to delete note:", error);
      set({ notesList: previousNotes }); // Rollback
      throw error; // Re-throw so UI can show error
    }
  },

  deleteConcept: async (id: string) => {
    const previousConcepts = get().conceptsList;
    set({ conceptsList: previousConcepts.filter(c => c.id !== id) });
    try {
      await conceptsService.deleteConcept(id);
    } catch (error) {
      console.error("Failed to delete concept:", error);
      set({ conceptsList: previousConcepts }); // Rollback
    }
  },

  deleteUpload: async (id: string) => {
    const previousUploads = get().uploadsList;
    set({ uploadsList: previousUploads.filter(u => u.id !== id) });
    try {
      await uploadsService.deleteUpload(id);
    } catch (error) {
      console.error("Failed to delete upload:", error);
      set({ uploadsList: previousUploads });
    }
  },

  // Feed Mode & History
  setFeedMode: (mode: 'daily' | 'history') => set({ feedMode: mode }),

  fetchSchedule: async () => {
    try {
      const schedule = await feedService.getSchedule();
      set({ activeRecallSchedule: schedule });
    } catch (error) {
      console.error("Failed to fetch schedule:", error);
    }
  },

  fetchQuizHistory: async () => {
    try {
      const data = await feedService.getQuizHistory();
      // Transform to FeedItems
      const items: FeedItem[] = (data.quizzes || []).map((q: any) => ({
        id: q.id,
        type: 'quiz',
        question: q.question_text,
        options: (Array.isArray(q.options) ? q.options : []).map((opt: string, i: number) => ({
          id: String.fromCharCode(65 + i),
          text: opt,
          isCorrect: opt === q.correct_answer
        })),
        explanation: q.explanation,
        relatedConcept: q.topic,
        source_url: ''
      }));
      set({ quizHistory: items });
    } catch (error) {
      console.error("Failed to fetch quiz history:", error);
    }
  }
}));
