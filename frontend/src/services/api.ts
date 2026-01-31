/**
 * GraphRecall API Service Layer
 * Connects the Vite frontend to the FastAPI backend endpoints.
 */

// Use environment variable if available, otherwise default to local backend
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export const feedService = {
    /** Get the personalized active recall feed */
    getFeed: async (userId: string = "00000000-0000-0000-0000-000000000001") => {
        const response = await fetch(`${API_BASE}/feed?user_id=${userId}`);
        if (!response.ok) throw new Error('Failed to fetch feed');
        return response.json();
    },

    /** Record a review for a card */
    recordReview: async (itemId: string, itemType: string, difficulty: string) => {
        const response = await fetch(`${API_BASE}/feed/review?item_id=${itemId}&item_type=${itemType}&difficulty=${difficulty}`, {
            method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to record review');
        return response.json();
    },

    /** Get user statistics */
    getStats: async (userId: string = "00000000-0000-0000-0000-000000000001") => {
        const response = await fetch(`${API_BASE}/feed/stats?user_id=${userId}`);
        if (!response.ok) throw new Error('Failed to fetch stats');
        return response.json();
    },

    /** Toggle like status for a card */
    likeItem: async (itemId: string, itemType: string, userId: string = "00000000-0000-0000-0000-000000000001") => {
        const response = await fetch(`${API_BASE}/${itemId}/like?item_type=${itemType}&user_id=${userId}`, {
            method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to like item');
        return response.json();
    },

    /** Toggle save status for a card */
    saveItem: async (itemId: string, itemType: string, userId: string = "00000000-0000-0000-0000-000000000001") => {
        const response = await fetch(`${API_BASE}/${itemId}/save?item_type=${itemType}&user_id=${userId}`, {
            method: 'POST'
        });
        if (!response.ok) throw new Error('Failed to save item');
        return response.json();
    }
};

export const graphService = {
    /** Get 3D graph data */
    getGraph: async (userId: string = "00000000-0000-0000-0000-000000000001") => {
        const response = await fetch(`${API_BASE}/graph3d?user_id=${userId}`);
        if (!response.ok) throw new Error('Failed to fetch graph data');
        return response.json();
    },

    /** Get focused neighborhood around a concept */
    focusConcept: async (conceptId: string) => {
        const response = await fetch(`${API_BASE}/graph3d/focus/${conceptId}`);
        if (!response.ok) throw new Error('Failed to focus concept');
        return response.json();
    }
};

export const chatService = {
    /** Send message to GraphRAG chatbot */
    sendMessage: async (message: string, userId: string = "00000000-0000-0000-0000-000000000001") => {
        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, user_id: userId, conversation_history: [] })
        });
        if (!response.ok) throw new Error('Chat failed');
        return response.json();
    }
};

export const ingestService = {
    /** Start ingestion workflow */
    ingest: async (content: string, title?: string, skipReview: boolean = false) => {
        const response = await fetch(`${API_BASE}/v2/ingest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                content,
                title,
                user_id: "00000000-0000-0000-0000-000000000001",
                skip_review: skipReview
            })
        });
        if (!response.ok) throw new Error('Ingestion failed');
        return response.json();
    },

    /** Resume ingestion after user review */
    resume: async (threadId: string, approvedConcepts: any[], cancelled: boolean = false) => {
        const response = await fetch(`${API_BASE}/v2/ingest/resume`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thread_id: threadId,
                user_approved_concepts: approvedConcepts,
                user_cancelled: cancelled
            })
        });
        if (!response.ok) throw new Error('Resume ingestion failed');
        return response.json();
    }
};

/**
 * Generic API helper for direct endpoint access
 * Similar to axios for convenience
 */
export const api = {
    get: async (url: string) => {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`GET ${url} failed`);
        return { data: await response.json() };
    },

    post: async (url: string, data?: object) => {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: data ? JSON.stringify(data) : undefined,
        });
        if (!response.ok) throw new Error(`POST ${url} failed`);
        return { data: await response.json() };
    },

    delete: async (url: string) => {
        const response = await fetch(url, { method: 'DELETE' });
        if (!response.ok) throw new Error(`DELETE ${url} failed`);
        return { data: await response.json() };
    },
};

