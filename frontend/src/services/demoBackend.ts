import type { ChatMessage } from '../types';
import { DEMO_USER } from '../lib/demoMode';

type DemoSource = {
  id: string;
  title: string;
  content?: string;
  images?: string[];
};

type DemoConversationMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: DemoSource[];
  relatedConcepts?: string[];
  metadata?: {
    intent?: string;
    entities?: string[];
    documents_retrieved?: number;
    nodes_retrieved?: number;
  };
};

type DemoConversation = {
  id: string;
  title: string;
  updated_at: string;
  messages: DemoConversationMessage[];
};

type DemoConcept = {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity: number;
  mastery: number;
  prerequisites: string[];
  related: string[];
  tagline: string;
};

type DemoNoteChunk = {
  id: string;
  content: string;
  chunk_level: string;
  chunk_index: number;
  page_start?: number;
  page_end?: number;
  images: string[];
};

type DemoNote = {
  id: string;
  title: string;
  resource_type: string;
  created_at: string;
  content_text: string;
  preview: string;
  source_url?: string;
  chunks: DemoNoteChunk[];
};

type DemoUpload = {
  id: string;
  upload_type: string;
  file_url: string;
  thumbnail_url?: string;
  title?: string;
  description?: string;
  created_at: string;
};

type DemoIngestSession = {
  thread_id: string;
  mode: 'review' | 'background' | 'complete';
  title: string;
  content: string;
  created_at: string;
  poll_count: number;
  approved_concepts: DemoConcept[];
};

type DemoChatStreamParams = {
  message: string;
  conversationId: string;
  sourceIds?: string[];
  onStatus: (status: string) => void;
  onChunk: (chunk: string) => void;
  onDone: (payload: any) => void;
  onError: (error: string) => void;
};

type DemoQuizStreamParams = {
  topic: string;
  onStatus: (status: string) => void;
  onDone: (payload: any) => void;
  onError: (error: string) => void;
};

const DOMAIN_COLORS: Record<string, string> = {
  'NLP Foundations': '#2EFFE6',
  'LLM Systems': '#B6FF2E',
  'Retrieval & Agents': '#F59E0B',
  'Alignment & Evaluation': '#FF6B6B',
  'Generative AI': '#8B5CF6',
};

const jsonResponse = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
    },
  });

const clone = <T,>(value: T): T =>
  typeof structuredClone === 'function'
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const slugify = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');

const escapeSvg = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');

