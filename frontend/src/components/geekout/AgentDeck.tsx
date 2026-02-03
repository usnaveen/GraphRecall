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
        description: 'Orchestrates the entire team. Decides which agent is best suited for your request and routes tasks accordingly.',
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
        description: 'Silently prowls through your uploads in the dark, marking potential quizzes so you don\'t have to pay for them later.',
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
        description: 'Analyzes your graph for missing links. "Hey, isn\'t Quantum Mechanics related to Linear Algebra?"',
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
        description: 'Keeper of the Graph. Knows everything you\'ve ever noted and weaves answers from the tangled web of your memory.',
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
        description: 'Deduces what you actually want when you type "help me study". Figures out if you need a quiz, a summary, or a specific fact.',
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
        description: 'Ventures into the wild internet (via Tavily) to verify your knowledge against the world.',
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
        description: 'Translates abstract thoughts into structured diagrams. If you can think it, this agent can draw it.',
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
        description: 'The workhorse. Churns out flashcards and questions tirelessly. Loves a good multiple choice.',
        model: 'Gemini 2.5 Flash',
        rarity: 'common',
        number: '004',
        commitSha: '0dea645',
        createdDate: 'Jan 30, 2026',
        imageFilename: 'frosted_card_bg_1_1770134176619.png',
        tools: ['JSON Parser', 'Flashcard Gen'],
        databases: ['Postgres'],
        context: ['Concept Definitions', 'Learning Science'],
        isRAG: false
    },
    {
        id: 'synthesis',
        name: 'Diplomat',
        role: 'Synthesis Agent',
        description: 'Resolves conflicts between new and old ideas. Ensures your knowledge graph doesn\'t contradict itself.',
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
        description: 'The first line of defense. Smashes raw text rocks to find the concept gems hidden inside.',
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

            <div className="relative w-full max-w-sm h-[600px] flex flex-col items-center">
                <div className="text-center mb-8 relative z-50">
                    <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-cyan-400 to-purple-400">
                        Geeky Facts
                    </h2>
                    <p className="text-zinc-400 text-xs mt-1">
                        Meet the AI Agents powering your brain
                    </p>
                </div>

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
