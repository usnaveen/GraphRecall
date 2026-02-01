import { create } from 'zustand';
import type { FeedItem, ChatMessage, UserStats } from '../types';
import { mockFeedItems, mockChatMessages, mockUserStats } from '../data/mockData';

interface AppState {
  // Feed State
  feedItems: FeedItem[];
  currentFeedIndex: number;
  likedItems: Set<string>;
  savedItems: Set<string>;
  itemsReviewedToday: number;
  dailyItemLimit: number;
  
  // Chat State
  chatMessages: ChatMessage[];
  
  // User State
  userStats: UserStats;
  
  // Actions
  nextFeedItem: () => void;
  prevFeedItem: () => void;
  toggleLike: (itemId: string) => void;
  toggleSave: (itemId: string) => void;
  addChatMessage: (message: ChatMessage) => void;
  resetFeed: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // Initial State
  feedItems: mockFeedItems,
  currentFeedIndex: 0,
  likedItems: new Set(),
  savedItems: new Set(),
  itemsReviewedToday: 12,
  dailyItemLimit: 20,
  chatMessages: mockChatMessages,
  userStats: mockUserStats,

  // Actions
  nextFeedItem: () => {
    const state = get();
    if (state.currentFeedIndex < state.feedItems.length - 1) {
      set({ 
        currentFeedIndex: state.currentFeedIndex + 1,
        itemsReviewedToday: Math.min(state.itemsReviewedToday + 1, state.dailyItemLimit)
      });
    }
  },

  prevFeedItem: () => {
    const state = get();
    if (state.currentFeedIndex > 0) {
      set({ currentFeedIndex: state.currentFeedIndex - 1 });
    }
  },

  toggleLike: (itemId: string) => {
    const state = get();
    const newLiked = new Set(state.likedItems);
    if (newLiked.has(itemId)) {
      newLiked.delete(itemId);
    } else {
      newLiked.add(itemId);
    }
    set({ likedItems: newLiked });
  },

  toggleSave: (itemId: string) => {
    const state = get();
    const newSaved = new Set(state.savedItems);
    if (newSaved.has(itemId)) {
      newSaved.delete(itemId);
    } else {
      newSaved.add(itemId);
    }
    set({ savedItems: newSaved });
  },

  addChatMessage: (message: ChatMessage) => {
    set((state: AppState) => ({
      chatMessages: [...state.chatMessages, message],
    }));
  },

  resetFeed: () => {
    set({ currentFeedIndex: 0 });
  },
}));
