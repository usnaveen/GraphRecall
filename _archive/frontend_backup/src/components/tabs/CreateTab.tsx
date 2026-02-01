"use client";

import React, { useState, useEffect } from "react";
import {
  FileText,
  Send,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronRight,
  Plus,
  Trash2,
  Edit3,
  Check,
  X,
  AlertCircle,
  Sparkles,
  ArrowRightLeft,
  ArrowRight,
  Copy,
  ImagePlus,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStore } from "@/lib/store";
import api, { ConceptReviewItem } from "@/lib/api";

// Steps in the create flow
type CreateStep = "input" | "review" | "complete";

export default function CreateTab() {
  const {
    reviewSession,
    setReviewSession,
    isIngesting,
    setIngesting,
    isReviewLoading,
    setReviewLoading,
  } = useStore();

  const [content, setContent] = useState("");
  const [step, setStep] = useState<CreateStep>("input");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    concepts_created: number;
    relationships_created: number;
  } | null>(null);
  const [editingConcept, setEditingConcept] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<Partial<ConceptReviewItem>>({});

  // Upload state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadType, setUploadType] = useState<"screenshot" | "infographic" | "diagram">("screenshot");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  // Check for pending review sessions on mount
  useEffect(() => {
    checkPendingSessions();
  }, []);

  const checkPendingSessions = async () => {
    try {
      const { sessions } = await api.getPendingReviewSessions();
      if (sessions.length > 0) {
        // Load the most recent pending session
        const session = await api.getReviewSession(sessions[0].session_id);
        setReviewSession(session);
        setStep("review");
      }
    } catch (error) {
      console.error("Failed to check pending sessions:", error);
    }
  };

  const handleIngest = async () => {
    if (!content.trim()) return;

    setIngesting(true);
    setError(null);

    try {
      // Use new human-in-the-loop endpoint
      const response = await api.ingestWithReview(content);

      if (response.session_id) {
        // Load the review session
        const session = await api.getReviewSession(response.session_id);
        setReviewSession(session);
        setStep("review");
      } else {
        // Direct approval (skip_review was true)
        setResult({ concepts_created: response.concepts_count, relationships_created: 0 });
        setStep("complete");
        setContent("");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process notes");
    } finally {
      setIngesting(false);
    }
  };

  const handleToggleConcept = (conceptId: string) => {
    if (!reviewSession) return;

    setReviewSession({
      ...reviewSession,
      concepts: reviewSession.concepts.map((c) =>
        c.id === conceptId
          ? {
            ...c,
            is_selected: !c.is_selected,
            user_modified: true,
            // If unselecting and it was an overwrite, maybe revert ID? 
            // unique ID logic handled in resolving
          }
          : c
      ),
    });
  };

  const handleResolveConflict = (concept: ConceptReviewItem, resolution: 'keep_existing' | 'overwrite' | 'merge') => {
    if (!reviewSession) return;

    let updatedConcept = { ...concept };

    if (resolution === 'keep_existing') {
      // Deselect the new concept
      updatedConcept.is_selected = false;
      updatedConcept.user_modified = true;
    } else if (resolution === 'overwrite') {
      // Use new content but existing ID
      if (concept.matched_existing_id) {
        updatedConcept.id = concept.matched_existing_id; // Swap ID to overwrite
        updatedConcept.is_selected = true;
        updatedConcept.user_modified = true;
        // Remove duplicate flag so it shows as a normal accepted concept
        updatedConcept.is_duplicate = false;
      }
    } else if (resolution === 'merge') {
      // Open edit form with existing ID, ready to edit
      if (concept.matched_existing_id) {
        updatedConcept.id = concept.matched_existing_id;
        // Don't set is_selected yet, wait for save
        updatedConcept.is_duplicate = false; // Treat as normal for editing
      }
      // Trigger edit immediately
      setEditingConcept(updatedConcept.id);
      setEditForm({
        name: updatedConcept.name,
        definition: updatedConcept.definition,
        domain: updatedConcept.domain,
        complexity_score: updatedConcept.complexity_score,
      });

      // We need to update the session first so the mapped ID is correct for the edit form
    }

    setReviewSession({
      ...reviewSession,
      concepts: reviewSession.concepts.map(c => c.id === concept.id ? updatedConcept : c)
    });
  };

  const getExistingConceptDetails = (conceptName: string) => {
    if (!reviewSession?.conflicts) return null;
    // Search case-insensitive
    const conflict = reviewSession.conflicts.find((c) =>
      c.new_concept_name.toLowerCase() === conceptName.toLowerCase()
    );
    return conflict ? conflict.existing_concept : null;
  };

  const handleEditConcept = (concept: ConceptReviewItem) => {
    setEditingConcept(concept.id);
    setEditForm({
      name: concept.name,
      definition: concept.definition,
      domain: concept.domain,
      complexity_score: concept.complexity_score,
    });
  };

  const handleSaveEdit = () => {
    if (!reviewSession || !editingConcept) return;

    setReviewSession({
      ...reviewSession,
      concepts: reviewSession.concepts.map((c) =>
        c.id === editingConcept
          ? { ...c, ...editForm, user_modified: true, is_selected: true }
          : c
      ),
    });
    setEditingConcept(null);
    setEditForm({});
  };

  const handleApprove = async () => {
    if (!reviewSession) return;

    setReviewLoading(true);
    setError(null);

    try {
      const approvedConcepts = reviewSession.concepts.filter((c) => c.is_selected);
      const removedIds = reviewSession.concepts
        .filter((c) => !c.is_selected)
        .map((c) => c.id);

      const response = await api.approveReviewSession(
        reviewSession.session_id,
        approvedConcepts,
        removedIds
      );

      setResult({
        concepts_created: response.concepts_created,
        relationships_created: response.relationships_created,
      });
      setStep("complete");
      setReviewSession(null);
      setContent("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve concepts");
    } finally {
      setReviewLoading(false);
    }
  };

  const handleCancel = async () => {
    if (reviewSession) {
      try {
        await api.cancelReviewSession(reviewSession.session_id);
      } catch (error) {
        console.error("Failed to cancel session:", error);
      }
    }
    setReviewSession(null);
    setStep("input");
  };

  const handleStartNew = () => {
    setStep("input");
    setResult(null);
    setError(null);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    setSelectedFile(file);
    setUploadSuccess(false);
    if (file) {
      setPreviewUrl(URL.createObjectURL(file));
    } else {
      setPreviewUrl(null);
    }
  };

  const handleClearFile = () => {
    setSelectedFile(null);
    setPreviewUrl(null);
    setUploadTitle("");
    setUploadSuccess(false);
  };

  const handleFileUpload = async () => {
    if (!selectedFile) return;
    setIsUploading(true);
    setError(null);
    try {
      await api.uploadFile(selectedFile, uploadType, uploadTitle || undefined);
      setUploadSuccess(true);
      setSelectedFile(null);
      setPreviewUrl(null);
      setUploadTitle("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  // Input Step
  const renderInputStep = () => (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-center gap-3 mb-4">
        <FileText className="h-6 w-6 text-purple-500" />
        <h2 className="text-lg font-semibold text-white">Add Notes</h2>
      </div>

      <p className="text-sm text-slate-400 mb-4">
        Paste your notes or learning material. Our AI will extract concepts and let you review them before adding to your knowledge graph.
      </p>

      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Paste or type your markdown notes here...

Example:
# Neural Networks

Neural networks are computing systems inspired by biological neural networks...

## Backpropagation

The backpropagation algorithm is used to train neural networks..."
        className="flex-1 w-full p-4 bg-[#1A1A1C] border border-[#27272A] rounded-xl text-slate-300 placeholder:text-slate-600 resize-none focus:outline-none focus:ring-2 focus:ring-purple-500 font-mono text-sm"
        disabled={isIngesting}
      />

      {error && (
        <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-3">
          <XCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-red-400 text-sm">{error}</p>
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
            Extracting Concepts...
          </>
        ) : (
          <>
            <Sparkles className="h-4 w-4 mr-2" />
            Extract Concepts
          </>
        )}
      </Button>

      {/* Divider */}
      <div className="flex items-center gap-3 my-5">
        <div className="flex-1 h-px bg-[#27272A]" />
        <span className="text-xs text-slate-500 uppercase tracking-wider">or upload an image</span>
        <div className="flex-1 h-px bg-[#27272A]" />
      </div>

      {/* File Upload */}
      <div className="p-4 bg-[#1A1A1C] rounded-xl border border-dashed border-[#3f3f46]">
        {!selectedFile ? (
          <label
            htmlFor="file-upload"
            className="flex flex-col items-center justify-center py-6 cursor-pointer hover:bg-[#27272A]/50 rounded-lg transition-colors"
          >
            <ImagePlus className="h-8 w-8 text-slate-500 mb-2" />
            <span className="text-sm text-slate-400">Click to select an image</span>
            <span className="text-xs text-slate-600 mt-1">JPEG, PNG, GIF, WebP (max 10MB)</span>
            <input
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              onChange={handleFileSelect}
              className="hidden"
              id="file-upload"
            />
          </label>
        ) : (
          <div className="space-y-3">
            {/* Preview */}
            <div className="relative">
              <img
                src={previewUrl || ""}
                alt="Preview"
                className="w-full max-h-48 object-contain rounded-lg bg-black/20"
              />
              <button
                onClick={handleClearFile}
                className="absolute top-2 right-2 p-1 bg-black/60 rounded-full text-white hover:bg-black/80"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Title input */}
            <input
              type="text"
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="Title (optional)"
              className="w-full p-2 bg-[#27272A] border border-[#3f3f46] rounded-lg text-white text-sm placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-purple-500"
            />

            {/* Upload type */}
            <select
              value={uploadType}
              onChange={(e) => setUploadType(e.target.value as typeof uploadType)}
              className="w-full p-2 bg-[#27272A] border border-[#3f3f46] rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-purple-500"
            >
              <option value="screenshot">Screenshot</option>
              <option value="infographic">Infographic</option>
              <option value="diagram">Diagram</option>
            </select>

            {/* Upload button */}
            <Button
              onClick={handleFileUpload}
              disabled={isUploading}
              className="w-full bg-purple-600 hover:bg-purple-700"
            >
              {isUploading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Uploading...
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4 mr-2" />
                  Upload to Library
                </>
              )}
            </Button>
          </div>
        )}

        {uploadSuccess && (
          <div className="mt-3 p-3 rounded-lg bg-green-500/10 border border-green-500/30 flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4 text-green-500" />
            <span className="text-sm text-green-400">Image uploaded! It will appear in your feed.</span>
          </div>
        )}
      </div>
    </div>
  );

  // Review Step
  const renderReviewStep = () => {
    if (!reviewSession) return null;

    const selectedCount = reviewSession.concepts.filter((c) => c.is_selected).length;
    const items = reviewSession.concepts;

    // Show conflicts first? Or just mix them in.
    // Let's sort duplicates to top for visibility
    const sortedConcepts = [...items].sort((a, b) => {
      if (a.is_duplicate && !b.is_duplicate) return -1;
      if (!a.is_duplicate && b.is_duplicate) return 1;
      return 0;
    });

    return (
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-[#27272A]">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold text-white">Review Concepts</h2>
            <span className="text-sm text-slate-400">
              {selectedCount} of {reviewSession.concepts.length} selected
            </span>
          </div>
          <p className="text-sm text-slate-400">
            Review the AI-detected concepts. Resolve any conflicts or duplicates.
          </p>
        </div>

        {/* Concepts list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {sortedConcepts.map((concept) => {
            const existing = concept.is_duplicate ? getExistingConceptDetails(concept.name) : null;

            return (
              <div
                key={concept.id}
                className={`p-4 rounded-xl border-2 transition-all ${concept.is_selected
                    ? "bg-purple-500/10 border-purple-500/50"
                    : "bg-[#1A1A1C] border-[#27272A] opacity-50"
                  }`}
              >
                {editingConcept === concept.id ? (
                  // Edit mode
                  <div className="space-y-3">
                    <div className="flex justify-between items-center mb-2">
                      <h4 className="text-white font-medium">Edit Concept</h4>
                    </div>
                    <input
                      type="text"
                      value={editForm.name || ""}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="w-full p-2 bg-[#27272A] border border-[#3f3f46] rounded-lg text-white"
                      placeholder="Concept name"
                    />
                    <textarea
                      value={editForm.definition || ""}
                      onChange={(e) => setEditForm({ ...editForm, definition: e.target.value })}
                      className="w-full p-2 bg-[#27272A] border border-[#3f3f46] rounded-lg text-white text-sm resize-none"
                      rows={3}
                      placeholder="Definition"
                    />
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={editForm.domain || ""}
                        onChange={(e) => setEditForm({ ...editForm, domain: e.target.value })}
                        className="flex-1 p-2 bg-[#27272A] border border-[#3f3f46] rounded-lg text-white text-sm"
                        placeholder="Domain"
                      />
                      <input
                        type="number"
                        min={1}
                        max={10}
                        value={editForm.complexity_score || 5}
                        onChange={(e) => setEditForm({ ...editForm, complexity_score: parseInt(e.target.value) })}
                        className="w-20 p-2 bg-[#27272A] border border-[#3f3f46] rounded-lg text-white text-sm"
                        placeholder="1-10"
                      />
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" onClick={handleSaveEdit} className="bg-green-600 hover:bg-green-700">
                        <Check className="h-4 w-4 mr-1" /> Save & Select
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setEditingConcept(null)}>
                        <X className="h-4 w-4 mr-1" /> Cancel
                      </Button>
                    </div>
                  </div>
                ) : concept.is_duplicate && existing ? (
                  // Conflict Resolution UI
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-yellow-500 mb-2">
                      <AlertCircle className="h-5 w-5" />
                      <span className="font-semibold text-sm">Duplicate Concept Detected</span>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      {/* New Version */}
                      <div className="p-3 bg-purple-500/10 rounded-lg border border-purple-500/20">
                        <div className="text-xs text-purple-400 font-bold mb-1 uppercase tracking-wider">New Extraction</div>
                        <h4 className="font-medium text-white text-sm mb-1">{concept.name}</h4>
                        <p className="text-xs text-slate-400 line-clamp-3">{concept.definition}</p>
                      </div>

                      {/* Existing Version */}
                      <div className="p-3 bg-[#27272A] rounded-lg border border-[#3f3f46]">
                        <div className="text-xs text-slate-400 font-bold mb-1 uppercase tracking-wider">Existing in Graph</div>
                        <h4 className="font-medium text-slate-300 text-sm mb-1">{existing.name}</h4>
                        <p className="text-xs text-slate-500 line-clamp-3">{existing.definition}</p>
                      </div>
                    </div>

                    <div className="flex gap-2 pt-2">
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-1 border-[#3f3f46] hover:bg-[#27272A] text-slate-300"
                        onClick={() => handleResolveConflict(concept, 'keep_existing')}
                      >
                        <CheckCircle2 className="h-4 w-4 mr-2" />
                        Keep Existing
                      </Button>
                      <Button
                        size="sm"
                        className="flex-1 bg-purple-600 hover:bg-purple-700"
                        onClick={() => handleResolveConflict(concept, 'overwrite')}
                      >
                        <Copy className="h-4 w-4 mr-2" />
                        Overwrite
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="flex-1 border-purple-500 text-purple-400 hover:bg-purple-500/10"
                        onClick={() => handleResolveConflict(concept, 'merge')}
                      >
                        <ArrowRightLeft className="h-4 w-4 mr-2" />
                        Merge
                      </Button>
                    </div>
                  </div>
                ) : (
                  // Standard View mode
                  <>
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <h3 className="font-medium text-white">{concept.name}</h3>
                          {concept.user_modified && (
                            <span className="px-2 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded-full">
                              Modified
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-slate-400 mt-1">{concept.definition}</p>
                        <div className="flex items-center gap-3 mt-2 text-xs text-slate-500">
                          <span className="px-2 py-0.5 bg-[#27272A] rounded">{concept.domain}</span>
                          <span>Complexity: {concept.complexity_score}/10</span>
                          <span>Confidence: {Math.round(concept.confidence * 100)}%</span>
                        </div>
                        {concept.related_concepts.length > 0 && (
                          <div className="mt-2">
                            <span className="text-xs text-slate-500">Related: </span>
                            <span className="text-xs text-purple-400">
                              {concept.related_concepts.slice(0, 3).join(", ")}
                            </span>
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 ml-4">
                        <button
                          onClick={() => handleEditConcept(concept)}
                          className="p-2 text-slate-400 hover:text-white hover:bg-[#27272A] rounded-lg"
                        >
                          <Edit3 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => handleToggleConcept(concept.id)}
                          className={`p-2 rounded-lg ${concept.is_selected
                              ? "bg-purple-500 text-white"
                              : "bg-[#27272A] text-slate-400"
                            }`}
                        >
                          {concept.is_selected ? (
                            <Check className="h-4 w-4" />
                          ) : (
                            <Plus className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>

        {/* Actions */}
        <div className="p-4 border-t border-[#27272A] space-y-2">
          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2 mb-2">
              <AlertCircle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}

          <Button
            onClick={handleApprove}
            disabled={isReviewLoading || selectedCount === 0}
            className="w-full bg-purple-600 hover:bg-purple-700"
          >
            {isReviewLoading ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Adding to Graph...
              </>
            ) : (
              <>
                <CheckCircle2 className="h-4 w-4 mr-2" />
                Add {selectedCount} Concepts to Graph
              </>
            )}
          </Button>

          <Button variant="outline" onClick={handleCancel} className="w-full">
            <X className="h-4 w-4 mr-2" />
            Cancel
          </Button>
        </div>
      </div>
    );
  };

  // Complete Step
  const renderCompleteStep = () => (
    <div className="h-full flex flex-col items-center justify-center p-4">
      <div className="text-center">
        <div className="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
          <CheckCircle2 className="h-8 w-8 text-green-500" />
        </div>

        <h2 className="text-xl font-semibold text-white mb-2">
          Knowledge Graph Updated!
        </h2>

        {result && (
          <div className="text-slate-400 mb-6">
            <p>Created {result.concepts_created} new concepts</p>
            <p>Added {result.relationships_created} relationships</p>
          </div>
        )}

        <Button onClick={handleStartNew} className="bg-purple-600 hover:bg-purple-700">
          <Plus className="h-4 w-4 mr-2" />
          Add More Notes
        </Button>
      </div>
    </div>
  );

  return (
    <div className="h-full bg-[#0A0A0B]">
      {step === "input" && renderInputStep()}
      {step === "review" && renderReviewStep()}
      {step === "complete" && renderCompleteStep()}
    </div>
  );
}
