"use client";

import React, { useState } from "react";
import { Send, FileText, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/lib/store";
import api from "@/lib/api";

export default function NoteEditor() {
  const [content, setContent] = useState("");
  const [result, setResult] = useState<{
    success: boolean;
    message: string;
    details?: {
      concepts_created: number;
      relationships_created: number;
      processing_time_ms?: number;
    };
  } | null>(null);

  const { isIngesting, setIngesting, setIngestProgress, setGraphData } = useStore();

  const handleIngest = async () => {
    if (!content.trim()) return;

    setIngesting(true);
    setIngestProgress("Sending to server...");
    setResult(null);

    try {
      setIngestProgress("Extracting concepts (this may take 1-2 minutes)...");
      const response = await api.ingestNote(content);

      setResult({
        success: true,
        message: `Successfully created ${response.concepts_created} concepts!`,
        details: {
          concepts_created: response.concepts_created,
          relationships_created: response.relationships_created,
          processing_time_ms: response.processing_time_ms,
        },
      });

      // Refresh the graph
      setIngestProgress("Refreshing graph...");
      const graphData = await api.getGraph();
      setGraphData(graphData);

      // Clear the editor
      setContent("");
    } catch (error) {
      setResult({
        success: false,
        message: error instanceof Error ? error.message : "Failed to ingest note",
      });
    } finally {
      setIngesting(false);
      setIngestProgress(null);
    }
  };

  return (
    <Card className="bg-slate-800 border-slate-700 h-full flex flex-col">
      <CardHeader className="border-b border-slate-700">
        <CardTitle className="text-white flex items-center gap-2">
          <FileText className="h-5 w-5" />
          Add Note
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col p-4">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Paste or type your markdown notes here...

Example:
# Neural Networks

Neural networks are computing systems inspired by biological neural networks...

## Backpropagation

The backpropagation algorithm is used to train neural networks..."
          className="flex-1 w-full p-4 bg-slate-900 border border-slate-700 rounded-lg text-slate-300 placeholder:text-slate-600 resize-none focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
          disabled={isIngesting}
        />

        {/* Result message */}
        {result && (
          <div
            className={`mt-4 p-3 rounded-lg flex items-start gap-3 ${
              result.success
                ? "bg-green-500/10 border border-green-500/30"
                : "bg-red-500/10 border border-red-500/30"
            }`}
          >
            {result.success ? (
              <CheckCircle2 className="h-5 w-5 text-green-500 flex-shrink-0 mt-0.5" />
            ) : (
              <XCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
            )}
            <div>
              <p className={result.success ? "text-green-400" : "text-red-400"}>
                {result.message}
              </p>
              {result.details && (
                <div className="text-sm text-slate-400 mt-1">
                  <p>Concepts: {result.details.concepts_created}</p>
                  <p>Relationships: {result.details.relationships_created}</p>
                  {result.details.processing_time_ms && (
                    <p>Time: {(result.details.processing_time_ms / 1000).toFixed(1)}s</p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Progress message */}
        {isIngesting && (
          <div className="mt-4 p-3 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center gap-3">
            <Loader2 className="h-5 w-5 text-purple-500 animate-spin" />
            <span className="text-purple-400">Processing...</span>
          </div>
        )}

        <Button
          onClick={handleIngest}
          disabled={isIngesting || !content.trim()}
          className="mt-4 bg-purple-600 hover:bg-purple-700"
        >
          {isIngesting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Processing...
            </>
          ) : (
            <>
              <Send className="h-4 w-4 mr-2" />
              Ingest Note
            </>
          )}
        </Button>
      </CardContent>
    </Card>
  );
}
