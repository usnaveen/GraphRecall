/**
 * API client for GraphRecall backend
 * Updated to support all new endpoints
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ============================================================================
// Types
// ============================================================================

export interface Concept {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity_score: number;
  confidence?: number;
  related_concepts?: string[];
  prerequisites?: string[];
}

export interface GraphData {
  nodes: Concept[];
  edges: {
    source: string;
    target: string;
    type: string;
    properties?: Record<string, unknown>;
  }[];
  total_concepts: number;
  total_relationships: number;
}

export interface Note {
  id: string;
  user_id: string;
  content_type: string;
  content_text: string;
  source_url?: string;
  created_at: string;
  updated_at: string;
}

export interface IngestResponse {
  note_id: string;
  concepts_extracted: string[];
  concepts_created: number;
  relationships_created: number;
  status: string;
  processing_time_ms?: number;
}

export interface HealthStatus {
  status: string;
  postgres: { status: string; connected: boolean };
  neo4j: { status: string; connected: boolean };
  version: string;
}

// ============================================================================
// Human-in-the-Loop Types
// ============================================================================

export interface ConceptReviewItem {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity_score: number;
  confidence: number;
  related_concepts: string[];
  prerequisites: string[];
  is_selected: boolean;
  is_duplicate: boolean;
  matched_existing_id: string | null;
  user_modified: boolean;
}

export interface ConceptReviewSession {
  session_id: string;
  user_id: string;
  note_id: string;
  original_content: string;
  concepts: ConceptReviewItem[];
  conflicts: unknown[];
  status: string;
  created_at: string;
  expires_at: string;
}

export interface IngestWithReviewResponse {
  note_id: string;
  session_id: string | null;
  concepts_count: number;
  status: string;
  message: string;
}

// ============================================================================
// Feed Types
// ============================================================================

export type FeedItemType = 
  | 'flashcard' 
  | 'mcq' 
  | 'fill_blank' 
  | 'infographic' 
  | 'mermaid_diagram' 
  | 'screenshot' 
  | 'concept_showcase';

export type DifficultyLevel = 'again' | 'hard' | 'good' | 'easy';

export interface FeedItem {
  id: string;
  item_type: FeedItemType;
  content: Record<string, unknown>;
  concept_id?: string;
  concept_name?: string;
  domain?: string;
  due_date?: string;
  priority_score: number;
  created_at: string;
}

export interface FeedResponse {
  items: FeedItem[];
  total_due_today: number;
  completed_today: number;
  streak_days: number;
  domains: string[];
}

export interface UserStats {
  user_id: string;
  total_concepts: number;
  total_notes: number;
  total_reviews: number;
  streak_days: number;
  accuracy_rate: number;
  domain_progress: Record<string, number>;
  due_today: number;
  completed_today: number;
  overdue: number;
}

// ============================================================================
// Chat Types
// ============================================================================

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
}

export interface ChatResponse {
  response: string;
  sources: {
    type: string;
    id: string;
    title: string;
    preview: string;
  }[];
  related_concepts: {
    id: string;
    name: string;
    domain: string;
  }[];
  suggested_actions: string[];
}

// ============================================================================
// 3D Graph Types
// ============================================================================

export interface Graph3DNode {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity_score: number;
  mastery_level: number;
  x?: number;
  y?: number;
  z?: number;
  size: number;
  color: string;
}

export interface Graph3DEdge {
  id: string;
  source: string;
  target: string;
  relationship_type: string;
  strength: number;
}

export interface Graph3DResponse {
  nodes: Graph3DNode[];
  edges: Graph3DEdge[];
  clusters: {
    domain: string;
    color: string;
    count: number;
    concept_ids: string[];
  }[];
  total_nodes: number;
  total_edges: number;
}

// ============================================================================
// API Client
// ============================================================================

class ApiClient {
  private baseUrl: string;
  private userId: string = '00000000-0000-0000-0000-000000000001';

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`API Error (${response.status}): ${error}`);
    }

    return response.json();
  }

  // =========================================================================
  // Health
  // =========================================================================

  async getHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>('/health');
  }

  // =========================================================================
  // Notes (Legacy)
  // =========================================================================

  async getNotes(userId?: string): Promise<{ notes: Note[]; total: number }> {
    const params = `?user_id=${userId || this.userId}`;
    return this.request(`/api/notes${params}`);
  }

  async getNote(noteId: string): Promise<Note> {
    return this.request(`/api/notes/${noteId}`);
  }

  // Legacy ingest (auto-approve)
  async ingestNote(content: string, sourceUrl?: string): Promise<IngestResponse> {
    return this.request<IngestResponse>('/api/ingest', {
      method: 'POST',
      body: JSON.stringify({
        content,
        source_url: sourceUrl,
        user_id: this.userId,
      }),
    });
  }

  // =========================================================================
  // Human-in-the-Loop Review
  // =========================================================================

  async ingestWithReview(content: string, sourceUrl?: string): Promise<IngestWithReviewResponse> {
    return this.request<IngestWithReviewResponse>('/api/review/ingest', {
      method: 'POST',
      body: JSON.stringify({
        content,
        source_url: sourceUrl,
        user_id: this.userId,
        skip_review: false,
      }),
    });
  }

  async getReviewSession(sessionId: string): Promise<ConceptReviewSession> {
    return this.request<ConceptReviewSession>(`/api/review/sessions/${sessionId}`);
  }

  async getPendingReviewSessions(): Promise<{ sessions: { session_id: string; note_id: string; concepts_count: number; created_at: string }[]; total: number }> {
    return this.request(`/api/review/sessions?user_id=${this.userId}`);
  }

  async updateReviewSession(sessionId: string, concepts: ConceptReviewItem[]): Promise<void> {
    await this.request(`/api/review/sessions/${sessionId}`, {
      method: 'PUT',
      body: JSON.stringify(concepts),
    });
  }

  async approveReviewSession(
    sessionId: string,
    approvedConcepts: ConceptReviewItem[],
    removedIds: string[] = [],
    addedConcepts: ConceptReviewItem[] = []
  ): Promise<{ status: string; concepts_created: number; relationships_created: number }> {
    return this.request(`/api/review/sessions/${sessionId}/approve`, {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        approved_concepts: approvedConcepts,
        removed_concept_ids: removedIds,
        added_concepts: addedConcepts,
      }),
    });
  }

  async cancelReviewSession(sessionId: string): Promise<void> {
    await this.request(`/api/review/sessions/${sessionId}/cancel`, {
      method: 'POST',
    });
  }

  // =========================================================================
  // Knowledge Graph (Legacy 2D)
  // =========================================================================

  async getGraph(depth: number = 2): Promise<GraphData> {
    return this.request<GraphData>(`/api/graph?depth=${depth}`);
  }

  async getConcept(conceptId: string): Promise<{
    concept: Concept;
    related_notes: string[];
    proficiency_score?: number;
    last_reviewed?: string;
  }> {
    return this.request(`/api/graph/concept/${conceptId}`);
  }

  async searchConcepts(query: string): Promise<{ concepts: Concept[]; total: number }> {
    return this.request(`/api/graph/search?query=${encodeURIComponent(query)}`);
  }

  // =========================================================================
  // 3D Graph
  // =========================================================================

  async get3DGraph(options?: {
    centerConceptId?: string;
    domains?: string[];
    minMastery?: number;
    maxDepth?: number;
  }): Promise<Graph3DResponse> {
    const params = new URLSearchParams({ user_id: this.userId });
    
    if (options?.centerConceptId) params.set('center_concept_id', options.centerConceptId);
    if (options?.domains) params.set('domains', options.domains.join(','));
    if (options?.minMastery) params.set('min_mastery', options.minMastery.toString());
    if (options?.maxDepth) params.set('max_depth', options.maxDepth.toString());
    
    return this.request<Graph3DResponse>(`/api/graph3d?${params}`);
  }

  async focusOnConcept(conceptId: string, depth: number = 2): Promise<{
    center: Graph3DNode;
    connections: {
      concept: Graph3DNode;
      relationship: string;
      direction: string;
      strength: number;
    }[];
    prerequisite_path: { id: string; name: string }[];
    total_connections: number;
  }> {
    return this.request(`/api/graph3d/focus/${conceptId}?depth=${depth}&user_id=${this.userId}`);
  }

  async getGraphDomains(): Promise<{ domains: { domain: string; count: number; color: string }[] }> {
    return this.request('/api/graph3d/domains');
  }

  async searchGraph(query: string): Promise<{ results: { id: string; name: string; domain: string; color: string }[] }> {
    return this.request(`/api/graph3d/search?query=${encodeURIComponent(query)}`);
  }

  // =========================================================================
  // Feed
  // =========================================================================

  async getFeed(options?: {
    maxItems?: number;
    itemTypes?: FeedItemType[];
    domains?: string[];
  }): Promise<FeedResponse> {
    const params = new URLSearchParams({ user_id: this.userId });
    
    if (options?.maxItems) params.set('max_items', options.maxItems.toString());
    if (options?.itemTypes) params.set('item_types', options.itemTypes.join(','));
    if (options?.domains) params.set('domains', options.domains.join(','));
    
    return this.request<FeedResponse>(`/api/feed?${params}`);
  }

  async recordReview(
    itemId: string,
    itemType: string,
    difficulty: DifficultyLevel,
    responseTimeMs?: number
  ): Promise<{
    status: string;
    next_review: string;
    new_interval_days: number;
    easiness_factor: number;
    streak: number;
  }> {
    const params = new URLSearchParams({
      item_id: itemId,
      item_type: itemType,
      difficulty,
      user_id: this.userId,
    });
    
    if (responseTimeMs) params.set('response_time_ms', responseTimeMs.toString());
    
    return this.request(`/api/feed/review?${params}`, { method: 'POST' });
  }

  async getUserStats(): Promise<UserStats> {
    return this.request<UserStats>(`/api/feed/stats?user_id=${this.userId}`);
  }

  async getDueCount(): Promise<{ due_today: number; overdue: number; total: number }> {
    return this.request(`/api/feed/due-count?user_id=${this.userId}`);
  }

  // =========================================================================
  // Chat
  // =========================================================================

  async chat(message: string, history: ChatMessage[] = []): Promise<ChatResponse> {
    return this.request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        user_id: this.userId,
        message,
        conversation_history: history,
        include_sources: true,
      }),
    });
  }

  async quickChat(message: string): Promise<ChatResponse> {
    return this.request<ChatResponse>('/api/chat/quick', {
      method: 'POST',
      body: JSON.stringify({
        user_id: this.userId,
        message,
      }),
    });
  }

  async getChatSuggestions(): Promise<{ suggestions: string[] }> {
    return this.request(`/api/chat/suggestions?user_id=${this.userId}`);
  }

  // =========================================================================
  // Uploads
  // =========================================================================

  async createUpload(
    fileUrl: string,
    uploadType: 'screenshot' | 'infographic' = 'screenshot',
    title?: string,
    description?: string,
    linkedConcepts?: string[]
  ): Promise<{ id: string; file_url: string; status: string }> {
    const formData = new URLSearchParams();
    formData.set('user_id', this.userId);
    formData.set('upload_type', uploadType);
    formData.set('file_url', fileUrl);
    if (title) formData.set('title', title);
    if (description) formData.set('description', description);
    if (linkedConcepts) formData.set('linked_concepts', linkedConcepts.join(','));
    
    return this.request('/api/uploads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData.toString(),
    });
  }

  async getUploads(uploadType?: string): Promise<{ uploads: unknown[]; total: number }> {
    const params = new URLSearchParams({ user_id: this.userId });
    if (uploadType) params.set('upload_type', uploadType);
    
    return this.request(`/api/uploads?${params}`);
  }
}

export const api = new ApiClient();
export default api;
