export type TabType = 'feed' | 'graph' | 'create' | 'assistant' | 'profile';

export type CardType = 'term_card' | 'quiz' | 'fillblank' | 'screenshot' | 'diagram' | 'concept_showcase' | 'code_challenge';

export interface Concept {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity: number;
  prerequisites: string[];
  related: string[];
  mastery: number;
  lastReviewed?: Date;
  parent_topic?: string;
  subtopics?: string[];
}

export interface QuizOption {
  id: string;
  text: string;
  isCorrect: boolean;
}

export interface QuizCard {
  id: string;
  type: 'quiz';
  question: string;
  options: QuizOption[];
  explanation: string;
  relatedConcept: string;
  source_url?: string;
}

export interface TermCard {
  id: string;
  type: 'term_card' | 'flashcard';
  concept: Concept;
  source_url?: string;
}

export interface FillBlankCard {
  id: string;
  type: 'fillblank';
  sentence: string;
  answer: string;
  hint: string;
  relatedConcept: string;
}

export interface CodeCard {
  id: string;
  type: 'code_challenge';
  language: string;
  instruction: string;
  initialCode?: string;
  solutionCode: string;
  explanation: string;
  relatedConcept?: string;
}

export interface ScreenshotCard {
  id: string;
  type: 'screenshot';
  imageUrl: string;
  thumbnailUrl?: string;
  title?: string;
  description?: string;
  linkedConcepts: string[];
  addedAt: Date;
}

export interface DiagramCard {
  id: string;
  type: 'diagram';
  mermaidCode: string;
  caption: string;
  sourceNote: string;
}

export interface ConceptShowcaseCard {
  id: string;
  type: 'concept_showcase';
  conceptName: string;
  definition: string;
  domain: string;
  complexityScore: number;
  tagline: string;
  visualMetaphor: string;
  keyPoints: string[];
  realWorldExample: string;
  connectionsNote: string;
  emojiIcon: string;
  prerequisites: string[];
  relatedConcepts: string[];
}

export type FeedItem = TermCard | QuizCard | FillBlankCard | ScreenshotCard | DiagramCard | ConceptShowcaseCard | CodeCard;

export interface DailyActivity {
  date: string;
  reviews_completed: number;
  concepts_learned: number;
  accuracy: number;
}

export interface UserStats {
  conceptsLearned: number;
  notesAdded: number;
  accuracy: number;
  streakDays: number;

  // Enriched data
  domainProgress?: Record<string, number>; // Domain -> percentage
  dailyActivity?: DailyActivity[];
}

export interface DomainProgress {
  name: string;
  progress: number;
  color: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  status?: string; // e.g. "Thinking...", "Searching..."
  sources?: string[];
  relatedConcepts?: string[];
  serverId?: string;
  /** Raw source objects from the backend, used for source-scoped chat filtering */
  sourceObjects?: { id: string; title: string; content?: string }[];
  /** Metadata about the retrieval process */
  metadata?: {
    intent?: string;
    entities?: string[];
    documents_retrieved?: number;
    nodes_retrieved?: number;
  };
}

export interface GraphNode {
  id: string;
  name: string;
  x: number;
  y: number;
  z: number;
  size: number;
  color: string;
  mastery: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  strength: number;
}
