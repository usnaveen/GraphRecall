/**
 * GraphRecall API Service Layer
 * Connects the Vite frontend to the FastAPI backend endpoints.
 * All requests include the Bearer token for authentication.
 */

import { getAuthToken } from '../store/useAuthStore';

// Use environment variable if available, otherwise default to local backend
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

/**
 * Helper to build headers with authentication
 */
const getHeaders = (includeContentType: boolean = false): HeadersInit => {
    const token = getAuthToken();
    const headers: HeadersInit = {};

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    if (includeContentType) {
        headers['Content-Type'] = 'application/json';
    }

    return headers;
};

/**
 * Generic fetch wrapper with auth.
 * Automatically logs the user out on 401 (expired Google ID token).
 */
const authFetch = async (url: string, options: RequestInit = {}): Promise<Response> => {
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
    const response = await fetch(url, {
        ...options,
        headers: {
            ...getHeaders((options.method === 'POST' || options.method === 'PUT') && !isFormData),
            ...options.headers,
        },
    });

    // Handle 401 Unauthorized — token expired, force re-login
    if (response.status === 401) {
        console.warn('Unauthorized - token expired, logging out');
        // Dynamic import to avoid circular dependency
        const { useAuthStore } = await import('../store/useAuthStore');
        useAuthStore.getState().logout();
    }

    return response;
};

export const feedService = {
    /** Get the personalized active recall feed */
    getFeed: async () => {
        const response = await authFetch(`${API_BASE}/feed`);
        if (!response.ok) throw new Error('Failed to fetch feed');
        return response.json();
    },

    /** Record a review for a card */
    recordReview: async (itemId: string, itemType: string, difficulty: string) => {
        const response = await authFetch(
            `${API_BASE}/feed/review?item_id=${itemId}&item_type=${itemType}&difficulty=${difficulty}`,
            { method: 'POST' }
        );
        if (!response.ok) throw new Error('Failed to record review');
        return response.json();
    },

    /** Get user statistics */
    getStats: async () => {
        const response = await authFetch(`${API_BASE}/feed/stats`);
        if (!response.ok) throw new Error('Failed to fetch stats');
        return response.json();
    },

    /** Toggle like status for a card */
    likeItem: async (itemId: string, itemType: string) => {
        const response = await authFetch(
            `${API_BASE}/feed/${itemId}/like?item_type=${itemType}`,
            { method: 'POST' }
        );
        if (!response.ok) throw new Error('Failed to like item');
        return response.json();
    },

    /** Toggle save status for a card */
    saveItem: async (itemId: string, itemType: string) => {
        const response = await authFetch(
            `${API_BASE}/feed/${itemId}/save?item_type=${itemType}`,
            { method: 'POST' }
        );
        if (!response.ok) throw new Error('Failed to save item');
        return response.json();
    },

    /** Generate a quiz for a specific topic */
    getTopicQuiz: async (topic: string) => {
        const response = await authFetch(
            `${API_BASE}/feed/quiz/topic/${encodeURIComponent(topic)}`,
            {
                method: 'POST',
                body: JSON.stringify({ num_questions: 5, force_research: false })
            }
        );
        if (!response.ok) throw new Error('Failed to generate quiz');
        return response.json();
    }
};

export const graphService = {
    /** Get 3D graph data */
    getGraph: async () => {
        const response = await authFetch(`${API_BASE}/graph3d`);
        if (!response.ok) throw new Error('Failed to fetch graph data');
        return response.json();
    },

    /** Get focused neighborhood around a concept */
    focusConcept: async (conceptId: string) => {
        const response = await authFetch(`${API_BASE}/graph3d/focus/${conceptId}`);
        if (!response.ok) throw new Error('Failed to focus concept');
        return response.json();
    }
};

export const chatService = {
    /** Send message to GraphRAG chatbot */
    sendMessage: async (message: string) => {
        const response = await authFetch(`${API_BASE}/chat`, {
            method: 'POST',
            body: JSON.stringify({ message, conversation_history: [] })
        });
        if (!response.ok) throw new Error('Chat failed');
        return response.json();
    }
};

