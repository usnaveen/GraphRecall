"use client";

import React from "react";
import { X, BookOpen, Brain, Link2, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useStore } from "@/lib/store";

export default function ConceptPanel() {
  const { selectedConcept, setSelectedConcept } = useStore();

  if (!selectedConcept) return null;

  return (
    <div className="absolute right-4 top-4 bottom-4 w-80 z-10">
      <Card className="h-full bg-slate-800/95 border-slate-700 backdrop-blur">
        <CardHeader className="border-b border-slate-700">
          <div className="flex items-start justify-between">
            <div>
              <CardTitle className="text-white text-lg">
                {selectedConcept.name}
              </CardTitle>
              <span className="text-xs text-purple-400 font-medium">
                {selectedConcept.domain}
              </span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setSelectedConcept(null)}
              className="text-slate-400 hover:text-white"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-4 space-y-4 overflow-y-auto max-h-[calc(100%-80px)]">
          {/* Definition */}
          <div>
            <h4 className="text-sm font-medium text-slate-300 flex items-center gap-2 mb-2">
              <BookOpen className="h-4 w-4" />
              Definition
            </h4>
            <p className="text-sm text-slate-400">
              {selectedConcept.definition || "No definition available"}
            </p>
          </div>

          {/* Complexity */}
          <div>
            <h4 className="text-sm font-medium text-slate-300 flex items-center gap-2 mb-2">
              <Brain className="h-4 w-4" />
              Complexity
            </h4>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-green-500 via-yellow-500 to-red-500"
                  style={{
                    width: `${(selectedConcept.complexity_score / 10) * 100}%`,
                  }}
                />
              </div>
              <span className="text-sm text-slate-400">
                {selectedConcept.complexity_score}/10
              </span>
            </div>
          </div>

          {/* Relationships */}
          {selectedConcept.relationships && selectedConcept.relationships.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-slate-300 flex items-center gap-2 mb-2">
                <Link2 className="h-4 w-4" />
                Related Concepts
              </h4>
              <div className="space-y-1">
                {selectedConcept.relationships.map((rel, index) => (
                  <div
                    key={index}
                    className="text-sm text-slate-400 bg-slate-700/50 px-2 py-1 rounded flex items-center justify-between"
                  >
                    <span>{rel.target}</span>
                    <span className="text-xs text-slate-500">
                      {rel.type.replace(/_/g, " ")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="pt-4 border-t border-slate-700 space-y-2">
            <Button
              variant="outline"
              className="w-full border-purple-500/50 text-purple-400 hover:bg-purple-500/10"
            >
              <Brain className="h-4 w-4 mr-2" />
              Start Quiz
            </Button>
            <Button
              variant="outline"
              className="w-full border-slate-600 text-slate-300 hover:bg-slate-700"
            >
              <Clock className="h-4 w-4 mr-2" />
              Review Flashcards
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
