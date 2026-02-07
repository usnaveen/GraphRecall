import type { FeedItem, Concept, UserStats, DomainProgress, ChatMessage, GraphNode, GraphEdge } from '../types';

export const mockConcepts: Concept[] = [
  {
    id: '1',
    name: 'Neural Networks',
    definition: 'A computing system inspired by biological neural networks that can learn from observational data.',
    domain: 'Machine Learning',
    complexity: 7,
    prerequisites: ['Linear Algebra', 'Gradient Descent', 'Backpropagation'],
    related: ['CNN', 'RNN', 'Deep Learning'],
    mastery: 65,
    lastReviewed: new Date('2026-01-28'),
  },
  {
    id: '2',
    name: 'Backpropagation',
    definition: 'An algorithm for calculating gradients by propagating errors backwards through network layers.',
    domain: 'Machine Learning',
    complexity: 8,
    prerequisites: ['Calculus', 'Chain Rule'],
    related: ['Neural Networks', 'Gradient Descent', 'Optimization'],
    mastery: 70,
    lastReviewed: new Date('2026-01-27'),
  },
  {
    id: '3',
    name: 'ReLU',
    definition: 'Rectified Linear Unit - an activation function that outputs the input directly if positive, otherwise zero.',
    domain: 'Machine Learning',
    complexity: 4,
    prerequisites: ['Activation Functions'],
    related: ['Neural Networks', 'Sigmoid', 'Tanh'],
    mastery: 85,
    lastReviewed: new Date('2026-01-29'),
  },
  {
    id: '4',
    name: 'LSTM',
    definition: 'Long Short-Term Memory networks are a special kind of RNN capable of learning long-term dependencies.',
    domain: 'Machine Learning',
    complexity: 9,
    prerequisites: ['RNN', 'Gradient Descent'],
    related: ['GRU', 'Seq2Seq', 'Attention'],
    mastery: 45,
    lastReviewed: new Date('2026-01-25'),
  },
  {
    id: '5',
    name: 'CNN',
    definition: 'Convolutional Neural Networks are designed to process data with grid-like topology such as images.',
    domain: 'Machine Learning',
    complexity: 7,
    prerequisites: ['Neural Networks', 'Convolution'],
    related: ['Pooling', 'Filters', 'Image Recognition'],
    mastery: 60,
    lastReviewed: new Date('2026-01-26'),
  },
];

export const mockFeedItems: FeedItem[] = [
  {
    id: 'fc1',
    type: 'flashcard',
    concept: mockConcepts[0],
  },
  {
    id: 'quiz1',
    type: 'quiz',
    question: 'Which algorithm is used to update weights in a neural network during training?',
    options: [
      { id: 'a', text: 'K-Means Clustering', isCorrect: false },
      { id: 'b', text: 'Backpropagation', isCorrect: true },
      { id: 'c', text: 'Random Forest', isCorrect: false },
      { id: 'd', text: 'Principal Component Analysis', isCorrect: false },
    ],
    explanation: 'Backpropagation calculates gradients by propagating errors backwards through the network layers.',
    relatedConcept: 'Neural Networks',
  },
  {
    id: 'fb1',
    type: 'fillblank',
    sentence: 'The __________ function introduces non-linearity into neural networks, allowing them to learn complex patterns.',
    answer: 'activation',
    hint: 'ReLU is a popular example',
    relatedConcept: 'Neural Networks',
  },
  {
    id: 'fc2',
    type: 'flashcard',
    concept: mockConcepts[3],
  },
  {
    id: 'quiz2',
    type: 'quiz',
    question: 'What is the main advantage of LSTM over standard RNN?',
    options: [
      { id: 'a', text: 'Faster training speed', isCorrect: false },
      { id: 'b', text: 'Better at long-term dependencies', isCorrect: true },
      { id: 'c', text: 'Requires less data', isCorrect: false },
      { id: 'd', text: 'Simpler architecture', isCorrect: false },
    ],
    explanation: 'LSTMs use gating mechanisms to maintain information over longer sequences, solving the vanishing gradient problem.',
    relatedConcept: 'LSTM',
  },
  {
    id: 'd1',
    type: 'diagram',
    mermaidCode: `graph TD
    A[Neural Network] --> B[Input Layer]
    A --> C[Hidden Layers]
    A --> D[Output Layer]
    C --> E[Backpropagation]`,
    caption: 'Neural Network Architecture',
    sourceNote: 'Deep Learning Notes - Chapter 3',
  },
];