export const notesService = {
    /** Get list of user's notes */
    listNotes: async (limit: number = 50, offset: number = 0) => {
        const response = await authFetch(`${API_BASE}/notes?limit=${limit}&offset=${offset}`);
        if (!response.ok) throw new Error('Failed to fetch notes');
        return response.json();
    },

    deleteNote: async (noteId: string) => {
        const response = await authFetch(`${API_BASE}/notes/${noteId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete note');
        return response.json();
    }
};

export const conceptsService = {
    /** Get list of user's concepts (via graph3d endpoint) */
    listConcepts: async () => {
        const response = await authFetch(`${API_BASE}/graph3d`);
        if (!response.ok) throw new Error('Failed to fetch concepts');
        return response.json();
    },

    deleteConcept: async (conceptId: string) => {
        const response = await authFetch(`${API_BASE}/concepts/${conceptId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete concept');
        return response.json();
    }
};

export const authService = {
    updateProfile: async (settings: any) => {
        const response = await authFetch(`${API_BASE}/auth/profile`, {
            method: 'PATCH',
            body: JSON.stringify({ settings })
        });
        if (!response.ok) throw new Error('Failed to update profile');
        return response.json();
    }
};

export const ingestService = {
    /** Start ingestion workflow */
    ingest: async (content: string, title?: string, skipReview: boolean = false) => {
        const response = await authFetch(`${API_BASE}/v2/ingest`, {
            method: 'POST',
            body: JSON.stringify({
                content,
                title,
                skip_review: skipReview
            })
        });
        if (!response.ok) throw new Error('Ingestion failed');
        return response.json();
    },

    /** Ingest content from a URL */
    ingestUrl: async (url: string) => {
        const response = await authFetch(`${API_BASE}/v2/ingest/url`, {
            method: 'POST',
            body: JSON.stringify({ url })
        });
        if (!response.ok) throw new Error('URL Ingestion failed');
        return response.json();
    },

    /** Resume ingestion after user review */
    resume: async (threadId: string, approvedConcepts: any[], cancelled: boolean = false) => {
        const response = await authFetch(`${API_BASE}/v2/ingest/${threadId}/approve`, {
            method: 'POST',
            body: JSON.stringify({
                approved_concepts: approvedConcepts,
                cancelled: cancelled
            })
        });
        if (!response.ok) throw new Error('Resume ingestion failed');
        return response.json();
    },

    /** Store a YouTube link (no processing) */
    ingestYoutube: async (url: string, title?: string) => {
        const response = await authFetch(`${API_BASE}/v2/ingest/youtube`, {
            method: 'POST',
            body: JSON.stringify({ url, title })
        });
        if (!response.ok) throw new Error('YouTube link storage failed');
        return response.json();
    },

    /** Ingest an LLM chat transcript */
    ingestChatTranscript: async (content: string, title?: string) => {
        const response = await authFetch(`${API_BASE}/v2/ingest/chat-transcript`, {
            method: 'POST',
            body: JSON.stringify({ content, title })
        });
        if (!response.ok) throw new Error('Chat transcript ingestion failed');
        return response.json();
    },
};

export const uploadsService = {
    /** Upload a screenshot/infographic file */
    createUpload: async (
        file: File,
        uploadType: 'screenshot' | 'infographic' | 'diagram' = 'screenshot',
        title?: string,
        description?: string,
        linkedConcepts?: string[]
    ) => {
        const formData = new FormData();
        formData.append('upload_type', uploadType);
        if (title) formData.append('title', title);
        if (description) formData.append('description', description);
        if (linkedConcepts && linkedConcepts.length > 0) {
            formData.append('linked_concepts', linkedConcepts.join(','));
        }
        formData.append('file', file);

        const response = await authFetch(`${API_BASE}/uploads`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) throw new Error('Upload failed');
        return response.json();
    },

    /** List uploads */
    listUploads: async (limit: number = 20, offset: number = 0) => {
        const response = await authFetch(`${API_BASE}/uploads?limit=${limit}&offset=${offset}`);
        if (!response.ok) throw new Error('Failed to fetch uploads');
        return response.json();
    },

    /** Delete an upload */
    deleteUpload: async (uploadId: string) => {
        const response = await authFetch(`${API_BASE}/uploads/${uploadId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete upload');
        return response.json();
    }
};

/**
 * Generic API helper for direct endpoint access
 */
export const api = {
    get: async (path: string) => {
        const url = `${API_BASE}${path}`;
        const response = await authFetch(url);
        if (!response.ok) throw new Error(`GET ${path} failed`);
        return { data: await response.json() };
    },

    post: async (path: string, data?: object) => {
        const url = `${API_BASE}${path}`;
        const response = await authFetch(url, {
            method: 'POST',
            body: data ? JSON.stringify(data) : undefined,
        });
        if (!response.ok) throw new Error(`POST ${path} failed`);
        return { data: await response.json() };
    },

    delete: async (path: string) => {
        const url = `${API_BASE}${path}`;
        const response = await authFetch(url, { method: 'DELETE' });
        if (!response.ok) throw new Error(`DELETE ${path} failed`);
        return { data: await response.json() };
    },

    graph: {
        getGraph: async () => {
            const response = await authFetch(`${API_BASE}/graph3d`);
            if (!response.ok) throw new Error('Failed to fetch graph data');
            return response.json();
        },
        getFocus: async (conceptId: string) => {
            const response = await authFetch(`${API_BASE}/graph3d/focus/${encodeURIComponent(conceptId)}`);
            if (!response.ok) throw new Error('Failed to fetch concept focus');
            return response.json();
        }
    }
};

export const nodesService = {
    createNode: async (name: string, description?: string, position?: { x: number; y: number; z: number }) => {
        const response = await authFetch(`${API_BASE}/nodes`, {
            method: 'POST',
            body: JSON.stringify({ name, description, position }),
        });
        if (!response.ok) throw new Error('Failed to create node');
        return response.json();
    },
    suggestLinks: async (nodeId: string) => {
        const response = await authFetch(`${API_BASE}/nodes/${encodeURIComponent(nodeId)}/suggest-links`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error('Failed to suggest links');
        return response.json();
    },
    applyLinks: async (nodeId: string, links: { target_id: string; relationship_type: string; strength?: number }[]) => {
        const response = await authFetch(`${API_BASE}/nodes/${encodeURIComponent(nodeId)}/link`, {
            method: 'POST',
            body: JSON.stringify({ links }),
        });
        if (!response.ok) throw new Error('Failed to apply links');
        return response.json();
    }
};
