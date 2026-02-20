import { useEffect, useState } from "react";
import { X, FileText, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import ReactMarkdown from 'react-markdown';
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
  evidence_span?: string;
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

  // Get chunks for display. The backend now pre-filters the most relevant chunks 
  // (e.g. matching evidence_span, or having images).
  const getDisplayChunks = (chunks: ChunkData[]) => {
    return chunks.slice().sort((a, b) => a.chunk_index - b.chunk_index);
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

                      {/* Text content rendered via Markdown */}
                      <div className="text-sm text-white/80 leading-relaxed prose prose-invert max-w-none">
                        <ReactMarkdown
                          components={{
                            img: ({ node, ...props }) => {
                              // If it's a relative/asset path from backend
                              let src = props.src;
                              if (src && !src.startsWith('http') && !src.startsWith('data:')) {
                                src = `/api/v2/files/${src}`;
                              }
                              return (
                                <img
                                  {...props}
                                  src={src}
                                  className="max-w-full rounded-lg my-2 border border-white/10"
                                  loading="lazy"
                                />
                              );
                            },
                            p: ({ children }) => <span className="mb-2 block break-words whitespace-pre-wrap">{children}</span>,
                            a: ({ node, ...props }) => <a {...props} className="text-[#B6FF2E] hover:underline" target="_blank" rel="noopener noreferrer" />,
                          }}
                        >
                          {chunk.content}
                        </ReactMarkdown>
                      </div>

                      {/* Images (Fallback for explicit JSON images that aren't in markdown) */}
                      {chunk.images && chunk.images.length > 0 && chunk.content && !chunk.content.includes("![") && (
                        <div className="mt-3 space-y-2">
                          {chunk.images.map((img, idx) => {
                            let ImgSrc = undefined;
                            let ImgAlt = `Figure ${idx + 1}`;

                            if (typeof img === "string") {
                              if (img.startsWith("http") || img.startsWith("data:")) {
                                ImgSrc = img;
                              } else {
                                // Assume it's a dictionary string or a filename and try parsing
                                try {
                                  let parsed = JSON.parse(img);
                                  ImgSrc = parsed.filename ? `/api/v2/files/${parsed.filename}` : parsed.url;
                                  ImgAlt = parsed.caption || parsed.alt || ImgAlt;
                                } catch (e) {
                                  // Raw string filename
                                  ImgSrc = `/api/v2/files/${img}`;
                                }
                              }
                            } else if (typeof img === "object") {
                              const typedImg = img as any;
                              ImgSrc = typedImg.filename ? `/api/v2/files/${typedImg.filename}` : typedImg.url;
                              ImgAlt = typedImg.caption || typedImg.alt || ImgAlt;
                            }

                            return ImgSrc ? (
                              <div
                                key={idx}
                                className="rounded-lg overflow-hidden border border-white/10 bg-white/5"
                              >
                                <img
                                  src={ImgSrc}
                                  alt={ImgAlt}
                                  className="max-w-full h-auto"
                                  loading="lazy"
                                />
                              </div>
                            ) : null;
                          })}
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
