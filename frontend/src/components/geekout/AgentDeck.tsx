import React, { useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import { AgentCard, type AgentInfo } from './AgentCard';
import { X } from 'lucide-react';

// Hardcoded Geeky Data
const AGENTS_DATA: AgentInfo[] = [
    {
        id: 'supervisor',
        name: 'Supervisor',
        role: 'The Orchestrator',
        description: 'Routes incoming requests to the most appropriate specialist agent based on intent analysis and task complexity. Manages multi-step workflows.',
        model: 'LangGraph + Gemini 2.5',
        rarity: 'legendary',
        number: '000',
        commitSha: '77c19e6',
        createdDate: 'Feb 3, 2026',
        imageFilename: 'frosted_card_bg_5_supervisor_1770134893540.png',
        tools: ['LangGraph', 'State Management'],
        databases: [],
        context: ['User Intent', 'Workflow State'],
        isRAG: false
    },
    {
        id: 'scanner',
        name: 'Scanner',
        role: 'File Watcher',
        description: 'Monitors uploaded files (PDFs, images, documents) and automatically extracts key concepts, generating quiz questions from the content.',
        model: 'Watchdog API',
        rarity: 'rare',
        number: '008',
        commitSha: '39ab1ea',
        createdDate: 'Feb 3, 2026',
        imageFilename: 'frosted_card_bg_9_scanner_1770134996986.png',
        tools: ['File System Events', 'Hash Check'],
        databases: [],
        context: ['Local Directories', 'File Metadata'],
        isRAG: false
    },
    {
        id: 'matchmaker',
        name: 'Matchmaker',
        role: 'Graph Linker',
        description: 'Traverses your knowledge graph to discover implicit connections between concepts, suggesting relationships you may have missed.',
        model: 'Gemini 2.5 Flash',
        rarity: 'rare',
        number: '009',
        commitSha: '77c19e6',
        createdDate: 'Feb 3, 2026',
        imageFilename: 'frosted_card_bg_7_matchmaker_1770134942667.png',
        tools: ['Graph Traversal', 'Semantic Check'],
        databases: ['Neo4j'],
        context: ['Graph Structure', 'Concept Nodes'],
        isRAG: false
    },
    {
        id: 'librarian',
        name: 'Librarian',
        role: 'Knowledge Keeper',
        description: 'Retrieves relevant context from your notes and knowledge graph using vector search and graph queries to answer questions accurately.',
        model: 'Gemini 2.5 Flash',
        rarity: 'legendary',
        number: '005',
        commitSha: '0dea645',
        createdDate: 'Jan 30, 2026',
        imageFilename: 'frosted_card_bg_10_librarian_1770135034314.png',
        tools: ['Vector Search', 'Graph Cypher'],
        databases: ['Neo4j', 'Postgres'],
        context: ['Knowledge Graph', 'Notes', 'Chat History'],
        isRAG: true
    },
    {
        id: 'detective',
        name: 'Sherlock',
        role: 'Intent Analyst',
        description: 'Analyzes your message to determine intent -- whether you need a quiz, summary, explanation, or fact lookup -- and structures the request accordingly.',
        model: 'Gemini 2.5 Flash',
        rarity: 'uncommon',
        number: '006',
        commitSha: 'fb03b97',
        createdDate: 'Jan 31, 2026',
        imageFilename: 'frosted_card_bg_6_detective_1770134917329.png',
        tools: ['Reasoning Engine', 'Intent Classifier'],
        databases: [],
        context: ['User Query', 'Conversation Context'],
        isRAG: false
    },
    {
        id: 'quiz',
        name: 'Quiz Master',
        role: 'Web Explorer',
        description: 'Searches the web via Tavily to find relevant quiz questions and supplementary material on topics you are studying.',
        model: 'Gemini 2.5 + Tavily',
        rarity: 'rare',
        number: '007',
        commitSha: 'f248ca3',
        createdDate: 'Feb 2, 2026',
        imageFilename: 'frosted_card_bg_3_1770134221369.png',
        tools: ['Tavily Search', 'Curriculum Gen'],
        databases: ['Postgres Cache'],
        context: ['Web Search Results', 'External Data'],
        isRAG: false
    },
    {
        id: 'mermaid',
        name: 'Architect',
        role: 'Visualizer',
        description: 'Generates structured visual diagrams (flowcharts, mind maps, concept maps) from your notes using Mermaid.js syntax.',
        model: 'Gemini 2.5 Flash',
        rarity: 'rare',
        number: '003',
        commitSha: '0dea645',
        createdDate: 'Jan 30, 2026',
        imageFilename: 'frosted_card_bg_4_1770134241935.png',
        tools: ['Mermaid.js', 'Flowchart Gen'],
        databases: [],
        context: ['Concept Relationships', 'Process Flows'],
        isRAG: false
    },
    {
        id: 'content',
        name: 'Artist',
        role: 'Content Engine',
        description: 'Generates diverse study content: term cards, multiple-choice questions, fill-in-the-blank exercises, and concept showcases from your knowledge base.',
        model: 'Gemini 2.5 Flash',
        rarity: 'common',
        number: '004',
        commitSha: '0dea645',
        createdDate: 'Jan 30, 2026',
        imageFilename: 'frosted_card_bg_1_1770134176619.png',
        tools: ['JSON Parser', 'Term Card Gen'],
        databases: ['Postgres'],
        context: ['Concept Definitions', 'Learning Science'],
        isRAG: false
    },
    {
        id: 'synthesis',
        name: 'Diplomat',
        role: 'Synthesis Agent',
        description: 'Compares newly extracted concepts against existing ones using vector similarity, merging duplicates and resolving contradictions.',
        model: 'Gemini 2.5 Flash',
        rarity: 'uncommon',
        number: '002',
        commitSha: '0dea645',
        createdDate: 'Jan 30, 2026',
        imageFilename: 'frosted_card_bg_2_1770134199307.png',
        tools: ['Vector Similarity', 'Conflict Resolution'],
        databases: ['Postgres (pgvector)'],
        context: ['Existing Concepts', 'New Extracts'],
        isRAG: false
    },
    {
        id: 'extract',
        name: 'Miner',
        role: 'Extraction Agent',
        description: 'Parses raw text from your notes and uploads to extract structured concepts, definitions, relationships, and key facts.',
        model: 'Gemini 2.5 Flash',
        rarity: 'common',
        number: '001',
        commitSha: '0dea645',
        createdDate: 'Jan 30, 2026',
        imageFilename: 'frosted_card_bg_8_miner_1770134971171.png',
        tools: ['NLP Extraction', 'Pattern Matching'],
        databases: [],
        context: ['Raw Note Content', 'Markdown'],
        isRAG: false
    },
];

interface AgentDeckProps {
    onClose: () => void;
}

export const AgentDeck: React.FC<AgentDeckProps> = ({ onClose }) => {
    const [agents, setAgents] = useState<AgentInfo[]>(AGENTS_DATA);

    const removeTopCard = () => {
        setAgents((prev) => {
            const top = prev[0];
            const rest = prev.slice(1);
            // Recycle to bottom
            return [...rest, top];
        });
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
            {/* Close Button */}
            <button
                onClick={onClose}
                className="absolute top-6 right-6 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors z-50"
            >
                <X className="w-6 h-6" />
            </button>

            <div className="relative w-full max-w-sm h-full flex flex-col items-center justify-center">

                <div className="relative w-[320px] h-[500px]">
                    <AnimatePresence>
                        {agents.map((agent, index) => (
                            <AgentCard
                                key={agent.id}
                                agent={agent}
                                index={index}
                                onRemove={removeTopCard}
                            />
                        ))}
                    </AnimatePresence>
                </div>

                <div className="mt-8 text-zinc-500 text-xs font-mono animate-pulse">
                    Swipe to explore agents &rarr;
                </div>
            </div>
        </div>
    );
};