const svgDataUri = (
  title: string,
  subtitle: string,
  accent: string,
  lines: string[] = [],
) => {
  const lineMarkup = lines
    .map(
      (line, index) =>
        `<text x="40" y="${160 + index * 22}" fill="#D4D7E1" font-size="16" font-family="IBM Plex Sans, sans-serif">${escapeSvg(
          line,
        )}</text>`,
    )
    .join('');

  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720">
      <defs>
        <linearGradient id="g" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stop-color="#0C111B" />
          <stop offset="100%" stop-color="#151A27" />
        </linearGradient>
      </defs>
      <rect width="1200" height="720" rx="40" fill="url(#g)" />
      <rect x="40" y="40" width="1120" height="640" rx="28" fill="rgba(255,255,255,0.03)" stroke="${accent}" stroke-width="2" />
      <circle cx="1080" cy="120" r="56" fill="${accent}" fill-opacity="0.18" />
      <circle cx="1080" cy="120" r="24" fill="${accent}" fill-opacity="0.45" />
      <text x="40" y="110" fill="#FFFFFF" font-size="44" font-weight="700" font-family="IBM Plex Sans, sans-serif">${escapeSvg(
        title,
      )}</text>
      <text x="40" y="138" fill="${accent}" font-size="18" font-weight="600" font-family="IBM Plex Sans, sans-serif">${escapeSvg(
        subtitle,
      )}</text>
      ${lineMarkup}
      <text x="40" y="652" fill="rgba(255,255,255,0.5)" font-size="14" font-family="IBM Plex Sans, sans-serif">GraphRecall demo visual</text>
    </svg>
  `;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
};

const isoDaysAgo = (daysAgo: number) => {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString();
};

const isoDaysAhead = (daysAhead: number) => {
  const date = new Date();
  date.setDate(date.getDate() + daysAhead);
  return date.toISOString().split('T')[0];
};

const DEMO_CONCEPTS: DemoConcept[] = [
  {
    id: 'tokenization',
    name: 'Tokenization',
    definition: 'The step that converts raw text into model-friendly tokens while preserving boundaries the model can learn over.',
    domain: 'NLP Foundations',
    complexity: 4,
    mastery: 86,
    prerequisites: [],
    related: ['embeddings', 'context-window'],
    tagline: 'Where language becomes model input.',
  },
  {
    id: 'embeddings',
    name: 'Embeddings',
    definition: 'Dense vector representations that place semantically similar text closer together in a continuous space.',
    domain: 'NLP Foundations',
    complexity: 5,
    mastery: 82,
    prerequisites: ['tokenization'],
    related: ['vector-database', 'rag'],
    tagline: 'Semantic geometry for language.',
  },
  {
    id: 'attention',
    name: 'Attention',
    definition: 'A mechanism that lets the model dynamically weight which tokens matter most for the current computation.',
    domain: 'NLP Foundations',
    complexity: 6,
    mastery: 78,
    prerequisites: ['embeddings'],
    related: ['self-attention', 'transformer'],
    tagline: 'Dynamic focus over context.',
  },
  {
    id: 'self-attention',
    name: 'Self-Attention',
    definition: 'Attention applied within a sequence so every token can condition on every other token in the same context window.',
    domain: 'LLM Systems',
    complexity: 7,
    mastery: 74,
    prerequisites: ['attention'],
    related: ['transformer', 'context-window'],
    tagline: 'Every token can look at every other token.',
  },
  {
    id: 'positional-encoding',
    name: 'Positional Encoding',
    definition: 'Signals injected into token representations so the model knows order even without recurrence.',
    domain: 'LLM Systems',
    complexity: 6,
    mastery: 69,
    prerequisites: ['tokenization'],
    related: ['transformer', 'self-attention'],
    tagline: 'Order for an order-agnostic architecture.',
  },
  {
    id: 'transformer',
    name: 'Transformer',
    definition: 'The dominant neural architecture for modern language models, built from self-attention, feed-forward blocks, and residual pathways.',
    domain: 'LLM Systems',
    complexity: 8,
    mastery: 81,
    prerequisites: ['self-attention', 'positional-encoding'],
    related: ['decoder-only-llm', 'fine-tuning'],
    tagline: 'The backbone of modern LLMs.',
  },
  {
    id: 'decoder-only-llm',
    name: 'Decoder-Only LLM',
    definition: 'A transformer variant optimized for next-token prediction, making it ideal for chat, code generation, and reasoning.',
    domain: 'LLM Systems',
    complexity: 7,
    mastery: 79,
    prerequisites: ['transformer'],
    related: ['context-window', 'in-context-learning'],
    tagline: 'Predict the next token, unlock broad intelligence.',
  },
  {
    id: 'context-window',
    name: 'Context Window',
    definition: 'The finite number of tokens a model can attend to in a single forward pass.',
    domain: 'LLM Systems',
    complexity: 5,
    mastery: 76,
    prerequisites: ['decoder-only-llm'],
    related: ['tokenization', 'in-context-learning'],
    tagline: 'How much of the conversation fits at once.',
  },
  {
    id: 'in-context-learning',
    name: 'In-Context Learning',
    definition: 'The model adapts behavior from examples and instructions in the prompt without updating weights.',
    domain: 'Generative AI',
    complexity: 6,
    mastery: 83,
    prerequisites: ['decoder-only-llm', 'context-window'],
    related: ['prompt-engineering', 'few-shot-prompting'],
    tagline: 'Learning from the prompt instead of retraining.',
  },
  {
    id: 'prompt-engineering',
    name: 'Prompt Engineering',
    definition: 'The craft of structuring instructions, context, examples, and output constraints to reliably steer model behavior.',
    domain: 'Generative AI',
    complexity: 5,
    mastery: 91,
    prerequisites: ['in-context-learning'],
    related: ['tool-calling', 'agents'],
    tagline: 'Designing the interface to model behavior.',
  },
  {
    id: 'fine-tuning',
    name: 'Fine-Tuning',
    definition: 'Additional training on task-specific data so a pretrained model internalizes a new style, behavior, or domain.',
    domain: 'Generative AI',
    complexity: 7,
    mastery: 68,
    prerequisites: ['transformer'],
    related: ['rlhf', 'evals'],
    tagline: 'Move behavior from prompt-time to weights.',
  },
  {
    id: 'rag',
    name: 'Retrieval-Augmented Generation',
    definition: 'A system pattern that retrieves external knowledge and injects it into generation time to improve grounding and freshness.',
    domain: 'Retrieval & Agents',
    complexity: 7,
    mastery: 88,
    prerequisites: ['embeddings', 'context-window'],
    related: ['vector-database', 'reranking', 'agents'],
    tagline: 'Ground generation with retrieved evidence.',
  },
  {
    id: 'vector-database',
    name: 'Vector Database',
    definition: 'A storage system optimized for nearest-neighbor lookup over embeddings, often used in semantic search and RAG.',
    domain: 'Retrieval & Agents',
    complexity: 6,
    mastery: 73,
    prerequisites: ['embeddings'],
    related: ['rag', 'reranking'],
    tagline: 'Search by meaning instead of exact words.',
  },
  {
    id: 'reranking',
    name: 'Reranking',
    definition: 'A second-pass scoring step that improves retrieval quality by ordering retrieved documents with a stronger relevance model.',
    domain: 'Retrieval & Agents',
    complexity: 6,
    mastery: 64,
    prerequisites: ['vector-database'],
    related: ['rag', 'evals'],
    tagline: 'Turn okay retrieval into strong retrieval.',
  },
  {
    id: 'tool-calling',
    name: 'Tool Calling',
    definition: 'A mechanism that lets an LLM emit structured arguments so external tools or APIs can be invoked safely and reliably.',
    domain: 'Retrieval & Agents',
    complexity: 6,
    mastery: 77,
    prerequisites: ['prompt-engineering'],
    related: ['agents', 'rag'],
    tagline: 'From text generation to structured actions.',
  },
  {
    id: 'agents',
    name: 'Agents',
    definition: 'LLM-powered systems that plan, decide when to call tools, observe results, and iterate toward a goal.',
    domain: 'Retrieval & Agents',
    complexity: 8,
    mastery: 71,
    prerequisites: ['tool-calling', 'rag'],
    related: ['prompt-engineering', 'evals'],
    tagline: 'Reason, act, observe, and continue.',
  },
  {
    id: 'rlhf',
    name: 'RLHF',
    definition: 'Reinforcement Learning from Human Feedback aligns model behavior by optimizing toward human preference signals.',
    domain: 'Alignment & Evaluation',
    complexity: 8,
    mastery: 66,
    prerequisites: ['fine-tuning'],
    related: ['safety-guardrails', 'hallucinations'],
    tagline: 'Preference shaping after pretraining.',
  },
  {
    id: 'hallucinations',
    name: 'Hallucinations',
    definition: 'Fluent but unsupported model outputs that arise when generation is weakly grounded or overconfident.',
    domain: 'Alignment & Evaluation',
    complexity: 5,
    mastery: 84,
    prerequisites: ['decoder-only-llm'],
    related: ['rag', 'evals', 'safety-guardrails'],
    tagline: 'Confident language without reliable evidence.',
  },
  {
    id: 'safety-guardrails',
    name: 'Safety Guardrails',
    definition: 'Policies, filters, and control layers that reduce harmful, off-policy, or ungrounded outputs in production systems.',
    domain: 'Alignment & Evaluation',
    complexity: 6,
    mastery: 72,
    prerequisites: ['hallucinations', 'rlhf'],
    related: ['agents', 'evals'],
    tagline: 'Operational boundaries around model behavior.',
  },
  {
    id: 'evals',
    name: 'Eval Benchmarks',
    definition: 'Task suites and rubric-driven checks used to measure quality, regressions, safety, and groundedness in AI systems.',
    domain: 'Alignment & Evaluation',
    complexity: 6,
    mastery: 75,
    prerequisites: ['hallucinations'],
    related: ['rag', 'agents', 'safety-guardrails'],
    tagline: 'What gets measured gets improved.',
  },
];

const conceptById = new Map(DEMO_CONCEPTS.map((concept) => [concept.id, concept]));
const conceptByName = new Map(DEMO_CONCEPTS.map((concept) => [concept.name.toLowerCase(), concept]));

const conceptArt: Record<string, string> = {
  transformer: svgDataUri(
    'Transformer Stack',
    'Self-attention + feed-forward layers',
    DOMAIN_COLORS['LLM Systems'],
    [
      'Tokens -> embeddings -> positional encoding',
      'Multi-head self-attention discovers dependencies',
      'Residual blocks keep optimization stable',
      'Decoder-only variants dominate chat and code models',
    ],
  ),
  rag: svgDataUri(
    'RAG Pipeline',
    'Retriever + reranker + grounded response',
    DOMAIN_COLORS['Retrieval & Agents'],
    [
      'Query -> embedding -> vector search',
      'Rerank for faithfulness and precision',
      'Inject evidence into the prompt',
      'Return answer with citations and confidence',
    ],
  ),
  evals: svgDataUri(
    'LLM Evaluation Loop',
    'Offline benchmarks and online feedback',
    DOMAIN_COLORS['Alignment & Evaluation'],
    [
      'Golden tasks track regressions across releases',
      'Human review catches nuance and harmful edge cases',
      'Production telemetry closes the loop',
    ],
  ),
};

const buildConceptNotes = (concept: DemoConcept): DemoNote[] => {
  const image = conceptArt[concept.id] || svgDataUri(
    concept.name,
    concept.tagline,
    DOMAIN_COLORS[concept.domain],
    [concept.definition],
  );

  const chunkLines = [
    `**${concept.name}** lives in the ${concept.domain} cluster of the GraphRecall demo workspace.`,
    concept.definition,
    concept.prerequisites.length > 0
      ? `Prerequisites: ${concept.prerequisites
          .map((id) => conceptById.get(id)?.name || id)
          .join(', ')}.`
      : 'This is a foundation concept with no strict prerequisite in the demo graph.',
    concept.related.length > 0
      ? `Closest neighbors in the graph: ${concept.related
          .map((id) => conceptById.get(id)?.name || id)
          .join(', ')}.`
      : 'It connects broadly across the graph.',
  ];

  const title = `${concept.name} Design Notes`;
  const noteId = `note-${concept.id}`;

  return [
    {
      id: noteId,
      title,
      resource_type: 'note',
      created_at: isoDaysAgo(3),
      preview: chunkLines[1],
      content_text: chunkLines.join('\n\n'),
      chunks: [
        {
          id: `${noteId}-chunk-1`,
          chunk_level: 'section',
          chunk_index: 0,
          page_start: 1,
          page_end: 2,
          images: [image],
          content: chunkLines.join('\n\n'),
        },
      ],
    },
  ];
};

const customConceptNotes: Record<string, DemoNote[]> = {
  transformer: [
    {
      id: 'note-transformer-architecture',
      title: 'Transformer Notes - Attention Stack',
      resource_type: 'note',
      created_at: isoDaysAgo(1),
      preview:
        'The demo project treats the Transformer as the bridge between NLP primitives and downstream LLM products.',
      content_text:
        'The Transformer replaces recurrence with self-attention and parallel feed-forward blocks.',
      chunks: [
        {
          id: 'note-transformer-architecture-1',
          chunk_level: 'section',
          chunk_index: 0,
          page_start: 11,
          page_end: 12,
          images: [conceptArt.transformer],
          content:
            'The **Transformer** turns token embeddings into contextual representations by alternating **multi-head self-attention** with feed-forward layers. In the demo graph, it is the hinge point that links foundational NLP ideas like embeddings and positional encoding to production concerns like fine-tuning and context-window limits.',
        },
        {
          id: 'note-transformer-architecture-2',
          chunk_level: 'section',
          chunk_index: 1,
          page_start: 12,
          page_end: 13,
          images: [],
          content:
            'Key intuition: each token builds a weighted summary of the rest of the sequence. That is why concepts like **Self-Attention**, **Context Window**, and **In-Context Learning** are clustered so tightly around the Transformer node in demo mode.',
        },
      ],
    },
  ],
  rag: [
    {
      id: 'note-rag-playbook',
      title: 'RAG System Design Review',
      resource_type: 'documentation',
      created_at: isoDaysAgo(2),
      preview:
        'Retrieval-augmented generation is shown as a system, not just a prompt trick: embedding, retrieve, rerank, cite.',
      source_url: 'https://example.com/rag-playbook',
      content_text: 'RAG combines embeddings, search, reranking, and grounded response synthesis.',
      chunks: [
        {
          id: 'note-rag-playbook-1',
          chunk_level: 'section',
          chunk_index: 0,
          page_start: 4,
          page_end: 5,
          images: [conceptArt.rag],
          content:
            'In this demo, **RAG** is modeled as a multi-step system: embed the query, retrieve candidate chunks, rerank them, and pass only the highest-signal evidence into generation. This keeps answers grounded and dramatically reduces hallucinations for enterprise knowledge tasks.',
        },
        {
          id: 'note-rag-playbook-2',
          chunk_level: 'section',
          chunk_index: 1,
          page_start: 5,
          page_end: 6,
          images: [],
          content:
            'The graph intentionally connects **RAG** to **Vector Database**, **Reranking**, **Agents**, and **Hallucinations** so the user can navigate from mechanics to product tradeoffs without leaving the graph view.',
        },
      ],
    },
  ],
  evals: [
    {
      id: 'note-eval-checklist',
      title: 'LLM Evaluation Checklist',
      resource_type: 'note',
      created_at: isoDaysAgo(4),
      preview:
        'Benchmarks alone are not enough; the demo emphasizes offline metrics, rubric grading, and production telemetry together.',
      content_text:
        'Evaluation should cover accuracy, grounding, latency, safety, and failure analysis.',
      chunks: [
        {
          id: 'note-eval-checklist-1',
          chunk_level: 'section',
          chunk_index: 0,
          page_start: 2,
          page_end: 3,
          images: [conceptArt.evals],
          content:
            'The demo evaluation note frames **Eval Benchmarks** as a product discipline. Offline tasks catch regressions before release, while rubric-based human review and live telemetry tell you whether the system is still safe and useful under real workload variation.',
        },
      ],
    },
  ],
};

const books: DemoNote[] = [
  {
    id: 'book-slp',
    title: 'Speech and Language Processing - Demo Highlights',
    resource_type: 'book',
    created_at: isoDaysAgo(8),
    preview: 'Classical NLP foundations that still explain why transformer systems behave the way they do.',
    content_text:
      'A curated reading log covering tokenization, embeddings, attention, and sequence modeling.',
    chunks: [
      {
        id: 'book-slp-chunk-1',
        chunk_level: 'chapter',
        chunk_index: 0,
        page_start: 22,
        page_end: 24,
        images: [],
        content:
          'Classical NLP ideas still matter. The demo uses this book summary to connect symbolic preprocessing, tokenization, and probabilistic language modeling to the modern Transformer era.',
      },
    ],
  },
  {
    id: 'book-genai-engineering',
    title: 'Generative AI Engineering Notes',
    resource_type: 'book',
    created_at: isoDaysAgo(5),
    preview: 'Product patterns for prompt design, RAG, evaluation, and agent orchestration.',
    content_text:
      'Field notes on turning LLMs into production systems with observability and control.',
    chunks: [
      {
        id: 'book-genai-engineering-chunk-1',
        chunk_level: 'chapter',
        chunk_index: 0,
        page_start: 30,
        page_end: 32,
        images: [],
        content:
          'Production GenAI requires more than model quality. You need retrieval, tool boundaries, evals, and guardrails. That framing is reflected across the entire GraphRecall demo graph.',
      },
    ],
  },
];

const notesByConceptId = new Map<string, DemoNote[]>();
for (const concept of DEMO_CONCEPTS) {
  notesByConceptId.set(concept.id, customConceptNotes[concept.id] || buildConceptNotes(concept));
}

const baseNotes = [
  ...Array.from(notesByConceptId.values()).flat(),
  ...books,
].map((note) => ({
  ...note,
  preview: note.preview || note.content_text.slice(0, 160),
}));

const buildGraph = () => {
  const nodes = DEMO_CONCEPTS.map((concept) => ({
    id: concept.id,
    name: concept.name,
    definition: concept.definition,
    domain: concept.domain,
    complexity_score: concept.complexity,
    mastery: concept.mastery,
    color: DOMAIN_COLORS[concept.domain],
    size: 1 + concept.complexity / 8,
  }));

  const edgeMap = new Map<string, any>();
  for (const concept of DEMO_CONCEPTS) {
    for (const prerequisiteId of concept.prerequisites) {
      if (!conceptById.has(prerequisiteId)) continue;
      const edgeId = `${prerequisiteId}->${concept.id}:PREREQUISITE_OF`;
      edgeMap.set(edgeId, {
        id: edgeId,
        source: prerequisiteId,
        target: concept.id,
        relationship_type: 'PREREQUISITE_OF',
        strength: 0.88,
      });
    }
    for (const relatedId of concept.related) {
      if (!conceptById.has(relatedId)) continue;
      const pair = [concept.id, relatedId].sort().join('::');
      if (!edgeMap.has(pair)) {
        edgeMap.set(pair, {
          id: pair,
          source: concept.id,
          target: relatedId,
          relationship_type: 'RELATED_TO',
          strength: 0.7,
        });
      }
    }
  }

  const communities = Array.from(new Set(DEMO_CONCEPTS.map((concept) => concept.domain))).map(
    (domain, index) => ({
      id: `community-${slugify(domain)}`,
      title: domain,
      level: 0,
      children: [],
      entity_ids: DEMO_CONCEPTS.filter((concept) => concept.domain === domain).map(
        (concept) => concept.id,
      ),
      size: DEMO_CONCEPTS.filter((concept) => concept.domain === domain).length,
      computedColor: DOMAIN_COLORS[domain] || '#95a5a6',
      order: index,
    }),
  );

  return {
    nodes,
    edges: Array.from(edgeMap.values()),
    communities,
  };
};

const graphData = buildGraph();

const buildFeedItems = () => [
  {
    id: 'feed-transformer-card',
    item_type: 'flashcard',
    concept_id: 'transformer',
    concept_name: 'Transformer',
    domain: 'LLM Systems',
    created_at: isoDaysAgo(0),
    content: {
      definition: conceptById.get('transformer')?.definition,
      complexity: 8,
      prerequisites: ['Self-Attention', 'Positional Encoding'],
      related_concepts: ['Decoder-Only LLM', 'Fine-Tuning'],
      mastery: 81,
      back:
        'A Transformer alternates self-attention and feed-forward blocks so every token can condition on the rest of the sequence in parallel.',
    },
  },
  {
    id: 'feed-self-attention-quiz',
    item_type: 'mcq',
    concept_id: 'self-attention',
    concept_name: 'Self-Attention',
    domain: 'LLM Systems',
    created_at: isoDaysAgo(0),
    content: {
      question: 'What does self-attention let each token do inside a sequence?',
      options: [
        'Ignore the rest of the context and only preserve its own embedding',
        'Compute weighted interactions with other tokens in the same context window',
        'Cache gradients for future training steps',
        'Select only the final token as context',
      ],
      correct_answer: 'B',
      explanation:
        'Self-attention gives each token a weighted summary of the rest of the sequence, which is why transformers capture long-range dependencies so well.',
      source_url: 'https://example.com/self-attention-demo',
    },
  },
  {
    id: 'feed-rag-fillblank',
    item_type: 'fill_blank',
    concept_id: 'rag',
    concept_name: 'Retrieval-Augmented Generation',
    domain: 'Retrieval & Agents',
    created_at: isoDaysAgo(0),
    content: {
      sentence:
        'A strong RAG pipeline usually retrieves, then __________ candidate chunks before answer generation.',
      answers: ['reranks'],
      hint: 'It is the second-pass relevance stage that improves precision.',
    },
  },
  {
    id: 'feed-rlhf-showcase',
    item_type: 'concept_showcase',
    concept_id: 'rlhf',
    concept_name: 'RLHF',
    domain: 'Alignment & Evaluation',
    created_at: isoDaysAgo(0),
    content: {
      concept_name: 'RLHF',
      definition: conceptById.get('rlhf')?.definition,
      domain: 'Alignment & Evaluation',
      complexity_score: 8,
      tagline: 'Preference shaping after pretraining.',
      visual_metaphor: 'Think of RLHF as post-production direction for model behavior.',
      key_points: [
        'Collect preference comparisons from humans or synthetic judges',
        'Train a reward model that approximates those preferences',
        'Use policy optimization to shift model behavior toward preferred outputs',
      ],
      real_world_example:
        'Chat assistants use RLHF-style alignment to become more helpful, less toxic, and more on-policy.',
      connections_note:
        'In the graph, RLHF links naturally to safety guardrails, hallucinations, and evaluation loops.',
      emoji_icon: 'AI',
      prerequisites: ['Fine-Tuning'],
      related_concepts: ['Safety Guardrails', 'Hallucinations', 'Eval Benchmarks'],
    },
  },
  {
    id: 'feed-rag-screenshot',
    item_type: 'screenshot',
    concept_id: 'rag',
    concept_name: 'Retrieval-Augmented Generation',
    domain: 'Retrieval & Agents',
    created_at: isoDaysAgo(0),
    content: {
      file_url: conceptArt.rag,
      thumbnail_url: conceptArt.rag,
      title: 'RAG System Snapshot',
      description:
        'A visual summary of retrieval, reranking, and grounded answer synthesis.',
      linked_concepts: ['RAG', 'Vector Database', 'Reranking'],
    },
  },
  {
    id: 'feed-transformer-diagram',
    item_type: 'mermaid_diagram',
    concept_id: 'transformer',
    concept_name: 'Transformer',
    domain: 'LLM Systems',
    created_at: isoDaysAgo(0),
    content: {
      title: 'Transformer to Chat Stack',
      source_note_id: 'note-transformer-architecture',
      mermaid_code: `graph TD
  A[Tokenization] --> B[Embeddings]
  B --> C[Positional Encoding]
  C --> D[Self-Attention Blocks]
  D --> E[Decoder-Only LLM]
  E --> F[In-Context Learning]
  F --> G[Prompt Engineering]
  G --> H[Tool Calling]
  H --> I[Agents]`,
    },
  },
  {
    id: 'feed-agent-code',
    item_type: 'code_challenge',
    concept_id: 'agents',
    concept_name: 'Agents',
    domain: 'Retrieval & Agents',
    created_at: isoDaysAgo(0),
    content: {
      question:
        'Complete the function so the agent only calls retrieval when the query asks for evidence or citations.',
      language: 'python',
      initial_code: `def should_retrieve(user_query: str) -> bool:\n    query = user_query.lower()\n    evidence_cues = ["cite", "source", "evidence", "document", "ground"]\n    # TODO: return True when any cue appears in the query\n`,
      correct_answer: `def should_retrieve(user_query: str) -> bool:\n    query = user_query.lower()\n    evidence_cues = ["cite", "source", "evidence", "document", "ground"]\n    return any(cue in query for cue in evidence_cues)\n`,
      explanation:
        'A lightweight routing heuristic is often enough to decide when the agent should pay retrieval cost.',
      source_url: 'https://example.com/agent-routing-demo',
    },
  },
  {
    id: 'feed-prompt-card',
    item_type: 'flashcard',
    concept_id: 'prompt-engineering',
    concept_name: 'Prompt Engineering',
    domain: 'Generative AI',
    created_at: isoDaysAgo(0),
    content: {
      definition: conceptById.get('prompt-engineering')?.definition,
      complexity: 5,
      prerequisites: ['In-Context Learning'],
      related_concepts: ['Tool Calling', 'Agents'],
      mastery: 91,
      back:
        'Good prompts specify the task, context, constraints, success criteria, and preferred output shape.',
    },
  },
];

