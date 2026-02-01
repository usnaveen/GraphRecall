import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Upload, Image, FileText, Link2, Check, 
  Save
} from 'lucide-react';

type CreateStep = 'upload' | 'processing' | 'review' | 'success';

interface ExtractedConcept {
  id: string;
  name: string;
  definition: string;
  domain: string;
  complexity: number;
  selected: boolean;
  exists?: boolean;
}

export function CreateScreen() {
  const [step, setStep] = useState<CreateStep>('upload');
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [extractedConcepts, setExtractedConcepts] = useState<ExtractedConcept[]>([
    {
      id: '1',
      name: 'Neural Network',
      definition: 'A computing system inspired by biological neural networks that can learn patterns from data.',
      domain: 'Machine Learning',
      complexity: 7,
      selected: true,
    },
    {
      id: '2',
      name: 'Backpropagation',
      definition: 'Algorithm for calculating gradients by propagating errors backwards through layers.',
      domain: 'Machine Learning',
      complexity: 8,
      selected: true,
      exists: true,
    },
    {
      id: '3',
      name: 'Input Layer',
      definition: 'First layer that receives raw data in a neural network.',
      domain: 'Machine Learning',
      complexity: 3,
      selected: true,
    },
    {
      id: '4',
      name: 'Gradient',
      definition: 'A vector of partial derivatives indicating the direction of steepest ascent.',
      domain: 'Mathematics',
      complexity: 6,
      selected: false,
    },
  ]);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    startProcessing();
  };

  const startProcessing = () => {
    setStep('processing');
    setProgress(0);
    
    const interval = setInterval(() => {
      setProgress(prev => {
        if (prev >= 100) {
          clearInterval(interval);
          setStep('review');
          return 100;
        }
        return prev + 10;
      });
    }, 300);
  };

  const toggleConcept = (id: string) => {
    setExtractedConcepts(prev => 
      prev.map(c => c.id === id ? { ...c, selected: !c.selected } : c)
    );
  };

  const selectedCount = extractedConcepts.filter(c => c.selected).length;

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
              <p className="text-sm text-white/50">Upload your notes and we&apos;ll extract concepts</p>
            </div>

            {/* Drop Zone */}
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`
                flex-1 min-h-[200px] rounded-3xl border-2 border-dashed flex flex-col items-center justify-center p-6 transition-all duration-300
                ${isDragging 
                  ? 'border-[#B6FF2E] bg-[#B6FF2E]/5' 
                  : 'border-white/20 bg-white/[0.02] hover:border-white/30'
                }
              `}
            >
              <motion.div
                animate={isDragging ? { scale: 1.1 } : { scale: 1 }}
                className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4"
              >
                <Upload className="w-8 h-8 text-[#B6FF2E]" />
              </motion.div>
              <p className="text-white font-medium mb-2">Drag & drop files here</p>
              <p className="text-white/50 text-sm mb-4">or tap to browse</p>
              
              {/* Format Pills */}
              <div className="flex gap-2">
                {['.md', '.txt', '.pdf', '.jpg'].map((format) => (
                  <span 
                    key={format}
                    className="px-2 py-1 rounded-full text-xs font-mono bg-white/5 text-white/50"
                  >
                    {format}
                  </span>
                ))}
              </div>
            </div>

            {/* Quick Actions */}
            <div className="mt-6">
              <p className="text-xs text-white/40 text-center mb-4">— OR —</p>
              <div className="grid grid-cols-3 gap-3">
                <QuickActionButton
                  icon={Image}
                  label="Screenshot"
                  onClick={startProcessing}
                />
                <QuickActionButton
                  icon={FileText}
                  label="Write Notes"
                  onClick={startProcessing}
                />
                <QuickActionButton
                  icon={Link2}
                  label="Import URL"
                  onClick={startProcessing}
                />
              </div>
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
              {extractedConcepts.map((concept, i: number) => (
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
                  onClick={() => setStep('success')}
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
