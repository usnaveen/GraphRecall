import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, Image, FileText, Link2, Check,
  Save, AlertCircle, Cpu, Database, Brain, Zap, Sparkles,
  FileType, HardDrive, Layers, GitBranch, Youtube, MessageSquare
} from 'lucide-react';
import * as pdfjsLib from 'pdfjs-dist';
import { ingestService, uploadsService } from '../services/api';
import { useAppStore } from '../store/useAppStore';

// Set PDF Worker - interacting with CDN to avoid Vite build complexity
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.js`;

type CreateStep = 'upload' | 'processing' | 'review' | 'success';
type InputMode = 'upload' | 'text' | 'youtube' | 'chat-transcript';

interface ExtractedConcept {
  id: string;
  name: string;
  definition: string;
  domain?: string;
  complexity?: number;
  selected: boolean;
  exists?: boolean;
}

interface FileMeta {
  fileName: string;
  fileSize: number;
  fileFormat: string;
  pageCount?: number;
  inputSource: 'file' | 'text' | 'url';
}

interface ProcessingMeta {
  // From file (client-side)
  file?: FileMeta;
  // From backend response
  concepts_extracted?: number;
  domains_detected?: string[];
  concept_names?: string[];
  avg_complexity?: number;
  content_length?: number;
  is_multimodal?: boolean;
  input_type?: string;
  extraction_agent?: string;
  existing_concepts_scanned?: number;
  overlap_ratio?: number;
  related_concept_names?: string[];
  concepts_created?: number;
  relationships_created?: number;
  flashcards_generated?: number;
  flashcard_agent?: string;
  upload_only?: boolean;
  upload_title?: string;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFormatLabel(ext: string): string {
  const map: Record<string, string> = {
    pdf: 'PDF Document',
    md: 'Markdown',
    txt: 'Plain Text',
    jpg: 'JPEG Image',
    jpeg: 'JPEG Image',
    png: 'PNG Image',
    gif: 'GIF Image',
    webp: 'WebP Image',
    docx: 'Word Document',
    doc: 'Word Document',
  };
  return map[ext] || ext.toUpperCase();
}

export function CreateScreen() {
  const [step, setStep] = useState<CreateStep>('upload');
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [extractedConcepts, setExtractedConcepts] = useState<ExtractedConcept[]>([]);
  const [inputType, setInputType] = useState<InputMode>('upload');
  const [textInput, setTextInput] = useState('');
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [processingMeta, setProcessingMeta] = useState<ProcessingMeta>({});
  const [uploadIntent, setUploadIntent] = useState<'ingest' | 'upload'>('ingest');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { fetchFeed, setActiveTab } = useAppStore();

  // Simulate progress ticks while waiting for API
  useEffect(() => {
    if (step !== 'processing' || progress >= 90) return;
    const timer = setInterval(() => {
      setProgress(p => {
        if (p >= 85) return p; // Cap simulated progress at 85%
        return p + Math.random() * 8 + 2;
      });
    }, 800);
    return () => clearInterval(timer);
  }, [step, progress]);

  const readFileContent = async (file: File): Promise<string> => {
    const extension = file.name.split('.').pop()?.toLowerCase();

    if (extension === 'pdf') {
      try {
        const arrayBuffer = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        let fullText = '';

        // Track page count for geekout facts
        setProcessingMeta(prev => ({
          ...prev,
          file: { ...prev.file!, pageCount: pdf.numPages }
        }));

        for (let i = 1; i <= pdf.numPages; i++) {
          const page = await pdf.getPage(i);
          const textContent = await page.getTextContent();
          const pageText = textContent.items.map((item: any) => item.str).join(' ');
          fullText += `\n--- Page ${i} ---\n${pageText}`;
        }
        return `Draft Note: ${file.name}\n\n${fullText}`;
      } catch (e) {
        throw new Error("Failed to parse PDF. Please ensure it is a valid text-based PDF.");
      }
    } else if (extension === 'docx' || extension === 'doc') {
      // DOCX: Read as ArrayBuffer, extract raw text using basic ZIP parsing
      // For MVP, we send the raw text content (paragraphs) to the LLM
      try {
        const arrayBuffer = await file.arrayBuffer();
        // Use basic text extraction from docx XML
        const blob = new Blob([arrayBuffer]);
        const text = await blob.text();
        // Extract text between <w:t> tags (basic DOCX XML text extraction)
        const matches = text.match(/<w:t[^>]*>([^<]*)<\/w:t>/g) || [];
        const extractedText = matches
          .map(m => m.replace(/<[^>]+>/g, ''))
          .join(' ');

        if (extractedText.trim().length < 10) {
          throw new Error("Could not extract text from DOCX. File may be empty or encrypted.");
        }
        return `Draft Note: ${file.name}\n\n${extractedText}`;
      } catch (e: any) {
        throw new Error(e.message || "Failed to parse DOCX file.");
      }
    } else if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(extension || '')) {
      // Handle Images as Base64 Data URL for Gemini Multimodal
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target?.result as string);
        reader.onerror = (e) => reject(e);
        reader.readAsDataURL(file);
      });
    } else {
      // Text, Markdown, etc.
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => resolve(e.target?.result as string);
        reader.onerror = (e) => reject(e);
        reader.readAsText(file);
      });
    }
  };

  const uploadImageFile = async (file: File) => {
    try {
      setStep('processing');
      setProgress(10);
      setError(null);
      setProcessingMeta({
        file: {
          fileName: file.name,
          fileSize: file.size,
          fileFormat: file.name.split('.').pop()?.toLowerCase() || '',
          inputSource: 'file',
        },
        upload_only: true,
        upload_title: file.name,
      });

      await uploadsService.createUpload(file, 'screenshot', file.name);
      setProgress(100);
      setStep('success');
      fetchFeed(true);
    } catch (err: any) {
      setError(err.message || "Failed to upload image");
      setStep('upload');
    } finally {
      setUploadIntent('ingest');
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      const isImage = file.type.startsWith('image/');
      if (uploadIntent === 'upload' && isImage) {
        await uploadImageFile(file);
        return;
      }
      const ext = file.name.split('.').pop()?.toLowerCase() || '';
      try {
        setStep('processing');
        setProgress(5);
        setError(null);
        setProcessingMeta({
          file: {
            fileName: file.name,
            fileSize: file.size,
            fileFormat: ext,
            inputSource: 'file',
          }
        });
        const content = await readFileContent(file);
        startProcessing(content, file.name);
      } catch (err: any) {
        setError(err.message || "Failed to read file");
        setStep('upload');
      }
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      const isImage = file.type.startsWith('image/');
      if (uploadIntent === 'upload' && isImage) {
        await uploadImageFile(file);
        return;
      }
      const ext = file.name.split('.').pop()?.toLowerCase() || '';
      try {
        setStep('processing');
        setProgress(5);
        setError(null);
        setProcessingMeta({
          file: {
            fileName: file.name,
            fileSize: file.size,
            fileFormat: ext,
            inputSource: 'file',
          }
        });
        const content = await readFileContent(file);
        startProcessing(content, file.name);
      } catch (err: any) {
        setError(err.message || "Failed to read file");
        setStep('upload');
      }
    }
  };

  const startProcessing = async (content: string, title: string = "New Knowledge") => {
    setStep('processing');
    setProgress(10);
    setError(null);

    // Set text input meta if no file meta exists
    setProcessingMeta(prev => prev.file ? prev : {
      file: {
        fileName: title,
        fileSize: new Blob([content]).size,
        fileFormat: content.startsWith('data:image') ? 'image' : 'text',
        inputSource: 'text',
      }
    });

    try {
      const response = await ingestService.ingest(content, title);
      setThreadId(response.thread_id);
      setProgress(100);

      // Merge backend processing metadata
      if (response.processing_metadata) {
        setProcessingMeta(prev => ({ ...prev, ...response.processing_metadata }));
      }

      if (response.status === 'awaiting_review') {
        const decisions = response.synthesis_decisions || [];
        const concepts = decisions.map((d: any, i: number) => ({
          id: i.toString(),
          name: d.new_concept.name,
          definition: d.new_concept.definition,
          domain: d.new_concept.domain || 'General',
          complexity: d.new_concept.complexity_score || 5,
          selected: d.recommended_action !== 'skip',
          exists: d.matches && d.matches.length > 0,
          original: d.new_concept
        }));
        setExtractedConcepts(concepts);
        setStep('review');
      } else {
        setStep('success');
      }
    } catch (error) {
      console.error('Ingestion failed:', error);
      setStep('upload');
    }
  };

  const handleSaveToGraph = async () => {
    if (!threadId) return;

    setStep('processing');
    setProgress(50);

    try {
      const approved = extractedConcepts
        .filter((c: ExtractedConcept) => c.selected)
        .map((c: ExtractedConcept) => (c as any).original);

      await ingestService.resume(threadId, approved);
      setStep('success');
    } catch (error) {
      console.error('Resume failed:', error);
      setStep('upload');
    }
  };

  const toggleConcept = (id: string) => {
    setExtractedConcepts((prev: ExtractedConcept[]) =>
      prev.map((c: ExtractedConcept) => c.id === id ? { ...c, selected: !c.selected } : c)
    );
  };

  const selectedCount = extractedConcepts.filter((c: ExtractedConcept) => c.selected).length;

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      <AnimatePresence mode="wait">
        {step === 'upload' && (
          <motion.div
            key="upload"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex-1 flex flex-col"
          >
            {/* Header */}
            <div className="text-center mb-6">
              <h2 className="font-heading text-xl font-bold text-white mb-1">Add Knowledge</h2>
              <p className="text-sm text-white/50">Upload notes, images, or paste text</p>
              {error && (
                <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl flex items-center justify-center gap-2 text-red-400 text-sm">
                  <AlertCircle className="w-4 h-4" />
                  {error}
                </div>
              )}
            </div>

            {/* Main Input Area */}
            <div className="flex-1 flex flex-col gap-4 min-h-0">

              {/* Input Modes: Text / YouTube / Chat Transcript / Upload */}
              {inputType === 'text' ? (
                <div className="flex-1 rounded-3xl border border-white/20 bg-white/[0.02] p-4 flex flex-col relative group hover:border-white/30 transition-colors">
                  <textarea
                    value={textInput}
                    onChange={(e) => setTextInput(e.target.value)}
                    placeholder="Paste your notes, lecture transcript, or type something to remember..."
                    className="w-full h-full bg-transparent border-none outline-none resize-none text-white/90 placeholder:text-white/20 font-mono text-sm leading-relaxed scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent pr-2"
                    autoFocus
                  />
                  <div className="absolute bottom-4 right-4 flex gap-2">
                    <button onClick={() => setInputType('upload')} className="px-3 py-1.5 rounded-lg bg-white/5 text-xs text-white/50 hover:bg-white/10 transition-colors">Cancel</button>
                    <button onClick={() => startProcessing(textInput)} disabled={!textInput.trim()} className="px-3 py-1.5 rounded-lg bg-[#B6FF2E] text-[#07070A] text-xs font-bold hover:bg-[#c5ff4d] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5">
                      <Upload className="w-3 h-3" /> Analyze
                    </button>
                  </div>
                </div>
              ) : inputType === 'youtube' ? (
                <div className="flex-1 rounded-3xl border border-red-500/30 bg-white/[0.02] p-6 flex flex-col items-center justify-center gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-red-500/20 flex items-center justify-center">
                    <Link2 className="w-7 h-7 text-red-400" />
                  </div>
                  <p className="text-sm text-white/70 text-center">YouTube links are stored as resources (not processed)</p>
                  <input
                    type="url"
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    placeholder="https://youtube.com/watch?v=..."
                    className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/30 focus:outline-none focus:border-red-500/50"
                    autoFocus
                  />
                  <div className="flex gap-2 w-full">
                    <button onClick={() => setInputType('upload')} className="flex-1 py-2.5 rounded-xl bg-white/5 text-white/70 text-sm hover:bg-white/10 transition-colors">Cancel</button>
                    <button
                      onClick={async () => {
                        if (!youtubeUrl.trim()) return;
                        setStep('processing');
                        setProgress(30);
                        setProcessingMeta({ file: { fileName: youtubeUrl, fileSize: 0, fileFormat: 'youtube', inputSource: 'url' } });
                        try {
                          await ingestService.ingestYoutube(youtubeUrl);
                          setProgress(100);
                          setStep('success');
                          setProcessingMeta(prev => ({ ...prev, concepts_extracted: 0 }));
                        } catch (err) {
                          setError("Failed to store YouTube link.");
                          setStep('upload');
                        }
                      }}
                      disabled={!youtubeUrl.trim()}
                      className="flex-1 py-2.5 rounded-xl bg-red-500 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-red-600 transition-colors"
                    >
                      Store Link
                    </button>
                  </div>
                </div>
              ) : inputType === 'chat-transcript' ? (
                <div className="flex-1 rounded-3xl border border-purple-500/30 bg-white/[0.02] p-4 flex flex-col relative group hover:border-purple-500/40 transition-colors">
                  <p className="text-[10px] uppercase tracking-wider text-purple-400/60 font-mono mb-2">Paste LLM Chat (Human/AI messages)</p>
                  <textarea
                    value={textInput}
                    onChange={(e) => setTextInput(e.target.value)}
                    placeholder={"Human: What is gradient descent?\n\nAI: Gradient descent is an optimization algorithm...\n\nHuman: How does it differ from SGD?\n\nAI: ..."}
                    className="w-full flex-1 bg-transparent border-none outline-none resize-none text-white/90 placeholder:text-white/20 font-mono text-sm leading-relaxed"
                    autoFocus
                  />
                  <div className="flex gap-2 pt-3">
                    <button onClick={() => { setInputType('upload'); setTextInput(''); }} className="flex-1 py-2.5 rounded-xl bg-white/5 text-white/70 text-sm hover:bg-white/10 transition-colors">Cancel</button>
                    <button
                      onClick={async () => {
                        if (!textInput.trim()) return;
                        setStep('processing');
                        setProgress(10);
                        setProcessingMeta({ file: { fileName: 'Chat Transcript', fileSize: new Blob([textInput]).size, fileFormat: 'chat', inputSource: 'text' } });
                        try {
                          const response = await ingestService.ingestChatTranscript(textInput);
                          if (response.processing_metadata) setProcessingMeta(prev => ({ ...prev, ...response.processing_metadata }));
                          setProgress(100);
                          setStep('success');
                        } catch (err) {
                          setError("Failed to process chat transcript.");
                          setStep('upload');
                        }
                      }}
                      disabled={!textInput.trim()}
                      className="flex-1 py-2.5 rounded-xl bg-purple-500 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-purple-600 transition-colors flex items-center justify-center gap-1.5"
                    >
                      <Brain className="w-3.5 h-3.5" /> Process Chat
                    </button>
                  </div>
                </div>
              ) : (
                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`
                    flex-1 rounded-3xl border-2 border-dashed flex flex-col items-center justify-center p-6 transition-all duration-300 cursor-pointer
                    ${isDragging
                      ? 'border-[#B6FF2E] bg-[#B6FF2E]/5'
                      : 'border-white/20 bg-white/[0.02] hover:border-white/30 hover:bg-white/[0.04]'
                    }
                  `}
                >
                  <input
                    type="file"
                    ref={fileInputRef}
                    className="hidden"
                    onChange={handleFileSelect}
                    accept=".md,.txt,.pdf,.jpg,.png,.jpeg,.docx,.doc"
                  />

                  <motion.div
                    animate={isDragging ? { scale: 1.1 } : { scale: 1 }}
                    className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4 border border-white/5"
                  >
                    <Upload className="w-8 h-8 text-[#B6FF2E]" />
                  </motion.div>
                  <p className="text-white font-medium mb-2">Drag & drop files here</p>
                  <p className="text-white/50 text-sm mb-4">or click to browse</p>

                  <div className="flex flex-wrap gap-1.5">
                    {['.md', '.txt', '.pdf', '.docx', 'Images'].map((format) => (
                      <span
                        key={format}
                        className="px-2 py-1 rounded-full text-xs font-mono bg-white/5 text-white/50 border border-white/5"
                      >
                        {format}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Quick Actions (Only show in upload mode) */}
              {inputType === 'upload' && (
                <div className="grid grid-cols-3 gap-2 shrink-0">
                  <QuickActionButton icon={FileText} label="Write Notes" onClick={() => setInputType('text')} />
                  <QuickActionButton
                    icon={Link2}
                    label="Article URL"
                    onClick={() => {
                      const url = prompt("Enter Article/Substack URL to analyze:");
                      if (url) {
                        setStep('processing');
                        setProgress(10);
                        setProcessingMeta({ file: { fileName: url, fileSize: 0, fileFormat: 'url', inputSource: 'url' } });
                        ingestService.ingestUrl(url)
                          .then(response => {
                            setThreadId(response.thread_id);
                            if (response.processing_metadata) setProcessingMeta(prev => ({ ...prev, ...response.processing_metadata }));
                            setProgress(100);
                            setStep('success');
                          })
                          .catch(err => {
                            console.error(err);
                            setError("Failed to fetch article. Ensure URL is publicly accessible.");
                            setStep('upload');
                          });
                      }
                    }}
                  />
                  <QuickActionButton icon={Youtube} label="YouTube" onClick={() => setInputType('youtube')} />
                  <QuickActionButton icon={MessageSquare} label="LLM Chat" onClick={() => setInputType('chat-transcript')} />
                  <QuickActionButton
                    icon={Image}
                    label="Images"
                    onClick={() => {
                      if (fileInputRef.current) {
                        fileInputRef.current.accept = "image/*";
                        setUploadIntent('upload');
                        fileInputRef.current.click();
                      }
                    }}
                  />
                </div>
              )}
            </div>
          </motion.div>
        )}

        {step === 'processing' && (
          <motion.div
            key="processing"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex-1 flex flex-col items-center justify-center"
          >
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
              className="w-16 h-16 rounded-full border-4 border-white/10 border-t-[#B6FF2E] mb-4"
            />
            <h3 className="font-heading text-lg font-bold text-white mb-2">
              {processingMeta.upload_only ? 'Uploading Image' : 'Analyzing Your Notes'}
            </h3>
            <div className="w-48 h-2 bg-white/10 rounded-full overflow-hidden mb-6">
              <motion.div
                className="h-full bg-gradient-to-r from-[#B6FF2E] to-[#2EFFE6]"
                initial={{ width: 0 }}
                animate={{ width: `${Math.min(progress, 100)}%` }}
              />
            </div>

            {/* Steps */}
            <div className="space-y-2 text-sm mb-6">
              <ProcessingStep label="Document parsed" completed={progress >= 20} />
              <ProcessingStep label="Content chunked" completed={progress >= 40} />
              <ProcessingStep label="Extracting concepts..." completed={progress >= 60} active={progress >= 40 && progress < 60} />
              <ProcessingStep label="Detecting conflicts" completed={progress >= 80} />
              <ProcessingStep label="Building relationships" completed={progress >= 100} />
            </div>

            <GeekoutPanel meta={processingMeta} />
          </motion.div>
        )}

        {step === 'review' && (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex-1 flex flex-col"
          >
            {/* Header */}
            <div className="mb-4">
              <h2 className="font-heading text-lg font-bold text-white mb-1">
                Review Extracted Concepts
              </h2>
              <p className="text-sm text-white/50">
                We found {extractedConcepts.length} concepts. Review before adding to your graph.
              </p>
            </div>

            {/* Concepts List */}
            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {extractedConcepts.map((concept: ExtractedConcept, i: number) => (
                <motion.div
                  key={concept.id}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={`
                    p-4 rounded-2xl border transition-all
                    ${concept.selected
                      ? 'bg-white/5 border-white/20'
                      : 'bg-transparent border-white/5 opacity-60'
                    }
                  `}
                >
                  <div className="flex items-start gap-3">
                    <button
                      onClick={() => toggleConcept(concept.id)}
                      className={`
                        w-5 h-5 rounded-md flex items-center justify-center transition-colors mt-0.5
                        ${concept.selected
                          ? 'bg-[#B6FF2E] text-[#07070A]'
                          : 'bg-white/10 text-transparent'
                        }
                      `}
                    >
                      <Check className="w-3 h-3" />
                    </button>

                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-medium text-white">{concept.name}</h4>
                        {concept.exists && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] bg-amber-500/20 text-amber-400">
                            Exists
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-white/60 mb-2">{concept.definition}</p>
                      <div className="flex items-center gap-3 text-xs text-white/40">
                        <span>{concept.domain}</span>
                        <span>•</span>
                        <span>Complexity: {concept.complexity}/10</span>
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>

            {/* Footer */}
            <div className="mt-4 pt-4 border-t border-white/10">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm text-white/60">
                  Selected: {selectedCount}/{extractedConcepts.length} concepts
                </span>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep('upload')}
                  className="flex-1 py-3 rounded-xl bg-white/5 text-white/70 font-medium hover:bg-white/10 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveToGraph}
                  disabled={selectedCount === 0}
                  className="flex-1 py-3 rounded-xl bg-[#B6FF2E] text-[#07070A] font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#c5ff4d] transition-colors flex items-center justify-center gap-2"
                >
                  <Save className="w-4 h-4" />
                  Save to Graph
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {step === 'success' && (
          <motion.div
            key="success"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex-1 flex flex-col items-center justify-center text-center"
          >
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 200, damping: 15 }}
              className="w-20 h-20 rounded-full bg-green-500/20 flex items-center justify-center mb-6"
            >
              <Check className="w-10 h-10 text-green-400" />
            </motion.div>

            <h2 className="font-heading text-2xl font-bold text-white mb-2">Success!</h2>
            <p className="text-white/60 mb-6">
              {processingMeta.upload_only ? 'Upload saved to your feed:' : 'Added to your knowledge graph:'}
            </p>

            {processingMeta.upload_only ? (
              <div className="text-sm text-white/80 mb-6">
                <span className="px-2 py-1 rounded-full bg-white/5 border border-white/10">
                  {processingMeta.upload_title || processingMeta.file?.fileName || 'Untitled Upload'}
                </span>
              </div>
            ) : (
              <div className="space-y-2 text-sm mb-6">
                <div className="flex items-center gap-2 text-white/80">
                  <div className="w-4 h-4 rounded-full bg-[#B6FF2E]/20 flex items-center justify-center">
                    <Check className="w-3 h-3 text-[#B6FF2E]" />
                  </div>
                  <span>{processingMeta.concepts_created || processingMeta.concepts_extracted || selectedCount} new concepts</span>
                </div>
                <div className="flex items-center gap-2 text-white/80">
                  <div className="w-4 h-4 rounded-full bg-[#2EFFE6]/20 flex items-center justify-center">
                    <Check className="w-3 h-3 text-[#2EFFE6]" />
                  </div>
                  <span>{processingMeta.relationships_created || 0} new relationships</span>
                </div>
                <div className="flex items-center gap-2 text-white/80">
                  <div className="w-4 h-4 rounded-full bg-[#9B59B6]/20 flex items-center justify-center">
                    <Sparkles className="w-4 h-4 text-white/40" />
                  </div>
                  <span>{processingMeta.flashcards_generated || 0} term cards generated</span>
                </div>
                {processingMeta.domains_detected && processingMeta.domains_detected.length > 0 && (
                  <div className="flex items-center gap-2 text-white/80">
                    <div className="w-4 h-4 rounded-full bg-amber-500/20 flex items-center justify-center">
                      <Check className="w-3 h-3 text-amber-400" />
                    </div>
                    <span>Domains: {processingMeta.domains_detected.join(', ')}</span>
                  </div>
                )}
              </div>
            )}

            {/* Geekout Summary on success — green=new, yellow=existing */}
            {!processingMeta.upload_only && processingMeta.concept_names && processingMeta.concept_names.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.3 }}
                className="w-full mb-6 p-3 rounded-xl bg-white/[0.03] border border-white/5"
              >
                <p className="text-[10px] uppercase tracking-wider text-white/30 mb-2 font-mono">Concepts Added to Graph</p>
                <div className="flex flex-wrap gap-1.5">
                  {processingMeta.concept_names.map((name, i) => {
                    const isExisting = processingMeta.related_concept_names?.some(
                      (r) => r.toLowerCase() === name.toLowerCase()
                    );
                    return (
                      <span
                        key={i}
                        className={`px-2 py-0.5 rounded-full text-[11px] border ${isExisting
                          ? 'bg-amber-400/10 text-amber-400/80 border-amber-400/20'
                          : 'bg-[#B6FF2E]/10 text-[#B6FF2E]/80 border-[#B6FF2E]/15'
                          }`}
                      >
                        {isExisting ? '↻ ' : '+ '}{name}
                      </span>
                    );
                  })}
                </div>
              </motion.div>
            )}

            <div className="flex gap-3 w-full">
              <button
                onClick={() => { setStep('upload'); setProcessingMeta({}); }}
                className="flex-1 py-3 rounded-xl bg-white/5 text-white/70 font-medium hover:bg-white/10 transition-colors"
              >
                Add More
              </button>
              <button
                onClick={() => { setStep('upload'); setProcessingMeta({}); setActiveTab('feed'); }}
                className="flex-1 py-3 rounded-xl bg-[#B6FF2E] text-[#07070A] font-medium hover:bg-[#c5ff4d] transition-colors"
              >
                Go to Feed
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ============================================================================
// Geekout Facts Panel (shown during processing)
// ============================================================================

function GeekoutPanel({ meta }: { meta: ProcessingMeta }) {
  const facts: { icon: any; label: string; value: string; color: string }[] = [];

  // File-level facts (available immediately)
  if (meta.file) {
    const f = meta.file;
    if (f.inputSource === 'url') {
      facts.push({ icon: Link2, label: 'Source', value: f.fileName.length > 35 ? f.fileName.slice(0, 35) + '...' : f.fileName, color: 'text-blue-400' });
    } else {
      facts.push({ icon: FileType, label: 'Format', value: getFormatLabel(f.fileFormat), color: 'text-[#B6FF2E]' });
      if (f.fileSize > 0) {
        facts.push({ icon: HardDrive, label: 'Size', value: formatFileSize(f.fileSize), color: 'text-[#2EFFE6]' });
      }
      if (f.pageCount && f.pageCount > 0) {
        facts.push({ icon: Layers, label: 'Pages', value: `${f.pageCount}`, color: 'text-amber-400' });
      }
    }
    if (f.inputSource === 'text') {
      facts.push({ icon: FileText, label: 'Input', value: 'Pasted Text', color: 'text-purple-400' });
    }
  }

  // Backend metadata (arrives after API response)
  if (meta.extraction_agent) {
    facts.push({ icon: Cpu, label: 'Agent', value: meta.extraction_agent, color: 'text-orange-400' });
  }
  if (meta.is_multimodal) {
    facts.push({ icon: Brain, label: 'Mode', value: 'Multimodal (Vision)', color: 'text-pink-400' });
  }
  if (meta.content_length) {
    facts.push({ icon: Database, label: 'Content', value: `${(meta.content_length / 1024).toFixed(1)} KB processed`, color: 'text-sky-400' });
  }
  if (meta.concepts_extracted) {
    facts.push({ icon: Zap, label: 'Concepts', value: `${meta.concepts_extracted} extracted`, color: 'text-[#B6FF2E]' });
  }
  if (meta.domains_detected && meta.domains_detected.length > 0) {
    facts.push({ icon: Layers, label: 'Domains', value: meta.domains_detected.join(', '), color: 'text-amber-400' });
  }
  if (meta.avg_complexity) {
    facts.push({ icon: Brain, label: 'Avg Complexity', value: `${meta.avg_complexity}/10`, color: 'text-purple-400' });
  }
  if (meta.existing_concepts_scanned) {
    facts.push({ icon: Database, label: 'Graph Scanned', value: `${meta.existing_concepts_scanned} existing concepts`, color: 'text-sky-400' });
  }
  if (meta.overlap_ratio !== undefined && meta.overlap_ratio > 0) {
    facts.push({ icon: GitBranch, label: 'Overlap', value: `${Math.round(meta.overlap_ratio * 100)}% with existing`, color: 'text-amber-400' });
  }
  if (meta.relationships_created) {
    facts.push({ icon: GitBranch, label: 'Relationships', value: `${meta.relationships_created} created`, color: 'text-[#2EFFE6]' });
  }
  if (meta.flashcards_generated) {
    facts.push({ icon: Zap, label: 'Term Cards', value: `${meta.flashcards_generated} generated`, color: 'text-pink-400' });
  }

  if (facts.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="w-full max-w-xs"
    >
      <div className="flex items-center gap-1.5 mb-2">
        <Cpu className="w-3 h-3 text-white/30" />
        <span className="text-[10px] uppercase tracking-wider text-white/30 font-mono">Processing Details</span>
      </div>
      <div className="rounded-xl bg-white/[0.03] border border-white/5 p-3 space-y-1.5">
        <AnimatePresence>
          {facts.map((fact, i) => (
            <motion.div
              key={fact.label}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.08 }}
              className="flex items-center gap-2 text-xs"
            >
              <fact.icon className={`w-3 h-3 ${fact.color} shrink-0`} />
              <span className="text-white/40 shrink-0">{fact.label}</span>
              <span className="text-white/10 shrink-0">|</span>
              <span className="text-white/70 truncate">{fact.value}</span>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Concept names as terminal-style streaming tags (green=new, yellow=existing) */}
        {meta.concept_names && meta.concept_names.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: facts.length * 0.08 + 0.1 }}
            className="pt-1.5 border-t border-white/5"
          >
            <p className="text-[9px] text-white/25 font-mono mb-1">
              <span className="text-[#B6FF2E]/60">●</span> new &nbsp;
              <span className="text-amber-400/60">●</span> existing
            </p>
            <div className="flex flex-wrap gap-1">
              {meta.concept_names.map((name, i) => {
                const isExisting = meta.related_concept_names?.some(
                  (r) => r.toLowerCase() === name.toLowerCase()
                );
                return (
                  <motion.span
                    key={name}
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: facts.length * 0.08 + 0.15 + i * 0.06 }}
                    className={`px-1.5 py-0.5 rounded text-[10px] font-mono border ${isExisting
                      ? 'bg-amber-400/10 text-amber-400/80 border-amber-400/20'
                      : 'bg-[#B6FF2E]/10 text-[#B6FF2E]/80 border-[#B6FF2E]/15'
                      }`}
                  >
                    {isExisting ? '↻ ' : '+ '}{name}
                  </motion.span>
                );
              })}
            </div>
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}

// Quick Action Button
function QuickActionButton({
  icon: Icon,
  label,
  onClick
}: {
  icon: any;
  label: string;
  onClick: () => void;
}) {
  return (
    <motion.button
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      className="flex flex-col items-center gap-2 p-4 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 transition-all"
    >
      <Icon className="w-6 h-6 text-[#B6FF2E]" />
      <span className="text-xs text-white/70">{label}</span>
    </motion.button>
  );
}

// Processing Step
function ProcessingStep({
  label,
  completed,
  active
}: {
  label: string;
  completed: boolean;
  active?: boolean;
}) {
  return (
    <div className={`flex items-center gap-2 ${completed ? 'text-green-400' : active ? 'text-[#B6FF2E]' : 'text-white/30'}`}>
      {completed ? (
        <Check className="w-4 h-4" />
      ) : active ? (
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
          className="w-4 h-4 border-2 border-current border-t-transparent rounded-full"
        />
      ) : (
        <div className="w-4 h-4 rounded-full border-2 border-current" />
      )}
      <span>{label}</span>
    </div>
  );
}