const demoQuizHistory = [
  {
    id: 'quiz-embeddings-semantic',
    topic: 'Embeddings',
    question_type: 'mcq',
    question_text: 'Why are embeddings useful in semantic search?',
    options: [
      'They make text longer and therefore easier to index',
      'They place semantically related text near each other in vector space',
      'They remove the need for chunking',
      'They guarantee factual answers',
    ],
    correct_answer: 'B',
    explanation:
      'Embedding vectors preserve semantic proximity, so nearest-neighbor search can retrieve meaningfully related passages.',
    source_url: 'https://example.com/semantic-search-demo',
  },
  {
    id: 'quiz-context-window-flash',
    topic: 'Context Window',
    question_type: 'flashcard',
    question_text: 'What is a context window?',
    front_content: 'Define context window',
    back_content:
      'The maximum number of tokens the model can attend to at once during a single forward pass.',
    correct_answer:
      'The maximum number of tokens the model can attend to at once during a single forward pass.',
    explanation:
      'Prompt design, retrieval selection, and memory strategies all work inside this limit.',
  },
  {
    id: 'quiz-finetuning-fillblank',
    topic: 'Fine-Tuning',
    question_type: 'fill_blank',
    question_text:
      'Fine-tuning moves behavior from prompt-time instructions into model __________.',
    correct_answer: 'weights',
    explanation:
      'Fine-tuning adjusts parameters, making the behavior more persistent than prompt-only steering.',
  },
  {
    id: 'quiz-rag-grounding',
    topic: 'RAG',
    question_type: 'mcq',
    question_text: 'Which stage most directly reduces hallucinations in a RAG pipeline?',
    options: [
      'Adding more emojis to the system prompt',
      'Grounding the answer in retrieved evidence with citations',
      'Making the model temperature extremely high',
      'Removing all retrieval metadata',
    ],
    correct_answer: 'B',
    explanation:
      'Grounded evidence plus citation discipline gives the model less room to invent unsupported claims.',
  },
  {
    id: 'quiz-agent-routing-code',
    topic: 'Agents',
    question_type: 'code_challenge',
    question_text: 'Write a simple rule that routes evidence-seeking queries to retrieval.',
    initial_code:
      'def route(query: str) -> str:\n    cues = ["citation", "source", "evidence"]\n    # return "retrieve" or "answer"\n',
    correct_answer:
      'def route(query: str) -> str:\n    cues = ["citation", "source", "evidence"]\n    return "retrieve" if any(cue in query.lower() for cue in cues) else "answer"\n',
    explanation:
      'This is the simplest version of an agent policy: inspect the request and route accordingly.',
    language: 'python',
  },
  {
    id: 'quiz-hallucinations-mitigation',
    topic: 'Hallucinations',
    question_type: 'mcq',
    question_text: 'What combination best mitigates hallucinations in a production LLM system?',
    options: [
      'Higher temperature and longer answers',
      'Grounded retrieval, evals, and clear refusal behavior',
      'Bigger context windows only',
      'Removing safety filters to reduce latency',
    ],
    correct_answer: 'B',
    explanation:
      'Hallucinations are best handled at the system level with retrieval, evaluation, and guardrails together.',
  },
];

const buildResourcesByTopic = () => {
  const resources = new Map<string, any[]>();
  for (const concept of DEMO_CONCEPTS) {
    const conceptNotes = notesByConceptId.get(concept.id) || [];
    const noteResources = conceptNotes.map((note) => ({
      title: note.title,
      created_at: note.created_at,
      preview: note.preview,
      type: 'note',
    }));

    const linkResource = {
      title: `${concept.name} Engineering Brief`,
      created_at: isoDaysAgo(2),
      preview: `${concept.tagline} This external brief is part of the visual demo and helps show article/link handling in the graph inspector.`,
      resource_type: 'documentation',
      source_url: `https://example.com/${slugify(concept.name)}`,
    };

    resources.set(concept.name.toLowerCase(), [...noteResources, linkResource]);
  }
  return resources;
};

