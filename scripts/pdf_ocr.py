#!/usr/bin/env python3
"""
Local PDF OCR Script using Marker

This script extracts text from image-heavy/scanned PDFs using the Marker library,
which uses Surya for OCR and supports M1 Mac MPS acceleration.

Usage:
    python scripts/pdf_ocr.py /path/to/textbook.pdf
    python scripts/pdf_ocr.py /path/to/textbook.pdf --output /path/to/output.md

Requirements (install once):
    pip install marker-pdf

On M1 Mac, Marker will automatically use MPS for GPU acceleration.
"""

import argparse
import os
import sys
import time
from pathlib import Path


def check_dependencies():
    """Check if required packages are installed."""
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        return True
    except ImportError:
        print("=" * 60)
        print("ERROR: Marker is not installed.")
        print("Please install it with: uv add marker-pdf")
        print("Or: pip install marker-pdf")
        print("=" * 60)
        return False


def extract_text_from_pdf(
    pdf_path: str,
    output_path: str = None,
    verbose: bool = True
) -> str:
    """
    Extract text from a PDF file using Marker.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path to save the Markdown output
        verbose: If True, print progress updates
    
    Returns:
        Extracted text as Markdown string
    """
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    if verbose:
        print(f"\n📖 Processing: {pdf_path.name}")
        print(f"   Size: {pdf_path.stat().st_size / 1024 / 1024:.1f} MB")
        print("-" * 50)
    
    start_time = time.time()
    
    # Initialize models (this takes a moment on first run)
    if verbose:
        print("🔧 Loading OCR models (first run may take a few minutes)...")
    
    model_dict = create_model_dict()
    converter = PdfConverter(artifact_dict=model_dict)
    
    if verbose:
        print("📝 Extracting text from PDF...")
    
    # Convert PDF to Markdown (Marker v1.10+ API)
    rendered = converter(str(pdf_path))
    
    # Determine output path
    if output_path is None:
        output_path = pdf_path.with_suffix(".md")
    output_path = Path(output_path)
    
    # Extract text and images
    text, _, images = text_from_rendered(rendered)
    
    # Save images if any were extracted
    if images:
        images_dir = output_path.parent / (output_path.stem + "_images")
        images_dir.mkdir(exist_ok=True)
        
        for img_name, img_data in images.items():
            img_path = images_dir / img_name
            if hasattr(img_data, 'save'):
                # PIL Image
                img_data.save(str(img_path))
            elif isinstance(img_data, bytes):
                # Raw bytes
                img_path.write_bytes(img_data)
        
        if verbose:
            print(f"   Images extracted: {len(images)} -> {images_dir}")
    
    elapsed = time.time() - start_time
    
    if verbose:
        print(f"\n✅ Extraction complete!")
        print(f"   Time: {elapsed:.1f} seconds")
        print(f"   Output length: {len(text):,} characters")
    
    # Save to file
    output_path.write_text(text, encoding="utf-8")
    
    if verbose:
        print(f"   Saved to: {output_path}")
    
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from PDF books using local OCR (Marker + Surya)"
    )
    parser.add_argument(
        "pdf_path",
        type=str,
        help="Path to the PDF file"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output Markdown file path (default: same name as PDF with .md extension)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    try:
        markdown_text = extract_text_from_pdf(
            pdf_path=args.pdf_path,
            output_path=args.output,
            verbose=not args.quiet
        )
        
        print("\n" + "=" * 60)
        print("🎉 SUCCESS! You can now upload the .md file to GraphRecall")
        print("=" * 60)
        
        # Show preview
        preview = markdown_text[:500].strip()
        if len(markdown_text) > 500:
            preview += "..."
        print(f"\n📄 Preview:\n{preview}\n")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during extraction: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
