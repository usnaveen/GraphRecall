import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload, Image, FileText, Link2, Check,
  Save, AlertCircle
} from 'lucide-react';
import * as pdfjsLib from 'pdfjs-dist';
import { ingestService } from '../services/api';

// Set PDF Worker - interacting with CDN to avoid Vite build complexity
pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.js`;

type CreateStep = 'upload' | 'processing' | 'review' | 'success';

interface ExtractedConcept {
  id: string;
  name: string;
  definition: string;
  domain?: string;
  complexity?: number;
  selected: boolean;
  exists?: boolean;
}

export function CreateScreen() {
  const [step, setStep] = useState<CreateStep>('upload');
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [extractedConcepts, setExtractedConcepts] = useState<ExtractedConcept[]>([]);
  const [inputType, setInputType] = useState<'upload' | 'text'>('upload');
  const [textInput, setTextInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const readFileContent = async (file: File): Promise<string> => {
    const extension = file.name.split('.').pop()?.toLowerCase();

    if (extension === 'pdf') {
      try {
        const arrayBuffer = await file.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        let fullText = '';

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

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      try {
        setStep('processing');
        setProgress(5);
        setError(null);
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
      try {
        setStep('processing');
        setProgress(5);
        setError(null);
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

    try {
      const response = await ingestService.ingest(content, title);
      setThreadId(response.thread_id);
      setProgress(100);

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

              {/* Toggle: Upload vs Text */}
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
                    <button
                      onClick={() => setInputType('upload')}
                      className="px-3 py-1.5 rounded-lg bg-white/5 text-xs text-white/50 hover:bg-white/10 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => startProcessing(textInput)}
                      disabled={!textInput.trim()}
                      className="px-3 py-1.5 rounded-lg bg-[#B6FF2E] text-[#07070A] text-xs font-bold hover:bg-[#c5ff4d] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5"
                    >
                      <Upload className="w-3 h-3" />
                      Analyze
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
                    accept=".md,.txt,.pdf,.jpg,.png,.jpeg"
                  />

                  <motion.div
                    animate={isDragging ? { scale: 1.1 } : { scale: 1 }}
                    className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4 border border-white/5"
                  >
                    <Upload className="w-8 h-8 text-[#B6FF2E]" />
                  </motion.div>
                  <p className="text-white font-medium mb-2">Drag & drop files here</p>
                  <p className="text-white/50 text-sm mb-4">or click to browse</p>

                  <div className="flex gap-2">
                    {['.md', '.txt', '.pdf', 'Images'].map((format) => (
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

              {/* Quick Actions (Only show if not typing text) */}
              {inputType !== 'text' && (
                <div className="grid grid-cols-3 gap-3 h-24 shrink-0">
                  <QuickActionButton
                    icon={Image}
                    label="Images"
                    onClick={() => {
                      if (fileInputRef.current) {
                        fileInputRef.current.accept = "image/*";
                        fileInputRef.current.click();
                      }
                    }}
                  />
                  <QuickActionButton
                    icon={FileText}
                    label="Write Notes"
                    onClick={() => setInputType('text')}
                  />
                  <QuickActionButton
                    icon={Link2}
                    label="Import URL"
                    onClick={() => {
                      const url = prompt("Enter URL to analyze:");
                      if (url) startProcessing(`Source URL: ${url}`);
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
              className="w-20 h-20 rounded-full border-4 border-white/10 border-t-[#B6FF2E] mb-6"
            />
            <h3 className="font-heading text-lg font-bold text-white mb-2">
              Analyzing Your Notes
            </h3>
            <div className="w-48 h-2 bg-white/10 rounded-full overflow-hidden mb-4">
              <motion.div
                className="h-full bg-gradient-to-r from-[#B6FF2E] to-[#2EFFE6]"
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
              />
            </div>

            {/* Steps */}
            <div className="space-y-2 text-sm">
              <ProcessingStep label="Document parsed" completed={progress >= 20} />
              <ProcessingStep label="Content chunked" completed={progress >= 40} />
              <ProcessingStep label="Extracting concepts..." completed={progress >= 60} active={progress >= 40 && progress < 60} />
              <ProcessingStep label="Detecting conflicts" completed={progress >= 80} />
              <ProcessingStep label="Building relationships" completed={progress >= 100} />
            </div>
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
            <p className="text-white/60 mb-6">Added to your knowledge graph:</p>

            <div className="space-y-2 text-sm mb-8">
              <div className="flex items-center gap-2 text-white/80">
                <div className="w-4 h-4 rounded-full bg-[#B6FF2E]/20 flex items-center justify-center">
                  <Check className="w-3 h-3 text-[#B6FF2E]" />
                </div>
                <span>{selectedCount} new concepts</span>
              </div>
              <div className="flex items-center gap-2 text-white/80">
                <div className="w-4 h-4 rounded-full bg-[#2EFFE6]/20 flex items-center justify-center">
                  <Check className="w-3 h-3 text-[#2EFFE6]" />
                </div>
                <span>12 new relationships</span>
              </div>
              <div className="flex items-center gap-2 text-white/80">
                <div className="w-4 h-4 rounded-full bg-[#9B59B6]/20 flex items-center justify-center">
                  <Check className="w-3 h-3 text-[#9B59B6]" />
                </div>
                <span>2 concepts merged with existing</span>
              </div>
            </div>

            <div className="flex gap-3 w-full">
              <button
                onClick={() => setStep('upload')}
                className="flex-1 py-3 rounded-xl bg-white/5 text-white/70 font-medium hover:bg-white/10 transition-colors"
              >
                Add More
              </button>
              <button
                onClick={() => setStep('upload')}
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

// Quick Action Button
function QuickActionButton({
  icon: Icon,
  label,
  onClick
}: {
  icon: React.ElementType;
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