const resourcesByTopic = buildResourcesByTopic();

const buildConversations = (): DemoConversation[] => [
  {
    id: 'conv-transformer-intuition',
    title: 'Transformer intuition',
    updated_at: isoDaysAgo(0),
    messages: [
      {
        id: 'msg-demo-assistant-intro',
        role: 'assistant',
        content:
          'This demo workspace is preloaded with **NLP**, **LLMs**, and **Generative AI** concepts. Try asking about Transformers, RAG, agents, evaluation, or alignment.',
        relatedConcepts: ['Transformer', 'RAG', 'Agents'],
      },
      {
        id: 'msg-demo-user-transformer',
        role: 'user',
        content: 'Give me a crisp intuition for the Transformer.',
      },
      {
        id: 'msg-demo-assistant-transformer',
        role: 'assistant',
        content:
          'The **Transformer** is powerful because every token can build a weighted summary of the other tokens in context using **self-attention**. That replaces brittle sequential processing with a parallel architecture that scales well for language modeling.[1]\n\nIn the demo graph, the Transformer sits between foundational concepts like **Embeddings** and downstream behaviors like **In-Context Learning** and **Fine-Tuning**.[2]',
        sources: [
          {
            id: 'note-transformer-architecture',
            title: 'Transformer Notes - Attention Stack',
            content:
              'The Transformer alternates self-attention and feed-forward blocks. Each token can condition on the rest of the sequence.',
            images: [conceptArt.transformer],
          },
          {
            id: 'book-slp',
            title: 'Speech and Language Processing - Demo Highlights',
            content:
              'Classical NLP foundations still explain why embeddings and sequence modeling matter in modern architectures.',
          },
        ],
        relatedConcepts: ['Transformer', 'Self-Attention', 'Embeddings'],
        metadata: {
          intent: 'explain',
          entities: ['Transformer'],
          documents_retrieved: 2,
          nodes_retrieved: 5,
        },
      },
      {
        id: 'msg-demo-user-rag-agents',
        role: 'user',
        content: '@connect RAG and agents',
      },
      {
        id: 'msg-demo-assistant-rag-agents',
        role: 'assistant',
        content:
          '**RAG** and **Agents** pair well because retrieval gives the agent grounded evidence, while tool use gives it the ability to act on that evidence.[1]\n\nA good mental model is:\n1. Retrieve the best knowledge snippets.\n2. Let the model reason over them.\n3. Call tools only when a step requires action or fresh state.\n4. Evaluate the loop for groundedness and latency.[2]',
        sources: [
          {
            id: 'note-rag-playbook',
            title: 'RAG System Design Review',
            content:
              'RAG improves grounding by retrieving evidence before generation and explicitly linking answers back to sources.',
            images: [conceptArt.rag],
          },
          {
            id: 'note-agents',
            title: 'Agents Design Notes',
            content:
              'Agents decide when to retrieve, when to call tools, and when to stop. Evaluation measures whether those choices help.',
          },
        ],
        relatedConcepts: ['RAG', 'Agents', 'Tool Calling'],
        metadata: {
          intent: 'connect',
          entities: ['RAG', 'Agents'],
          documents_retrieved: 2,
          nodes_retrieved: 6,
        },
      },
    ],
  },
  {
    id: 'conv-eval-checklist',
    title: 'Evaluation checklist',
    updated_at: isoDaysAgo(1),
    messages: [
      {
        id: 'msg-eval-user',
        role: 'user',
        content: '@path Build an eval plan for a customer support copilot',
      },
      {
        id: 'msg-eval-assistant',
        role: 'assistant',
        content:
          'Start with a layered plan:\n\n- **Task evals** for answer accuracy and groundedness.\n- **Safety evals** for refusals, policy adherence, and sensitive requests.\n- **Operational evals** for latency, retrieval quality, and tool correctness.\n- **Human review** for nuance that automated metrics miss.[1]\n\nThat is why the demo graph links **Eval Benchmarks**, **Hallucinations**, **Safety Guardrails**, and **Agents** into one cluster.[2]',
        sources: [
          {
            id: 'note-eval-checklist',
            title: 'LLM Evaluation Checklist',
            content:
              'Evaluation has to combine offline benchmarks, rubric review, and telemetry to be production-ready.',
            images: [conceptArt.evals],
          },
          {
            id: 'book-genai-engineering',
            title: 'Generative AI Engineering Notes',
            content:
              'Production GenAI needs monitoring, iteration, and system-level controls beyond model quality alone.',
          },
        ],
        relatedConcepts: ['Eval Benchmarks', 'Safety Guardrails', 'Hallucinations'],
        metadata: {
          intent: 'path',
          entities: ['Eval Benchmarks', 'Safety Guardrails'],
          documents_retrieved: 2,
          nodes_retrieved: 7,
        },
      },
    ],
  },
  {
    id: 'conv-alignment-summary',
    title: 'Alignment summary',
    updated_at: isoDaysAgo(2),
    messages: [
      {
        id: 'msg-align-user',
        role: 'user',
        content: '@summary RLHF and safety guardrails',
      },
      {
        id: 'msg-align-assistant',
        role: 'assistant',
        content:
          '**RLHF** shapes the model itself toward preferred behavior, while **Safety Guardrails** act as operational control layers around the model in production.[1]\n\nUse RLHF when you want broad behavior change. Use guardrails when you need enforceable boundaries, policy checks, and post-generation intervention.[2]',
        sources: [
          {
            id: 'note-rlhf',
            title: 'RLHF Design Notes',
            content:
              'RLHF trains a reward model from preference data and optimizes the policy toward preferred outputs.',
          },
          {
            id: 'note-safety-guardrails',
            title: 'Safety Guardrails Design Notes',
            content:
              'Guardrails intercept or constrain model behavior at runtime with rules, filters, and tool policies.',
          },
        ],
        relatedConcepts: ['RLHF', 'Safety Guardrails', 'Hallucinations'],
        metadata: {
          intent: 'summarize',
          entities: ['RLHF', 'Safety Guardrails'],
          documents_retrieved: 2,
          nodes_retrieved: 5,
        },
      },
    ],
  },
];

const mapConversationMessageToChat = (message: DemoConversationMessage): ChatMessage => ({
  id: message.id,
  role: message.role,
  content: message.content,
  serverId: message.id,
  sources: message.sources?.map((source) => source.title),
  sourceObjects: message.sources?.map((source) => ({
    id: source.id,
    title: source.title,
    content: source.content,
    images: source.images,
  })),
  relatedConcepts: message.relatedConcepts,
  metadata: message.metadata,
});

const buildDailyActivity = () =>
  Array.from({ length: 35 }).map((_, index) => {
    const reviews = [4, 7, 0, 11, 16, 8, 5][index % 7];
    return {
      date: isoDaysAgo(34 - index),
      reviews_completed: reviews,
      concepts_learned: reviews > 0 ? Math.max(1, Math.floor(reviews / 4)) : 0,
      accuracy: reviews > 0 ? 0.76 + ((index % 5) * 0.04) : 0,
    };
  });

const buildSchedule = () =>
  [2, 3, 4, 5, 6, 7, 9, 10, 11, 13].map((daysAhead, index) => ({
    date: isoDaysAhead(daysAhead),
    count: 2 + (index % 4),
    topics: [
      'Transformer',
      'RAG',
      'Eval Benchmarks',
      'Prompt Engineering',
      'Agents',
    ].slice(0, 2 + (index % 3)),
  }));

const createDemoState = () => ({
  user: clone(DEMO_USER),
  graph: clone(graphData),
  notes: clone(baseNotes),
  uploads: [
    {
      id: 'upload-rag-board',
      upload_type: 'diagram',
      file_url: conceptArt.rag,
      thumbnail_url: conceptArt.rag,
      title: 'RAG architecture board',
      description: 'Visual explainer used in the demo chat and graph note panel.',
      created_at: isoDaysAgo(1),
    },
    {
      id: 'upload-transformer-board',
      upload_type: 'screenshot',
      file_url: conceptArt.transformer,
      thumbnail_url: conceptArt.transformer,
      title: 'Transformer block breakdown',
      description: 'A visual walkthrough of embeddings, attention, and residual flow.',
      created_at: isoDaysAgo(2),
    },
    {
      id: 'upload-eval-board',
      upload_type: 'infographic',
      file_url: conceptArt.evals,
      thumbnail_url: conceptArt.evals,
      title: 'Evaluation dashboard sketch',
      description: 'Offline, human, and production eval loops in one panel.',
      created_at: isoDaysAgo(3),
    },
  ] as DemoUpload[],
  feedItems: buildFeedItems(),
  quizHistory: clone(demoQuizHistory),
  likedItemIds: new Set<string>(['feed-transformer-card']),
  savedItemIds: new Set<string>([
    'quiz-rag-grounding',
    'feed-transformer-card',
    'quiz-context-window-flash',
  ]),
  completedToday: 6,
  dailyGoal: 18,
  accuracyRate: 0.89,
  streakDays: 17,
  dailyActivity: buildDailyActivity(),
  schedule: buildSchedule(),
  conversations: buildConversations(),
  settings: clone(DEMO_USER.settings_json),
  ingestionSessions: {} as Record<string, DemoIngestSession>,
  counters: {
    conversation: 4,
    message: 100,
    note: 100,
    upload: 100,
    node: 100,
    thread: 100,
    card: 100,
  },
});

let demoState = createDemoState();

const lookupConceptByTopic = (topic: string) => {
  const lower = topic.toLowerCase();
  return (
    DEMO_CONCEPTS.find((concept) => concept.name.toLowerCase().includes(lower)) ||
    DEMO_CONCEPTS.find((concept) => lower.includes(concept.name.toLowerCase())) ||
    conceptByName.get(lower) ||
    DEMO_CONCEPTS[0]
  );
};

const buildDomainProgress = () => {
  const grouped = new Map<string, number[]>();
  for (const node of demoState.graph.nodes) {
    const scores = grouped.get(node.domain) || [];
    scores.push(node.mastery || 0);
    grouped.set(node.domain, scores);
  }
  return Object.fromEntries(
    Array.from(grouped.entries()).map(([domain, scores]) => [
      domain,
      Math.round(scores.reduce((total, score) => total + score, 0) / scores.length),
    ]),
  );
};

const buildFeedResponse = () => ({
  items: clone(demoState.feedItems),
  completed_today: demoState.completedToday,
  daily_goal: demoState.dailyGoal,
  total_due_today: demoState.feedItems.length,
});