export const mockUserStats: UserStats = {
  conceptsLearned: 156,
  notesAdded: 12,
  accuracy: 85,
  streakDays: 7,
};

export const mockDomainProgress: DomainProgress[] = [
  { name: 'Machine Learning', progress: 78, color: '#B6FF2E' },
  { name: 'Database Systems', progress: 42, color: '#2EFFE6' },
  { name: 'Mathematics', progress: 95, color: '#FF6B6B' },
  { name: 'System Design', progress: 28, color: '#9B59B6' },
];

export const mockChatMessages: ChatMessage[] = [
  {
    id: '1',
    role: 'assistant',
    content: 'Hi! I\'m your knowledge assistant. I can help you explore your notes and concepts. Try:\n• "Explain neural networks"\n• "What prerequisites do I need for LSTM?"\n• "Show me my notes on backpropagation"',
  },
  {
    id: '2',
    role: 'user',
    content: 'Explain the difference between CNN and RNN',
  },
  {
    id: '3',
    role: 'assistant',
    content: 'Great question! Based on your notes:\n\n**CNN (Convolutional Neural Network)**\n• Best for spatial data (images, video)\n• Uses convolution filters to detect patterns\n• Your mastery: 60%\n\n**RNN (Recurrent Neural Network)**\n• Best for sequential data (text, time series)\n• Has memory of previous inputs\n• Your mastery: 45%',
    sources: ['Deep Learning Notes - Chapter 5', 'ML Interview Prep'],
    relatedConcepts: ['Pooling', 'LSTM', 'Attention'],
  },
];

export const mockGraphNodes: GraphNode[] = [
  { id: '1', name: 'Neural Net', x: 0, y: 0, z: 0, size: 1.2, color: '#B6FF2E', mastery: 65 },
  { id: '2', name: 'CNN', x: -3, y: -2, z: 1, size: 1.0, color: '#2EFFE6', mastery: 60 },
  { id: '3', name: 'RNN', x: 3, y: -2, z: -1, size: 0.9, color: '#FF6B6B', mastery: 45 },
  { id: '4', name: 'Pooling', x: -4, y: -4, z: 2, size: 0.7, color: '#2EFFE6', mastery: 70 },
  { id: '5', name: 'LSTM', x: 4, y: -4, z: 0, size: 1.1, color: '#FF6B6B', mastery: 45 },
  { id: '6', name: 'GRU', x: 5, y: -3, z: -2, size: 0.8, color: '#FF6B6B', mastery: 30 },
  { id: '7', name: 'Backprop', x: 0, y: 3, z: 0, size: 1.0, color: '#9B59B6', mastery: 70 },
  { id: '8', name: 'Gradient', x: -2, y: 5, z: 1, size: 0.8, color: '#9B59B6', mastery: 75 },
  { id: '9', name: 'Loss', x: 0, y: 5, z: -1, size: 0.7, color: '#9B59B6', mastery: 80 },
  { id: '10', name: 'Optimizer', x: 2, y: 5, z: 0, size: 0.8, color: '#9B59B6', mastery: 55 },
];

export const mockGraphEdges: GraphEdge[] = [
  { source: '1', target: '2', strength: 0.8 },
  { source: '1', target: '3', strength: 0.8 },
  { source: '2', target: '4', strength: 0.9 },
  { source: '3', target: '5', strength: 0.85 },
  { source: '3', target: '6', strength: 0.75 },
  { source: '1', target: '7', strength: 0.9 },
  { source: '7', target: '8', strength: 0.8 },
  { source: '7', target: '9', strength: 0.85 },
  { source: '7', target: '10', strength: 0.7 },
];

export const heatmapData = [
  [0, 1, 2, 3, 1, 2, 3, 4, 2, 1, 3, 2, 1, 0, 2, 3],
  [1, 2, 3, 4, 2, 1, 0, 2, 3, 4, 2, 1, 2, 3, 1, 2],
  [2, 1, 0, 2, 3, 4, 2, 1, 0, 2, 3, 4, 3, 2, 1, 0],
  [3, 4, 2, 1, 0, 2, 3, 4, 2, 1, 0, 2, 1, 2, 3, 4],
  [1, 2, 3, 4, 2, 1, 0, 2, 3, 4, 2, 1, 0, 1, 2, 3],
  [0, 1, 2, 3, 4, 2, 1, 0, 2, 3, 4, 2, 1, 2, 3, 4],
  [2, 3, 4, 2, 1, 0, 2, 3, 4, 2, 1, 0, 2, 3, 4, 2],
];
