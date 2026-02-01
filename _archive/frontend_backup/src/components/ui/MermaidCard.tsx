"use client";

import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { Network, ZoomIn } from "lucide-react";
import { FeedItem } from "@/lib/api";

// Initialize mermaid with dark theme
mermaid.initialize({
    startOnLoad: false,
    theme: "dark",
    securityLevel: "loose",
    themeVariables: {
        fontFamily: "Inter, sans-serif",
        fontSize: "14px",
        primaryColor: "#B6FF2E",
        primaryTextColor: "#fff",
        primaryBorderColor: "#B6FF2E",
        lineColor: "#B6FF2E",
        secondaryColor: "#1A1A1C",
        tertiaryColor: "#1A1A1C",
    },
    flowchart: {
        curve: "basis",
        htmlLabels: true,
    }
});

export default function MermaidCard({ item }: { item: FeedItem }) {
    const chartRef = useRef<HTMLDivElement>(null);
    const [svg, setSvg] = useState<string>("");
    const content = item.content as {
        mermaid_code: string;
        title: string;
        chart_type?: string;
    };

    useEffect(() => {
        const renderChart = async () => {
            try {
                const id = `mermaid-${item.id}`;
                const { svg } = await mermaid.render(id, content.mermaid_code);
                setSvg(svg);
            } catch (error) {
                console.error("Failed to render mermaid chart:", error);
            }
        };

        if (content.mermaid_code) {
            renderChart();
        }
    }, [content.mermaid_code, item.id]);

    return (
        <div className="h-full flex flex-col p-6 recall-card">
            {/* Header */}
            <div className="flex items-center gap-2 mb-4">
                <Network className="h-5 w-5 text-[#B6FF2E]" />
                <span className="text-[#B6FF2E] font-medium font-heading tracking-wide">
                    {content.chart_type === "mindmap" ? "Mental Map" : "Process Flow"}
                </span>
                {item.concept_name && (
                    <span className="text-slate-500 text-sm font-mono">• {item.concept_name}</span>
                )}
            </div>

            {/* Main Graph Area */}
            <div className="flex-1 rounded-xl bg-black/20 border border-white/5 overflow-hidden relative group">

                {/* Graph SVG */}
                <div
                    className="w-full h-full flex items-center justify-center p-4 overflow-auto"
                    dangerouslySetInnerHTML={{ __html: svg }}
                />

                {/* Hover Overlay */}
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
                    <div className="flex items-center gap-2 text-white/80 bg-black/80 px-4 py-2 rounded-full border border-white/10 backdrop-blur-md">
                        <ZoomIn className="h-4 w-4" />
                        <span className="text-xs font-medium">Interactive Graph</span>
                    </div>
                </div>
            </div>

            {/* Caption/Title */}
            <div className="mt-4">
                <h3 className="text-lg font-medium text-white mb-1">{content.title}</h3>
                <p className="text-sm text-slate-400">
                    Visualize the connections between these concepts.
                </p>
            </div>
        </div>
    );
}