const buildStatsResponse = () => ({
  total_concepts: demoState.graph.nodes.length,
  total_notes: demoState.notes.length,
  accuracy_rate: demoState.accuracyRate,
  streak_days: demoState.streakDays,
  domain_progress: buildDomainProgress(),
  daily_activity: clone(demoState.dailyActivity),
});

const buildSavedItems = () => {
  const saved: any[] = [];
  const feedLookup = new Map(demoState.feedItems.map((item) => [item.id, item]));
  const quizLookup = new Map(demoState.quizHistory.map((item) => [item.id, item]));

  for (const id of demoState.savedItemIds) {
    if (feedLookup.has(id)) {
      const item = feedLookup.get(id);
      if (!item) continue;
      if (item.item_type === 'flashcard') {
        saved.push({
          id: item.id,
          item_category: 'flashcard',
          type: 'flashcard',
          topic: item.concept_name,
          front_content: item.concept_name,
          back_content: item.content.back || item.content.definition,
        });
      } else if (item.item_type === 'screenshot') {
        saved.push({
          id: item.id,
          question_text: item.content.title,
          explanation: item.content.description,
          topic: item.concept_name,
          options: [],
        });
      } else {
        saved.push({
          id: item.id,
          question_text: item.content.question || item.content.title || item.concept_name,
          explanation: item.content.explanation || item.content.description || '',
          topic: item.concept_name,
          options: item.content.options || [],
          correct_answer: item.content.correct_answer || '',
          source_url: item.content.source_url || '',
        });
      }
    } else if (quizLookup.has(id)) {
      saved.push(clone(quizLookup.get(id)));
    }
  }

  return saved;
};

const buildQuizPayload = (topic: string) => {
  const concept = lookupConceptByTopic(topic);
  const lower = topic.toLowerCase();

  const bank = {
    transformer: [
      {
        id: 'topic-transformer-1',
        question: 'Why did the Transformer displace RNN-heavy architectures for language modeling?',
        options: [
          'Because it removes the need for tokenization',
          'Because self-attention parallelizes sequence processing and captures long-range context better',
          'Because it only works on tiny datasets',
          'Because it never needs positional information',
        ],
        correct_answer: 'B',
        explanation:
          'Self-attention offers efficient parallel training and captures dependencies across long spans without recurrence.',
      },
      {
        id: 'topic-transformer-2',
        question: 'What role does positional encoding play in a Transformer?',
        options: [
          'It compresses the model weights after training',
          'It gives the architecture a notion of token order',
          'It selects the final answer token',
          'It decides which optimizer to use',
        ],
        correct_answer: 'B',
        explanation:
          'Without recurrence or convolution, the model needs explicit position signals to reason about order.',
      },
    ],
    rag: [
      {
        id: 'topic-rag-1',
        question: 'Which sequence best describes a mature RAG system?',
        options: [
          'Generate first, retrieve later, cite never',
          'Embed query, retrieve candidates, rerank, answer with evidence',
          'Tune the model on every user query',
          'Use temperature zero and skip retrieval entirely',
        ],
        correct_answer: 'B',
        explanation:
          'That sequence balances recall, precision, and grounded answer synthesis.',
      },
      {
        id: 'topic-rag-2',
        question: 'Why is reranking valuable in RAG?',
        options: [
          'It increases hallucinations but improves speed',
          'It reorders retrieved chunks using a stronger relevance signal',
          'It makes embeddings unnecessary',
          'It replaces the generator model',
        ],
        correct_answer: 'B',
        explanation:
          'Reranking improves precision before the final context is assembled.',
      },
    ],
    agents: [
      {
        id: 'topic-agents-1',
        question: 'What separates an agent from a single-shot prompt?',
        options: [
          'Agents can plan, use tools, observe results, and continue',
          'Agents do not rely on language models',
          'Agents cannot use retrieval',
          'Agents only answer one fixed question',
        ],
        correct_answer: 'A',
        explanation:
          'The planning and tool loop is what makes an agent feel stateful and goal-directed.',
      },
    ],
    evals: [
      {
        id: 'topic-evals-1',
        question: 'Which metric belongs in a production GenAI evaluation suite?',
        options: [
          'Only BLEU score',
          'Groundedness, safety, latency, and task success',
          'Prompt length alone',
          'GPU utilization only',
        ],
        correct_answer: 'B',
        explanation:
          'Production systems need multidimensional evaluation, not a single offline score.',
      },
    ],
  };

  const selected =
    (lower.includes('transformer') && bank.transformer) ||
    (lower.includes('attention') && bank.transformer) ||
    (lower.includes('rag') && bank.rag) ||
    (lower.includes('retrieval') && bank.rag) ||
    (lower.includes('agent') && bank.agents) ||
    (lower.includes('tool') && bank.agents) ||
    (lower.includes('eval') && bank.evals) ||
    bank.transformer;

  return {
    topic: concept.name,
    total: selected.length,
    from_notes: selected.length,
    from_web: 0,
    questions: clone(selected),
  };
};

const createConversation = (title = 'New chat') => {
  const id = `conv-demo-${demoState.counters.conversation++}`;
  const conversation: DemoConversation = {
    id,
    title,
    updated_at: new Date().toISOString(),
    messages: [],
  };
  demoState.conversations.unshift(conversation);
  return conversation;
};

const getConversation = (conversationId: string) =>
  demoState.conversations.find((conversation) => conversation.id === conversationId);

const createAssistantMessagePayload = (message: string, sourceIds?: string[]) => {
  const lower = message.toLowerCase();
  const focusedSources: DemoSource[] | null =
    sourceIds && sourceIds.length > 0
      ? sourceIds.flatMap((id) => {
          const note = demoState.notes.find((item) => item.id === id);
          return note
            ? [
                {
                  id,
                  title: note.title || id,
                  content: note.chunks[0]?.content || note.content_text,
                },
              ]
            : [];
        })
      : null;

  if (lower.includes('rag')) {
    return {
      content:
        '**RAG** is the system pattern this demo treats most seriously. It embeds the query, retrieves semantically related evidence, reranks it, and only then asks the model to answer with explicit grounding.[1]\n\nThat is why the graph clusters **RAG**, **Vector Database**, **Reranking**, and **Hallucinations** together: they are design tradeoffs of the same product loop.[2]',
      sources:
        focusedSources && focusedSources.length > 0
          ? focusedSources
          : [
              {
                id: 'note-rag-playbook',
                title: 'RAG System Design Review',
                content:
                  'RAG improves grounding by retrieving evidence before generation and explicitly linking answers back to sources.',
                images: [conceptArt.rag],
              },
              {
                id: 'book-genai-engineering',
                title: 'Generative AI Engineering Notes',
                content:
                  'Production GenAI depends on retrieval, evaluation, and policy boundaries in addition to model quality.',
              },
            ],
      relatedConcepts: ['RAG', 'Vector Database', 'Reranking', 'Hallucinations'],
      metadata: {
        intent: 'explain',
        entities: ['RAG'],
        documents_retrieved: 2,
        nodes_retrieved: 6,
      },
      title: 'RAG explainer',
    };
  }

  if (lower.includes('agent') || lower.includes('tool')) {
    return {
      content:
        '**Agents** in this demo are not magic autonomous beings. They are LLM loops with three extra ingredients: a goal, access to tools, and a policy for when to stop.[1]\n\nThe product-quality trick is to keep the tool boundary explicit. Use retrieval for evidence, tool calling for structured actions, and evals to verify the loop actually helped.[2]',
      sources: [
        {
          id: 'note-agents',
          title: 'Agents Design Notes',
          content:
            'Agents decide when to retrieve, when to call tools, and when to stop. Evaluation measures whether those choices help.',
        },
        {
          id: 'note-eval-checklist',
          title: 'LLM Evaluation Checklist',
          content:
            'Evaluation has to combine offline benchmarks, rubric review, and telemetry to be production-ready.',
          images: [conceptArt.evals],
        },
      ],
      relatedConcepts: ['Agents', 'Tool Calling', 'Eval Benchmarks'],
      metadata: {
        intent: 'connect',
        entities: ['Agents', 'Tool Calling'],
        documents_retrieved: 2,
        nodes_retrieved: 7,
      },
      title: 'Agent design',
    };
  }

  if (lower.includes('eval') || lower.includes('benchmark') || lower.includes('safety')) {
    return {
      content:
        'A serious GenAI system needs **three layers of evaluation**:\n\n- Offline benchmark tasks for repeatable regression checks.\n- Human review for nuance, style, and edge cases.\n- Production telemetry for latency, failures, and real user behavior.[1]\n\nThat layered loop is what turns isolated model demos into maintainable products.[2]',
      sources: [
        {
          id: 'note-eval-checklist',
          title: 'LLM Evaluation Checklist',
          content:
            'Benchmarks alone are not enough; you also need rubric review and live telemetry.',
          images: [conceptArt.evals],
        },
        {
          id: 'book-genai-engineering',
          title: 'Generative AI Engineering Notes',
          content:
            'Production GenAI requires observability, rollout discipline, and feedback loops around the core model.',
        },
      ],
      relatedConcepts: ['Eval Benchmarks', 'Safety Guardrails', 'Hallucinations'],
      metadata: {
        intent: 'path',
        entities: ['Eval Benchmarks'],
        documents_retrieved: 2,
        nodes_retrieved: 6,
      },
      title: 'Evaluation plan',
    };
  }

  if (lower.includes('alignment') || lower.includes('rlhf') || lower.includes('hallucination')) {
    return {
      content:
        '**RLHF** and **Safety Guardrails** solve related but different problems. RLHF changes the base behavior of the model, while guardrails constrain behavior at runtime. For hallucinations, the demo emphasizes system-level grounding with RAG and evals, not just alignment alone.[1]\n\nThat is why the alignment cluster in the graph connects back into retrieval and evaluation instead of living as an isolated “safety island.”[2]',
      sources: [
        {
          id: 'note-rlhf',
          title: 'RLHF Design Notes',
          content:
            'RLHF trains a reward model from preference data and optimizes the policy toward preferred outputs.',
        },
        {
          id: 'note-rag-playbook',
          title: 'RAG System Design Review',
          content:
            'Grounding with retrieval is a practical way to reduce unsupported claims in production systems.',
          images: [conceptArt.rag],
        },
      ],
      relatedConcepts: ['RLHF', 'Safety Guardrails', 'Hallucinations', 'RAG'],
      metadata: {
        intent: 'summarize',
        entities: ['RLHF', 'Hallucinations'],
        documents_retrieved: 2,
        nodes_retrieved: 7,
      },
      title: 'Alignment summary',
    };
  }

  return {
    content:
      'This demo workspace was built around **NLP**, **LLMs**, and **Generative AI** topics. The strongest paths right now are:\n\n- **Transformer -> Decoder-Only LLM -> In-Context Learning**\n- **Embeddings -> Vector Database -> RAG**\n- **Prompt Engineering -> Tool Calling -> Agents**\n- **Hallucinations -> Eval Benchmarks -> Safety Guardrails**\n\nAsk for an explanation, a learning path, or a quiz on any of those threads and the UI will stay fully local and visual.',
    sources: [
      {
        id: 'book-genai-engineering',
        title: 'Generative AI Engineering Notes',
        content:
          'Field notes on turning LLMs into production systems with retrieval, evaluation, and control layers.',
      },
    ],
    relatedConcepts: ['Transformer', 'RAG', 'Agents', 'Eval Benchmarks'],
    metadata: {
      intent: 'general',
      entities: ['Transformer', 'RAG', 'Agents'],
      documents_retrieved: 1,
      nodes_retrieved: 4,
    },
    title: 'Demo workspace overview',
  };
};

