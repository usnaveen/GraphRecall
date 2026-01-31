"use client";

import React from "react";
import { X, BookOpen, Brain } from "lucide-react";
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

        </CardContent>
      </Card>
    </div>
  );
}
