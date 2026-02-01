export type TabType = 'feed' | 'graph' | 'create' | 'assistant' | 'profile';

export type CardType = 'flashcard' | 'quiz' | 'fillblank' | 'screenshot' | 'diagram';

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
}

export interface Flashcard {
  id: string;
  type: 'flashcard';
  concept: Concept;
}

export interface FillBlankCard {
  id: string;
  type: 'fillblank';
  sentence: string;
  answer: string;
  hint: string;
  relatedConcept: string;
}

export interface ScreenshotCard {
  id: string;
  type: 'screenshot';
  imageUrl: string;
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

export type FeedItem = Flashcard | QuizCard | FillBlankCard | ScreenshotCard | DiagramCard;

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
