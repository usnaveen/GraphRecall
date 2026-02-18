import { useEffect, useState } from "react";
import { X, FileText, Loader2, Image as ImageIcon } from "lucide-react";
import { motion } from "framer-motion";
import { conceptsService } from "../../services/api";

interface ChunkData {
  id: string;
  content: string;
  chunk_level: string;
  chunk_index: number;
  page_start?: number;
  page_end?: number;
  images: string[];
  parent_content?: string;
}

interface NoteData {
  id: string;
  title: string;
  resource_type?: string;
  chunks: ChunkData[];
}

interface NotePanelProps {
  conceptId: string;
  conceptName: string;
  onClose: () => void;
}

export default function NotePanel({ conceptId, conceptName, onClose }: NotePanelProps) {
  const [notes, setNotes] = useState<NoteData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const res = await conceptsService.getConceptNotes(conceptId);
        if (!cancelled) setNotes(res.notes || []);
      } catch (err) {
        console.error("Failed to load notes:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [conceptId]);

  // Get only parent-level chunks for display (avoid duplicating parent+child content)
  const getDisplayChunks = (chunks: ChunkData[]) => {
    const parents = chunks.filter((c) => c.chunk_level === "parent");
    if (parents.length > 0) return parents.sort((a, b) => a.chunk_index - b.chunk_index);
    // Fallback: show child chunks if no parents
    return chunks
      .filter((c) => c.chunk_level === "child")
      .sort((a, b) => a.chunk_index - b.chunk_index);
  };

  return (
    <motion.div
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: "100%", opacity: 1 }}
      exit={{ width: 0, opacity: 0 }}
      transition={{ duration: 0.3 }}
      className="h-full bg-[#0d0d12] border-l border-white/10 flex flex-col overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/10 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-4 h-4 text-[#B6FF2E] flex-shrink-0" />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-white truncate">
              Notes: {conceptName}
            </h3>
            <p className="text-[10px] text-white/40">
              {notes.length} source{notes.length !== 1 ? "s" : ""} found
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-full hover:bg-white/10 transition-colors flex-shrink-0"
        >
          <X className="w-4 h-4 text-white/50" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center p-12">
            <Loader2 className="w-6 h-6 animate-spin text-[#B6FF2E]" />
          </div>
        ) : notes.length === 0 ? (
          <div className="text-center p-8">
            <FileText className="w-8 h-8 text-white/20 mx-auto mb-3" />
            <p className="text-sm text-white/50">No notes linked to this concept</p>
            <p className="text-xs text-white/30 mt-1">
              Ingest content to see notes here
            </p>
          </div>
        ) : (
          <div className="p-4 space-y-6">
            {notes.map((note) => (
              <div key={note.id}>
                {/* Note title */}
                <div className="flex items-center gap-2 mb-3 pb-2 border-b border-white/5">
                  <h4 className="text-xs font-semibold text-[#B6FF2E] uppercase tracking-wider">
                    {note.title}
                  </h4>
                  {note.resource_type && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-white/5 text-white/40">
                      {note.resource_type}
                    </span>
                  )}
                </div>

                {/* Chunks */}
                <div className="space-y-4">
                  {getDisplayChunks(note.chunks).map((chunk) => (
                    <div key={chunk.id} className="group">
                      {/* Page indicator */}
                      {chunk.page_start && (
                        <p className="text-[9px] text-white/30 mb-1 font-mono">
                          p. {chunk.page_start}
                          {chunk.page_end && chunk.page_end !== chunk.page_start
                            ? `–${chunk.page_end}`
                            : ""}
                        </p>
                      )}

                      {/* Text content */}
                      <div className="text-sm text-white/80 leading-relaxed whitespace-pre-wrap">
                        {chunk.content}
                      </div>

                      {/* Images */}
                      {chunk.images && chunk.images.length > 0 && (
                        <div className="mt-3 space-y-2">
                          {chunk.images.map((img, idx) => (
                            <div
                              key={idx}
                              className="rounded-lg overflow-hidden border border-white/10 bg-white/5"
                            >
                              {typeof img === "string" && img.startsWith("http") ? (
                                <img
                                  src={img}
                                  alt={`Figure from ${note.title}`}
                                  className="max-w-full h-auto"
                                  loading="lazy"
                                />
                              ) : typeof img === "object" && (img as any).url ? (
                                <img
                                  src={(img as any).url}
                                  alt={(img as any).alt || `Figure ${idx + 1}`}
                                  className="max-w-full h-auto"
                                  loading="lazy"
                                />
                              ) : (
                                <div className="flex items-center gap-2 p-3 text-xs text-white/40">
                                  <ImageIcon className="w-4 h-4" />
                                  <span>Image: {typeof img === "string" ? img : JSON.stringify(img)}</span>
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
