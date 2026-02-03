import React from 'react';
import { motion, type PanInfo } from 'framer-motion';

export interface AgentInfo {
    id: string;
    name: string;
    role: string;
    description: string;
    model: string;
    rarity: 'common' | 'uncommon' | 'rare' | 'legendary';
    number: string;
    commitSha: string;
    createdDate: string;
    imageFilename: string;
}

interface AgentCardProps {
    agent: AgentInfo;
    index: number;
    onRemove: () => void;
}

const RARITY_COLORS = {
    common: 'border-zinc-600',
    uncommon: 'border-cyan-500 shadow-[0_0_15px_rgba(6,182,212,0.5)]',
    rare: 'border-purple-500 shadow-[0_0_20px_rgba(168,85,247,0.6)]',
    legendary: 'border-amber-500 shadow-[0_0_25px_rgba(245,158,11,0.8)]',
};

const RARITY_LABELS = {
    common: 'Basic Agent',
    uncommon: 'Advanced Agent',
    rare: 'Specialized Agent',
    legendary: 'Master Agent',
};

export const AgentCard: React.FC<AgentCardProps> = ({ agent, index, onRemove }) => {
    const exitX = React.useRef(0);

    const handleDragEnd = (_: any, info: PanInfo) => {
        if (Math.abs(info.offset.x) > 100) {
            exitX.current = info.offset.x > 0 ? 200 : -200;
            onRemove();
        }
    };

    // Stack effect: top card is interactive, others are scaled down
    const isTop = index === 0;

    return (
        <motion.div
            className="absolute top-0 left-0 w-full h-full flex items-center justify-center p-4 cursor-grab active:cursor-grabbing"
            style={{
                zIndex: 50 - index
            }}
            initial={{ scale: 0.9, y: 30, opacity: 0 }}
            animate={{
                scale: isTop ? 1 : 1 - index * 0.05,
                y: isTop ? 0 : index * 10,
                opacity: index < 3 ? 1 : 0,
                rotate: isTop ? 0 : (index % 2 === 0 ? 2 : -2)
            }}
            exit={{ x: exitX.current, opacity: 0, transition: { duration: 0.2 } }}
            drag={isTop ? 'x' : false}
            dragConstraints={{ left: 0, right: 0 }}
            onDragEnd={handleDragEnd}
            whileDrag={{ rotate: 5 }}
        >
            <div
                className={`
          relative w-[320px] h-[500px] rounded-3xl overflow-hidden border-2 
          ${RARITY_COLORS[agent.rarity]} bg-zinc-900/80 backdrop-blur-md
          flex flex-col text-white select-none
        `}
            >
                {/* Background Image */}
                <div className="absolute inset-0 z-0">
                    {/* Since images are in public/assets/agents/ */}
                    <img
                        src={`/assets/agents/${agent.imageFilename}`}
                        alt="bg"
                        className="w-full h-full object-cover opacity-60"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent" />
                </div>

                {/* Header */}
                <div className="relative z-10 p-5 flex justify-between items-start">
                    <div className="bg-black/40 backdrop-blur-md px-3 py-1 rounded-full border border-white/10 text-xs font-mono text-zinc-300">
                        #{agent.number}
                    </div>
                    <div className={`
             px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider
             ${agent.rarity === 'legendary' ? 'bg-amber-500/20 text-amber-300 border border-amber-500/50' :
                            agent.rarity === 'rare' ? 'bg-purple-500/20 text-purple-300 border border-purple-500/50' :
                                'bg-white/10 text-zinc-400 border border-white/10'}
           `}>
                        {RARITY_LABELS[agent.rarity]}
                    </div>
                </div>

                {/* Content */}
                <div className="relative z-10 flex-1 flex flex-col justify-end p-6 gap-3">
                    <div>
                        <h2 className="text-3xl font-black tracking-tight mb-1 text-transparent bg-clip-text bg-gradient-to-br from-white to-zinc-400">
                            {agent.name}
                        </h2>
                        <div className="text-sm font-medium text-cyan-400 uppercase tracking-widest mb-4">
                            {agent.role}
                        </div>

                        <p className="text-zinc-300 text-sm leading-relaxed mb-6 italic border-l-2 border-white/20 pl-3">
                            "{agent.description}"
                        </p>

                        <div className="space-y-2 text-xs font-mono text-zinc-400 bg-black/40 p-4 rounded-xl border border-white/5">
                            <div className="flex justify-between">
                                <span>Model:</span>
                                <span className="text-zinc-200">{agent.model}</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Born:</span>
                                <span className="text-zinc-200">{agent.createdDate}</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Commit:</span>
                                <span className="text-zinc-500">{agent.commitSha}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </motion.div>
    );
};