const extractConceptsFromContent = (content: string) => {
  const lower = content.toLowerCase();
  const matches = DEMO_CONCEPTS.filter(
    (concept) =>
      lower.includes(concept.name.toLowerCase()) ||
      concept.name
        .toLowerCase()
        .split(' ')
        .some((token) => token.length > 4 && lower.includes(token)),
  );
  return matches.slice(0, 5).length > 0 ? matches.slice(0, 5) : DEMO_CONCEPTS.slice(0, 4);
};

const appendConversationMessage = (
  conversationId: string,
  message: DemoConversationMessage,
  titleHint?: string,
) => {
  const conversation = getConversation(conversationId) || createConversation(titleHint || 'New chat');
  conversation.messages.push(message);
  conversation.updated_at = new Date().toISOString();
  if (conversation.messages.length === 1 && titleHint) {
    conversation.title = titleHint;
  }
};

const saveConversationAsKnowledge = (conversationId: string) => {
  const conversation = getConversation(conversationId);
  if (!conversation) return;

  const noteId = `note-chat-${demoState.counters.note++}`;
  const note: DemoNote = {
    id: noteId,
    title: `${conversation.title} - Saved Conversation`,
    resource_type: 'chat_transcript',
    created_at: new Date().toISOString(),
    preview: conversation.messages
      .filter((message) => message.role === 'assistant')
      .map((message) => message.content)
      .join(' ')
      .slice(0, 180),
    content_text: conversation.messages
      .map((message) => `${message.role === 'assistant' ? 'Assistant' : 'User'}: ${message.content}`)
      .join('\n\n'),
    chunks: [
      {
        id: `${noteId}-chunk-1`,
        chunk_level: 'conversation',
        chunk_index: 0,
        images: [],
        content: conversation.messages
          .map((message) => `${message.role === 'assistant' ? 'Assistant' : 'User'}: ${message.content}`)
          .join('\n\n'),
      },
    ],
  };

  demoState.notes.unshift(note);
};

const mergeConceptIds = (sourceIds: string[], targetId: string) => {
  const target = demoState.graph.nodes.find((node) => node.id === targetId);
  if (!target) return;

  demoState.graph.nodes = demoState.graph.nodes.filter((node) => !sourceIds.includes(node.id));
  demoState.graph.edges = demoState.graph.edges
    .map((edge) => ({
      ...edge,
      source: sourceIds.includes(edge.source) ? targetId : edge.source,
      target: sourceIds.includes(edge.target) ? targetId : edge.target,
    }))
    .filter((edge) => edge.source !== edge.target);

  demoState.graph.communities = demoState.graph.communities.map((community) => ({
    ...community,
    entity_ids: community.entity_ids
      .filter((id: string) => !sourceIds.includes(id))
      .concat(community.entity_ids.includes(targetId) ? [] : [targetId]),
  }));
};

const buildNotesListResponse = (resourceType?: string) => ({
  notes: clone(
    demoState.notes.filter((note) => (resourceType ? note.resource_type === resourceType : true)),
  ).map((note) => ({
    id: note.id,
    title: note.title,
    content_text: note.content_text,
    resource_type: note.resource_type,
    created_at: note.created_at,
  })),
});

const findMessageById = (messageId: string) => {
  for (const conversation of demoState.conversations) {
    const message = conversation.messages.find((item) => item.id === messageId);
    if (message) return { conversation, message };
  }
  return null;
};

export const getDemoInitialChatMessages = () =>
  clone(buildConversations()[0].messages.map(mapConversationMessageToChat));

export async function streamDemoTopicQuiz(params: DemoQuizStreamParams) {
  try {
    params.onStatus('Scanning your knowledge graph...');
    await wait(350);
    params.onStatus('Selecting quiz candidates from NLP / LLM topics...');
    await wait(450);
    params.onStatus('Formatting answers for the active recall feed...');
    await wait(300);
    params.onDone(buildQuizPayload(params.topic));
  } catch (error) {
    params.onError(error instanceof Error ? error.message : 'Quiz demo failed');
  }
}

export async function streamDemoChat(params: DemoChatStreamParams) {
  try {
    const userMessageId = `msg-demo-${demoState.counters.message++}`;
    appendConversationMessage(params.conversationId, {
      id: userMessageId,
      role: 'user',
      content: params.message,
    }, params.message.slice(0, 40));

    const reply = createAssistantMessagePayload(params.message, params.sourceIds);
    const assistantMessageId = `msg-demo-${demoState.counters.message++}`;

    params.onStatus('Tracing concepts in the demo knowledge graph...');
    await wait(250);
    params.onStatus('Synthesising grounded answer...');
    await wait(300);

    const chunks = reply.content.split(' ');
    let running = '';
    for (const chunk of chunks) {
      running += `${chunk} `;
      params.onChunk(`${chunk} `);
      await wait(18);
    }

    appendConversationMessage(params.conversationId, {
      id: assistantMessageId,
      role: 'assistant',
      content: running.trim(),
      sources: reply.sources,
      relatedConcepts: reply.relatedConcepts,
      metadata: reply.metadata,
    }, reply.title);

    params.onDone({
      conversation_id: params.conversationId,
      message_id: assistantMessageId,
      sources: reply.sources,
      related_concepts: reply.relatedConcepts.map((name) => ({ id: slugify(name), name })),
      metadata: reply.metadata,
    });
  } catch (error) {
    params.onError(error instanceof Error ? error.message : 'Chat demo failed');
  }
}

async function parseJsonBody(options?: RequestInit) {
  if (!options?.body || typeof options.body !== 'string') return {};
  try {
    return JSON.parse(options.body);
  } catch {
    return {};
  }
}

function buildGraphSlice(limit: number, offset: number) {
  return {
    nodes: clone(demoState.graph.nodes.slice(offset, offset + limit)),
    edges: clone(demoState.graph.edges),
    communities: clone(demoState.graph.communities),
  };
}

