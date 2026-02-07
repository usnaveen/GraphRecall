import React from 'react';
import katex from 'katex';

/**
 * MathText: Renders text that may contain LaTeX math expressions.
 *
 * Supports:
 *   - Inline math: $...$
 *   - Display math: $$...$$
 *
 * Falls back to rendering raw text if KaTeX fails.
 */

interface MathTextProps {
  children: string;
  className?: string;
}

export const MathText: React.FC<MathTextProps> = ({ children, className }) => {
  if (!children) return null;

  // If no $ signs at all, skip processing entirely
  if (!children.includes('$')) {
    return <span className={className}>{children}</span>;
  }

  // Split on display math ($$...$$) and inline math ($...$)
  const parts: React.ReactNode[] = [];
  const regex = /\$\$([\s\S]*?)\$\$|\$((?!\$).*?)\$/g;
  let lastIndex = 0;
  let match;
  let key = 0;

  while ((match = regex.exec(children)) !== null) {
    // Add text before this match
    if (match.index > lastIndex) {
      parts.push(
        <span key={key++}>{children.slice(lastIndex, match.index)}</span>
      );
    }

    const displayMath = match[1]; // $$...$$ group
    const inlineMath = match[2]; // $...$ group
    const mathContent = displayMath ?? inlineMath;
    const isDisplay = displayMath !== undefined;

    if (mathContent) {
      try {
        const html = katex.renderToString(mathContent, {
          throwOnError: false,
          displayMode: isDisplay,
        });
        parts.push(
          <span
            key={key++}
            className={isDisplay ? 'block my-2' : 'inline'}
            dangerouslySetInnerHTML={{ __html: html }}
          />
        );
      } catch {
        // Fallback: show raw LaTeX
        parts.push(
          <code key={key++} className="text-[#B6FF2E] bg-white/10 px-1 rounded text-xs">
            {mathContent}
          </code>
        );
      }
    }

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < children.length) {
    parts.push(<span key={key++}>{children.slice(lastIndex)}</span>);
  }

  return <span className={className}>{parts}</span>;
};