export async function handleDemoRequest(url: string, options: RequestInit = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const parsed = new URL(url, 'http://demo.graphrecall.local');
  const path = parsed.pathname;

  if (path === '/health' || path === '/health/live') {
    return jsonResponse({
      status: 'healthy',
      postgres: { status: 'healthy', database: 'postgresql', connected: true },
      neo4j: { status: 'healthy', database: 'neo4j', connected: true },
      version: 'demo-ui',
    });
  }

  if ((path === '/auth/google' || path === '/api/auth/google') && method === 'POST') {
    return jsonResponse({
      status: 'success',
      user: {
        ...demoState.user,
        profile_picture: demoState.user.picture,
      },
      token: 'demo-id-token',
    });
  }

  if ((path === '/auth/profile' || path === '/api/auth/profile') && method === 'PATCH') {
    const body = await parseJsonBody(options);
    demoState.settings = {
      ...demoState.settings,
      ...(body.settings || {}),
    };
    demoState.user.settings_json = clone(demoState.settings);
    return jsonResponse({ status: 'success' });
  }

  if (path === '/api/feed' && method === 'GET') return jsonResponse(buildFeedResponse());
  if (path === '/api/feed/stats' && method === 'GET') return jsonResponse(buildStatsResponse());
  if (path === '/api/feed/schedule' && method === 'GET') return jsonResponse(clone(demoState.schedule));
  if (path === '/api/feed/history/quizzes' && method === 'GET') {
    return jsonResponse({ quizzes: clone(demoState.quizHistory) });
  }
  if (path === '/api/feed/saved' && method === 'GET') {
    return jsonResponse({ items: buildSavedItems() });
  }
  if (path === '/api/feed/due-count' && method === 'GET') {
    return jsonResponse({ due_count: demoState.feedItems.length });
  }
  if (path === '/api/feed/review' && method === 'POST') {
    demoState.completedToday += 1;
    demoState.accuracyRate = Math.min(0.96, demoState.accuracyRate + 0.0025);
    return jsonResponse({ status: 'success' });
  }

  const likeMatch = path.match(/^\/api\/feed\/([^/]+)\/like$/);
  if (likeMatch && method === 'POST') {
    const id = decodeURIComponent(likeMatch[1]);
    const isLiked = demoState.likedItemIds.has(id);
    if (isLiked) demoState.likedItemIds.delete(id);
    else demoState.likedItemIds.add(id);
    return jsonResponse({ is_liked: !isLiked });
  }

  const saveMatch = path.match(/^\/api\/feed\/([^/]+)\/save$/);
  if (saveMatch && method === 'POST') {
    const id = decodeURIComponent(saveMatch[1]);
    const isSaved = demoState.savedItemIds.has(id);
    if (isSaved) demoState.savedItemIds.delete(id);
    else demoState.savedItemIds.add(id);
    return jsonResponse({ is_saved: !isSaved });
  }

  const quizTopicMatch = path.match(/^\/api\/feed\/quiz\/topic\/(.+)$/);
  if (quizTopicMatch && method === 'POST') {
    const topic = decodeURIComponent(quizTopicMatch[1]);
    return jsonResponse(buildQuizPayload(topic));
  }

  const resourcesMatch = path.match(/^\/api\/feed\/resources\/(.+)$/);
  if (resourcesMatch && method === 'GET') {
    const topic = decodeURIComponent(resourcesMatch[1]).toLowerCase();
    return jsonResponse({ resources: clone(resourcesByTopic.get(topic) || []) });
  }

  if (path === '/api/graph3d' && method === 'GET') {
    const limit = Number(parsed.searchParams.get('limit') || 200);
    const offset = Number(parsed.searchParams.get('offset') || 0);
    return jsonResponse(buildGraphSlice(limit, offset));
  }

  const focusMatch = path.match(/^\/api\/graph3d\/focus\/(.+)$/);
  if (focusMatch && method === 'GET') {
    const conceptId = decodeURIComponent(focusMatch[1]);
    const neighborIds = new Set<string>([conceptId]);
    for (const edge of demoState.graph.edges) {
      if (edge.source === conceptId) neighborIds.add(edge.target);
      if (edge.target === conceptId) neighborIds.add(edge.source);
    }
    return jsonResponse({
      nodes: clone(demoState.graph.nodes.filter((node) => neighborIds.has(node.id))),
      edges: clone(
        demoState.graph.edges.filter(
          (edge) => neighborIds.has(edge.source) && neighborIds.has(edge.target),
        ),
      ),
      communities: clone(demoState.graph.communities),
    });
  }

  if (path === '/api/graph3d/communities/recompute' && method === 'POST') {
    return jsonResponse({ status: 'recomputed' });
  }

  if (path === '/api/chat' && method === 'POST') {
    const body = await parseJsonBody(options);
    const reply = createAssistantMessagePayload(body.message || '');
    return jsonResponse({
      response: reply.content,
      sources: reply.sources?.map((source) => ({ id: source.id, title: source.title })),
      related_concepts: reply.relatedConcepts?.map((name) => ({ id: slugify(name), name })),
    });
  }

  if (path === '/api/chat/history' && method === 'GET') {
    return jsonResponse({
      conversations: demoState.conversations.map((conversation) => ({
        id: conversation.id,
        title: conversation.title,
        updated_at: conversation.updated_at,
        message_count: conversation.messages.length,
      })),
    });
  }

  if (path === '/api/chat/conversations' && method === 'POST') {
    const conversation = createConversation('Untitled demo chat');
    return jsonResponse({ conversation_id: conversation.id });
  }

  const conversationMatch = path.match(/^\/api\/chat\/conversations\/([^/]+)$/);
  if (conversationMatch && method === 'GET') {
    const conversationId = decodeURIComponent(conversationMatch[1]);
    const conversation = getConversation(conversationId);
    if (!conversation) return jsonResponse({ detail: 'Conversation not found' }, 404);
    return jsonResponse({
      messages: conversation.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        sources_json: message.sources || [],
      })),
    });
  }

  const conversationToKnowledgeMatch = path.match(
    /^\/api\/chat\/conversations\/([^/]+)\/to-knowledge$/,
  );
  if (conversationToKnowledgeMatch && method === 'POST') {
    saveConversationAsKnowledge(decodeURIComponent(conversationToKnowledgeMatch[1]));
    return jsonResponse({ status: 'success' });
  }

  const saveMessageMatch = path.match(/^\/api\/chat\/messages\/([^/]+)\/save$/);
  if (saveMessageMatch && method === 'POST') {
    return jsonResponse({ status: 'saved' });
  }

  const createCardMatch = path.match(/^\/api\/chat\/messages\/([^/]+)\/create-card$/);
  if (createCardMatch && method === 'POST') {
    const body = await parseJsonBody(options);
    const lookup = findMessageById(decodeURIComponent(createCardMatch[1]));
    const content = lookup?.message.content || 'Demo card content';
    if (body.output_type === 'concept_card') {
      const card = {
        id: `card-demo-${demoState.counters.card++}`,
        type: 'flashcard',
        topic: lookup?.conversation.title || 'LLM Concept',
        back_content: content.slice(0, 240),
      };
      demoState.feedItems.unshift({
        id: card.id,
        item_type: 'flashcard',
        concept_id: 'prompt-engineering',
        concept_name: card.topic,
        domain: 'Generative AI',
        created_at: new Date().toISOString(),
        content: {
          definition: card.back_content,
          back: card.back_content,
          complexity: 5,
          prerequisites: [],
          related_concepts: ['Prompt Engineering', 'In-Context Learning'],
          mastery: 55,
        },
      });
      return jsonResponse(card);
    }
    const quiz = {
      id: `card-demo-${demoState.counters.card++}`,
      question_text: 'Which project pattern best improves grounded LLM answers?',
      options: [
        { id: 'A', text: 'Longer random prompts', is_correct: false },
        { id: 'B', text: 'Retrieval plus citations', is_correct: true },
        { id: 'C', text: 'Removing evals', is_correct: false },
        { id: 'D', text: 'Disabling tool calls', is_correct: false },
      ],
      explanation:
        'The demo repeatedly emphasizes grounding with retrieval and evidence rather than relying on model confidence.',
      topic: lookup?.conversation.title || 'RAG',
    };
    demoState.quizHistory.unshift({
      id: quiz.id,
      topic: quiz.topic,
      question_type: 'mcq',
      question_text: quiz.question_text,
      options: quiz.options.map((option) => option.text),
      correct_answer: 'B',
      explanation: quiz.explanation,
    });
    return jsonResponse(quiz);
  }

  if (path === '/api/notes' && method === 'GET') {
    const resourceType = parsed.searchParams.get('resource_type') || undefined;
    return jsonResponse(buildNotesListResponse(resourceType));
  }

  const deleteNoteMatch = path.match(/^\/api\/notes\/([^/]+)$/);
  if (deleteNoteMatch && method === 'DELETE') {
    const noteId = decodeURIComponent(deleteNoteMatch[1]);
    demoState.notes = demoState.notes.filter((note) => note.id !== noteId);
    return jsonResponse({ status: 'deleted' });
  }

  if (path === '/api/uploads' && method === 'GET') {
    return jsonResponse({ uploads: clone(demoState.uploads) });
  }

  if (path === '/api/uploads' && method === 'POST' && options.body instanceof FormData) {
    const file = options.body.get('file') as File | null;
    const uploadType = String(options.body.get('upload_type') || 'screenshot');
    const title = String(options.body.get('title') || file?.name || 'Demo upload');
    const description = String(
      options.body.get('description') || 'Uploaded in demo mode for the multimodal create flow.',
    );
    const fileUrl = file ? URL.createObjectURL(file) : conceptArt.transformer;
    const upload: DemoUpload = {
      id: `upload-demo-${demoState.counters.upload++}`,
      upload_type: uploadType,
      file_url: fileUrl,
      thumbnail_url: fileUrl,
      title,
      description,
      created_at: new Date().toISOString(),
    };
    demoState.uploads.unshift(upload);
    demoState.feedItems.unshift({
      id: `feed-upload-${upload.id}`,
      item_type: 'screenshot',
      concept_id: 'rag',
      concept_name: 'Retrieval-Augmented Generation',
      domain: 'Retrieval & Agents',
      created_at: upload.created_at,
      content: {
        file_url: upload.file_url,
        thumbnail_url: upload.thumbnail_url || upload.file_url,
        title: upload.title || 'Demo upload',
        description: upload.description || 'Uploaded in demo mode.',
        linked_concepts: ['RAG'],
      },
    });
    return jsonResponse({ upload });
  }

  const deleteUploadMatch = path.match(/^\/api\/uploads\/([^/]+)$/);
  if (deleteUploadMatch && method === 'DELETE') {
    const uploadId = decodeURIComponent(deleteUploadMatch[1]);
    demoState.uploads = demoState.uploads.filter((upload) => upload.id !== uploadId);
    return jsonResponse({ status: 'deleted' });
  }

  if (path === '/api/concepts/merge' && method === 'POST') {
    const body = await parseJsonBody(options);
    mergeConceptIds(body.source_ids || [], body.target_id);
    return jsonResponse({ status: 'merged' });
  }

  const conceptNotesMatch = path.match(/^\/api\/concepts\/([^/]+)\/notes$/);
  if (conceptNotesMatch && method === 'GET') {
    const conceptId = decodeURIComponent(conceptNotesMatch[1]);
    return jsonResponse({
      notes: clone(notesByConceptId.get(conceptId) || []),
    });
  }

  const deleteConceptMatch = path.match(/^\/api\/concepts\/([^/]+)$/);
  if (deleteConceptMatch && method === 'DELETE') {
    const conceptId = decodeURIComponent(deleteConceptMatch[1]);
    demoState.graph.nodes = demoState.graph.nodes.filter((node) => node.id !== conceptId);
    demoState.graph.edges = demoState.graph.edges.filter(
      (edge) => edge.source !== conceptId && edge.target !== conceptId,
    );
    return jsonResponse({ status: 'deleted' });
  }

  if (path === '/api/concepts/backfill-embeddings' && method === 'POST') {
    return jsonResponse({ status: 'queued', processed: demoState.graph.nodes.length });
  }

  if (path === '/api/nodes' && method === 'POST') {
    const body = await parseJsonBody(options);
    const newId = `demo-node-${demoState.counters.node++}`;
    const domain = body.domain || 'Generative AI';
    const node = {
      id: newId,
      name: body.name || 'New Demo Node',
      definition:
        body.description ||
        'A new concept created in demo mode to show manual graph editing.',
      domain,
      complexity_score: 5,
      mastery: 42,
      color: DOMAIN_COLORS[domain] || '#A3A3A3',
      size: 1.5,
    };
    demoState.graph.nodes.push(node);
    if (body.parent_concept_id) {
      demoState.graph.edges.push({
        id: `${body.parent_concept_id}->${newId}:SUBTOPIC_OF`,
        source: newId,
        target: body.parent_concept_id,
        relationship_type: 'SUBTOPIC_OF',
        strength: 0.84,
      });
    }
    const hasDomainCommunity = demoState.graph.communities.some((community) => community.title === domain);
    demoState.graph.communities = hasDomainCommunity
      ? demoState.graph.communities.map((community) => {
          if (community.title === domain) {
            return {
              ...community,
              entity_ids: community.entity_ids.includes(newId)
                ? community.entity_ids
                : [...community.entity_ids, newId],
              size: community.entity_ids.includes(newId) ? community.size : community.size + 1,
            };
          }
          return community;
        })
      : [
          ...demoState.graph.communities,
          {
            id: `community-${slugify(domain)}`,
            title: domain,
            level: 0,
            children: [],
            entity_ids: [newId],
            size: 1,
            computedColor: DOMAIN_COLORS[domain] || '#95a5a6',
            order: demoState.graph.communities.length,
          },
        ];
    notesByConceptId.set(newId, [
      {
        id: `note-${newId}`,
        title: `${node.name} Design Notes`,
        resource_type: 'note',
        created_at: new Date().toISOString(),
        preview: node.definition,
        content_text: node.definition,
        chunks: [
          {
            id: `note-${newId}-chunk-1`,
            chunk_level: 'section',
            chunk_index: 0,
            images: [],
            content:
              `**${node.name}** was created in demo mode to showcase manual graph expansion.\n\n${node.definition}`,
          },
        ],
      },
    ]);
    return jsonResponse({ node });
  }

  const suggestLinksMatch = path.match(/^\/api\/nodes\/([^/]+)\/suggest-links$/);
  if (suggestLinksMatch && method === 'POST') {
    const nodeId = decodeURIComponent(suggestLinksMatch[1]);
    const node = demoState.graph.nodes.find((item) => item.id === nodeId);
    const concept = lookupConceptByTopic(node?.name || 'Prompt Engineering');
    return jsonResponse({
      links: [
        {
          target_id: concept.id,
          target_name: concept.name,
          relationship_type: 'RELATED_TO',
          strength: 0.72,
          reason: 'The node name overlaps with the strongest nearby demo concept.',
        },
        {
          target_id: 'rag',
          target_name: 'Retrieval-Augmented Generation',
          relationship_type: 'RELATED_TO',
          strength: 0.64,
          reason: 'Most GenAI workflows in this demo eventually connect back to retrieval and grounding.',
        },
      ],
    });
  }

  const applyLinksMatch = path.match(/^\/api\/nodes\/([^/]+)\/link$/);
  if (applyLinksMatch && method === 'POST') {
    const nodeId = decodeURIComponent(applyLinksMatch[1]);
    const body = await parseJsonBody(options);
    for (const link of body.links || []) {
      demoState.graph.edges.push({
        id: `${nodeId}->${link.target_id}:${link.relationship_type}`,
        source: nodeId,
        target: link.target_id,
        relationship_type: link.relationship_type,
        strength: link.strength || 0.65,
      });
    }
    return jsonResponse({ status: 'linked' });
  }

  if (path === '/api/v2/health' && method === 'GET') {
    return jsonResponse({
      status: 'healthy',
      demo_mode: true,
      available_modalities: ['notes', 'pdf', 'images', 'youtube', 'chat-transcript', 'processed-zip'],
    });
  }

  if (path === '/api/v2/ingest' && method === 'POST') {
    const body = await parseJsonBody(options);
    const content = String(body.content || '');
    const title = String(body.title || 'Demo Knowledge Note');
    const concepts = extractConceptsFromContent(content);
    const threadId = `thread-demo-${demoState.counters.thread++}`;
    demoState.ingestionSessions[threadId] = {
      thread_id: threadId,
      mode: 'review',
      title,
      content,
      created_at: new Date().toISOString(),
      poll_count: 0,
      approved_concepts: concepts,
    };
    return jsonResponse({
      thread_id: threadId,
      status: 'awaiting_review',
      synthesis_decisions: concepts.map((concept) => ({
        new_concept: {
          name: concept.name,
          definition: concept.definition,
          domain: concept.domain,
          complexity_score: concept.complexity,
        },
        matches: [],
        recommended_action: 'create',
      })),
      processing_metadata: {
        concepts_extracted: concepts.length,
        domains_detected: [...new Set(concepts.map((concept) => concept.domain))],
        concept_names: concepts.map((concept) => concept.name),
        avg_complexity:
          concepts.reduce((total, concept) => total + concept.complexity, 0) / concepts.length,
      },
    });
  }

  const approveMatch = path.match(/^\/api\/v2\/ingest\/([^/]+)\/approve$/);
  if (approveMatch && method === 'POST') {
    const threadId = decodeURIComponent(approveMatch[1]);
    const session = demoState.ingestionSessions[threadId];
    if (!session) return jsonResponse({ detail: 'Thread not found' }, 404);
    const noteId = `note-demo-${demoState.counters.note++}`;
    const note: DemoNote = {
      id: noteId,
      title: session.title,
      resource_type: 'note',
      created_at: new Date().toISOString(),
      preview: session.content.slice(0, 160),
      content_text: session.content,
      chunks: [
        {
          id: `${noteId}-chunk-1`,
          chunk_level: 'section',
          chunk_index: 0,
          images: [],
          content: session.content,
        },
      ],
    };
    demoState.notes.unshift(note);
    return jsonResponse({ status: 'completed', note_id: noteId, thread_id: threadId });
  }

  if (path === '/api/v2/ingest/url' && method === 'POST') {
    const body = await parseJsonBody(options);
    const title = `Article - ${String(body.url || 'Demo URL')}`;
    demoState.notes.unshift({
      id: `note-demo-${demoState.counters.note++}`,
      title,
      resource_type: 'article',
      created_at: new Date().toISOString(),
      preview: 'A stored article resource used to demonstrate the URL ingestion path in UI-only mode.',
      source_url: body.url,
      content_text:
        'This article was added in demo mode to show the ingestion success state without a live backend.',
      chunks: [
        {
          id: `${title}-chunk-1`,
          chunk_level: 'section',
          chunk_index: 0,
          images: [],
          content:
            'This stored article demonstrates the create-screen URL flow for GenAI and NLP reading material.',
        },
      ],
    });
    return jsonResponse({
      status: 'completed',
      thread_id: `thread-demo-${demoState.counters.thread++}`,
      processing_metadata: {
        concepts_extracted: 3,
        concept_names: ['RAG', 'Agents', 'Eval Benchmarks'],
      },
    });
  }

  if (path === '/api/v2/ingest/youtube' && method === 'POST') {
    const body = await parseJsonBody(options);
    demoState.notes.unshift({
      id: `note-demo-${demoState.counters.note++}`,
      title: 'YouTube Resource',
      resource_type: 'youtube',
      created_at: new Date().toISOString(),
      preview: 'A saved YouTube link to demonstrate multimodal resource storage.',
      source_url: body.url,
      content_text: `Saved YouTube link: ${body.url}`,
      chunks: [
        {
          id: `note-youtube-${demoState.counters.note}`,
          chunk_level: 'resource',
          chunk_index: 0,
          images: [],
          content: `Saved YouTube link for later study: ${body.url}`,
        },
      ],
    });
    return jsonResponse({ status: 'stored' });
  }

  if (path === '/api/v2/ingest/chat-transcript' && method === 'POST') {
    const body = await parseJsonBody(options);
    demoState.notes.unshift({
      id: `note-demo-${demoState.counters.note++}`,
      title: 'Imported Chat Transcript',
      resource_type: 'chat_transcript',
      created_at: new Date().toISOString(),
      preview: 'Imported transcript demonstrating chat-to-knowledge flow.',
      content_text: body.content || '',
      chunks: [
        {
          id: `note-chat-${demoState.counters.note}`,
          chunk_level: 'conversation',
          chunk_index: 0,
          images: [],
          content: body.content || '',
        },
      ],
    });
    return jsonResponse({
      status: 'completed',
      processing_metadata: {
        concepts_extracted: 4,
        concept_names: ['Prompt Engineering', 'Tool Calling', 'Agents', 'Eval Benchmarks'],
      },
    });
  }

  if (path === '/api/v2/ingest/processed-zip' && method === 'POST' && options.body instanceof FormData) {
    const file = options.body.get('file') as File | null;
    const title = String(options.body.get('title') || file?.name || 'Processed ZIP Demo');
    const threadId = `thread-demo-${demoState.counters.thread++}`;
    demoState.ingestionSessions[threadId] = {
      thread_id: threadId,
      mode: 'background',
      title,
      content:
        'Processed ZIP demo ingest containing textbook-like chunks on NLP, LLM architecture, and evaluation.',
      created_at: new Date().toISOString(),
      poll_count: 0,
      approved_concepts: DEMO_CONCEPTS.slice(0, 6),
    };
    return jsonResponse({ thread_id: threadId, status: 'queued' });
  }

  const statusMatch = path.match(/^\/api\/v2\/ingest\/([^/]+)\/status$/);
  if (statusMatch && method === 'GET') {
    const threadId = decodeURIComponent(statusMatch[1]);
    const session = demoState.ingestionSessions[threadId];
    if (!session) return jsonResponse({ status: 'not_found' });
    session.poll_count += 1;
    if (session.mode === 'background') {
      if (session.poll_count >= 3) {
        demoState.notes.unshift({
          id: `note-demo-${demoState.counters.note++}`,
          title: session.title,
          resource_type: 'book',
          created_at: new Date().toISOString(),
          preview: 'Background-processed book ingest for the demo library.',
          content_text: session.content,
          chunks: [
            {
              id: `${session.title}-chunk-1`,
              chunk_level: 'chapter',
              chunk_index: 0,
              images: [conceptArt.transformer],
              content: session.content,
            },
          ],
        });
        session.mode = 'complete';
        return jsonResponse({
          status: 'completed',
          stage: 'complete',
          progress: {
            completed_nodes: ['extract', 'chunk', 'save_chunks'],
            chunk_save_total: 24,
            chunk_save_done: 24,
          },
        });
      }
      return jsonResponse({
        status: 'processing',
        stage: session.poll_count === 1 ? 'chunking' : 'save_chunks',
        progress: {
          completed_nodes: session.poll_count === 1 ? ['extract'] : ['extract', 'chunk'],
          chunk_save_total: 24,
          chunk_save_done: session.poll_count === 1 ? 8 : 18,
          chunk_save_stage: 'persisting book chunks',
        },
      });
    }
    return jsonResponse({
      status: 'awaiting_review',
      stage: 'review',
      synthesis_decisions: session.approved_concepts.map((concept) => ({
        new_concept: {
          name: concept.name,
          definition: concept.definition,
          domain: concept.domain,
          complexity_score: concept.complexity,
        },
        matches: [],
        recommended_action: 'create',
      })),
      progress: {
        completed_nodes: ['extract'],
      },
    });
  }

  const eventsMatch = path.match(/^\/api\/v2\/ingest\/([^/]+)\/events$/);
  if (eventsMatch && method === 'GET') {
    const threadId = decodeURIComponent(eventsMatch[1]);
    const session = demoState.ingestionSessions[threadId];
    if (!session) return jsonResponse({ events: [] });
    const events =
      session.mode === 'background'
        ? [
            {
              timestamp: isoDaysAgo(0),
              level: 'info',
              message: 'Queued processed ZIP for background ingestion',
            },
            {
              timestamp: isoDaysAgo(0),
              level: 'info',
              message: 'Extracted textbook chunks on NLP, LLMs, and evaluation',
            },
            {
              timestamp: isoDaysAgo(0),
              level: 'info',
              message: 'Persisting book chunks and image metadata',
            },
          ]
        : [
            {
              timestamp: isoDaysAgo(0),
              level: 'info',
              message: 'Concept candidates ready for review',
            },
          ];
    return jsonResponse({ events });
  }

  if (path === '/api/users/me/purge' && method === 'DELETE') {
    demoState = createDemoState();
    return jsonResponse({ status: 'reset' });
  }

  return jsonResponse(
    {
      detail: `Demo backend has no route for ${method} ${path}`,
    },
    404,
  );
}
