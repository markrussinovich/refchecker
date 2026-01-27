"""
Thumbnail generation utilities for PDF and web page previews.

Uses PyMuPDF (fitz) to extract the first page of PDFs as thumbnails.
Thumbnails are cached on disk to avoid regeneration.
"""
import os
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Optional
import asyncio

logger = logging.getLogger(__name__)

# Default thumbnail cache directory
THUMBNAIL_CACHE_DIR = Path(tempfile.gettempdir()) / "refchecker_thumbnails"

# Thumbnail settings
THUMBNAIL_WIDTH = 200  # Target width in pixels for small thumbnails
THUMBNAIL_DPI = 150  # Higher DPI for sharper text rendering

# Preview settings (larger image for overlay view)
PREVIEW_WIDTH = 1600  # Target width in pixels for preview/overlay


def get_thumbnail_cache_path(source_identifier: str, check_id: Optional[int] = None) -> Path:
    """
    Get the cache path for a thumbnail.
    
    Args:
        source_identifier: A unique identifier for the source (URL, file path, or hash)
        check_id: Optional check ID for more unique naming
        
    Returns:
        Path to the thumbnail file (may not exist yet)
    """
    # Create cache directory if it doesn't exist
    THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create a hash of the source for the filename
    source_hash = hashlib.md5(source_identifier.encode()).hexdigest()[:12]
    
    if check_id:
        filename = f"thumb_{check_id}_{source_hash}.png"
    else:
        filename = f"thumb_{source_hash}.png"
    
    return THUMBNAIL_CACHE_DIR / filename


def get_preview_cache_path(source_identifier: str, check_id: Optional[int] = None) -> Path:
    """
    Get the cache path for a preview (larger image for overlay).
    
    Args:
        source_identifier: A unique identifier for the source (URL, file path, or hash)
        check_id: Optional check ID for more unique naming
        
    Returns:
        Path to the preview file (may not exist yet)
    """
    # Create cache directory if it doesn't exist
    THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create a hash of the source for the filename
    source_hash = hashlib.md5(source_identifier.encode()).hexdigest()[:12]
    
    if check_id:
        filename = f"preview_{check_id}_{source_hash}.png"
    else:
        filename = f"preview_{source_hash}.png"
    
    return THUMBNAIL_CACHE_DIR / filename


def generate_pdf_thumbnail(pdf_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Generate a thumbnail from the first page of a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path for the output thumbnail. If not provided,
                     uses the cache directory.
                     
    Returns:
        Path to the generated thumbnail, or None if generation failed
    """
    try:
        import fitz  # PyMuPDF
        
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        
        # Determine output path
        if output_path is None:
            output_path = str(get_thumbnail_cache_path(pdf_path))
        
        # Check if thumbnail already exists
        if os.path.exists(output_path):
            logger.debug(f"Thumbnail already exists: {output_path}")
            return output_path
        
        # Open the PDF
        doc = fitz.open(pdf_path)
        
        if len(doc) == 0:
            logger.warning(f"PDF has no pages: {pdf_path}")
            doc.close()
            return None
        
        # Get the first page
        page = doc[0]
        
        # Calculate zoom factor to get desired width
        page_width = page.rect.width
        zoom = THUMBNAIL_WIDTH / page_width
        
        # Create transformation matrix
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page to pixmap with higher quality
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Enhance contrast to make text darker/more readable
        try:
            from PIL import Image, ImageEnhance
            import io
            
            # Convert pixmap to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            # Increase contrast (1.3 = 30% more contrast)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.3)
            
            # Slightly increase sharpness
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.2)
            
            # Save enhanced image
            img.save(output_path, "PNG")
        except ImportError:
            # Fallback: save without enhancement if PIL not available
            pix.save(output_path)
        
        doc.close()
        
        logger.info(f"Generated thumbnail: {output_path} ({pix.width}x{pix.height})")
        return output_path
        
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Install with: pip install pymupdf")
        return None
    except Exception as e:
        logger.error(f"Error generating PDF thumbnail: {e}")
        return None


async def generate_pdf_thumbnail_async(pdf_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Async wrapper for PDF thumbnail generation.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path for the output thumbnail
        
    Returns:
        Path to the generated thumbnail, or None if generation failed
    """
    return await asyncio.to_thread(generate_pdf_thumbnail, pdf_path, output_path)


def generate_pdf_preview(pdf_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Generate a high-resolution preview from the first page of a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path for the output preview. If not provided,
                     uses the cache directory.
                     
    Returns:
        Path to the generated preview, or None if generation failed
    """
    try:
        import fitz  # PyMuPDF
        
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found: {pdf_path}")
            return None
        
        # Determine output path
        if output_path is None:
            output_path = str(get_preview_cache_path(pdf_path))
        
        # Check if preview already exists
        if os.path.exists(output_path):
            logger.debug(f"Preview already exists: {output_path}")
            return output_path
        
        # Open the PDF
        doc = fitz.open(pdf_path)
        
        if len(doc) == 0:
            logger.warning(f"PDF has no pages: {pdf_path}")
            doc.close()
            return None
        
        # Get the first page
        page = doc[0]
        
        # Calculate zoom factor to get desired width (larger for preview)
        page_width = page.rect.width
        zoom = PREVIEW_WIDTH / page_width
        
        # Create transformation matrix
        mat = fitz.Matrix(zoom, zoom)
        
        # Render page to pixmap with higher quality
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Enhance contrast to make text darker/more readable
        try:
            from PIL import Image, ImageEnhance
            import io
            
            # Convert pixmap to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            # Increase contrast (1.2 = 20% more contrast)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.2)
            
            # Slightly increase sharpness
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.1)
            
            # Save enhanced image
            img.save(output_path, "PNG", optimize=True)
        except ImportError:
            # Fallback: save without enhancement if PIL not available
            pix.save(output_path)
        
        doc.close()
        
        logger.info(f"Generated preview: {output_path} ({pix.width}x{pix.height})")
        return output_path
        
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Install with: pip install pymupdf")
        return None
    except Exception as e:
        logger.error(f"Error generating PDF preview: {e}")
        return None


async def generate_pdf_preview_async(pdf_path: str, output_path: Optional[str] = None) -> Optional[str]:
    """
    Async wrapper for PDF preview generation.
    
    Args:
        pdf_path: Path to the PDF file
        output_path: Optional path for the output preview
        
    Returns:
        Path to the generated preview, or None if generation failed
    """
    return await asyncio.to_thread(generate_pdf_preview, pdf_path, output_path)


def generate_arxiv_thumbnail(arxiv_id: str, check_id: Optional[int] = None) -> Optional[str]:
    """
    Generate a thumbnail for an ArXiv paper.
    
    Downloads the PDF and generates a thumbnail of the first page.
    
    Args:
        arxiv_id: ArXiv paper ID (e.g., "2311.12022")
        check_id: Optional check ID for cache naming
        
    Returns:
        Path to the generated thumbnail, or None if generation failed
    """
    try:
        import arxiv as arxiv_lib
        
        # Check if thumbnail already exists
        output_path = get_thumbnail_cache_path(f"arxiv_{arxiv_id}", check_id)
        if output_path.exists():
            logger.debug(f"ArXiv thumbnail already exists: {output_path}")
            return str(output_path)
        
        # Download the PDF to a temporary location
        pdf_dir = Path(tempfile.gettempdir()) / "refchecker_pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"arxiv_{arxiv_id}.pdf"
        
        # Check if PDF is already downloaded
        if not pdf_path.exists():
            logger.info(f"Downloading ArXiv PDF: {arxiv_id}")
            search = arxiv_lib.Search(id_list=[arxiv_id])
            paper = next(search.results())
            paper.download_pdf(filename=str(pdf_path))
        
        # Generate thumbnail from the PDF
        return generate_pdf_thumbnail(str(pdf_path), str(output_path))
        
    except Exception as e:
        logger.error(f"Error generating ArXiv thumbnail: {e}")
        return None


async def generate_arxiv_thumbnail_async(arxiv_id: str, check_id: Optional[int] = None) -> Optional[str]:
    """
    Async wrapper for ArXiv thumbnail generation.
    
    Args:
        arxiv_id: ArXiv paper ID
        check_id: Optional check ID for cache naming
        
    Returns:
        Path to the generated thumbnail, or None if generation failed
    """
    return await asyncio.to_thread(generate_arxiv_thumbnail, arxiv_id, check_id)


def generate_arxiv_preview(arxiv_id: str, check_id: Optional[int] = None) -> Optional[str]:
    """
    Generate a high-resolution preview for an ArXiv paper.
    
    Downloads the PDF and generates a preview of the first page.
    
    Args:
        arxiv_id: ArXiv paper ID (e.g., "2311.12022")
        check_id: Optional check ID for cache naming
        
    Returns:
        Path to the generated preview, or None if generation failed
    """
    try:
        import arxiv as arxiv_lib
        
        # Check if preview already exists
        output_path = get_preview_cache_path(f"arxiv_{arxiv_id}", check_id)
        if output_path.exists():
            logger.debug(f"ArXiv preview already exists: {output_path}")
            return str(output_path)
        
        # Download the PDF to a temporary location
        pdf_dir = Path(tempfile.gettempdir()) / "refchecker_pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"arxiv_{arxiv_id}.pdf"
        
        # Check if PDF is already downloaded
        if not pdf_path.exists():
            logger.info(f"Downloading ArXiv PDF: {arxiv_id}")
            search = arxiv_lib.Search(id_list=[arxiv_id])
            paper = next(search.results())
            paper.download_pdf(filename=str(pdf_path))
        
        # Generate preview from the PDF
        return generate_pdf_preview(str(pdf_path), str(output_path))
        
    except Exception as e:
        logger.error(f"Error generating ArXiv preview: {e}")
        return None


async def generate_arxiv_preview_async(arxiv_id: str, check_id: Optional[int] = None) -> Optional[str]:
    """
    Async wrapper for ArXiv preview generation.
    
    Args:
        arxiv_id: ArXiv paper ID
        check_id: Optional check ID for cache naming
        
    Returns:
        Path to the generated preview, or None if generation failed
    """
    return await asyncio.to_thread(generate_arxiv_preview, arxiv_id, check_id)


def get_text_thumbnail(check_id: int, text_preview: str = "", text_file_path: str = "") -> Optional[str]:
    """
    Generate a thumbnail for pasted text showing actual content.
    
    Creates an image with the first few lines of the text content.
    
    Args:
        check_id: Check ID for naming
        text_preview: Optional first few lines of text to display
        text_file_path: Optional path to the text file to read content from
        
    Returns:
        Path to the generated thumbnail, or None if generation failed
    """
    try:
        import fitz
        
        output_path = get_thumbnail_cache_path(f"text_{check_id}", check_id)
        
        if output_path.exists():
            return str(output_path)
        
        # Try to read text content from file
        text_content = text_preview
        if text_file_path and os.path.exists(text_file_path):
            try:
                with open(text_file_path, 'r', encoding='utf-8') as f:
                    text_content = f.read()
            except Exception as e:
                logger.warning(f"Could not read text file: {e}")
        
        # Clean up text content - remove excessive blank lines that cause rendering issues
        if text_content:
            # Normalize line endings and remove consecutive blank lines
            lines = text_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            # Keep only non-empty lines
            text_content = '\n'.join(line for line in lines if line.strip())
        
        # Create a document-like image with actual text content
        doc = fitz.open()
        page = doc.new_page(width=THUMBNAIL_WIDTH, height=int(THUMBNAIL_WIDTH * 1.4))
        
        # Fill with white/off-white background
        page.draw_rect(page.rect, color=(0.95, 0.95, 0.95), fill=(0.99, 0.99, 0.99))
        
        # Draw border
        page.draw_rect(page.rect, color=(0.8, 0.8, 0.8), width=1)
        
        # Draw actual text content if available
        margin = 10
        if text_content:
            # Create a text box for the content
            text_rect = fitz.Rect(margin, margin, THUMBNAIL_WIDTH - margin, int(THUMBNAIL_WIDTH * 1.4) - margin)
            
            # Truncate to first ~500 chars for thumbnail
            display_text = text_content[:500]
            if len(text_content) > 500:
                display_text += "..."
            
            # Insert text with small font
            page.insert_textbox(
                text_rect,
                display_text,
                fontsize=6,
                color=(0.2, 0.2, 0.2),
                fontname="helv"
            )
        else:
            # Fallback: Draw placeholder lines
            line_height = 12
            y = margin + 30
            
            # Draw a "T" icon at top
            text_rect = fitz.Rect(margin, margin, margin + 30, margin + 25)
            page.insert_textbox(text_rect, "T", fontsize=20, color=(0.4, 0.4, 0.6))
            
            for i in range(10):
                line_width = THUMBNAIL_WIDTH - 2 * margin
                if i % 3 == 2:
                    line_width = line_width * 0.7
                
                page.draw_line(
                    fitz.Point(margin, y),
                    fitz.Point(margin + line_width, y),
                    color=(0.7, 0.7, 0.7),
                    width=2
                )
                y += line_height
        
        # Render to pixmap and save
        pix = page.get_pixmap(alpha=False)
        pix.save(str(output_path))
        doc.close()
        
        logger.info(f"Generated text thumbnail: {output_path}")
        return str(output_path)
        
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed")
        return None
    except Exception as e:
        logger.error(f"Error generating text thumbnail: {e}")
        return None


def get_text_preview(check_id: int, text_preview: str = "", text_file_path: str = "") -> Optional[str]:
    """
    Generate a high-resolution preview for pasted text showing actual content.
    
    Creates a larger image (similar to PDF previews) with the text content.
    
    Args:
        check_id: Check ID for naming
        text_preview: Optional first few lines of text to display
        text_file_path: Optional path to the text file to read content from
        
    Returns:
        Path to the generated preview, or None if generation failed
    """
    try:
        import fitz
        
        output_path = get_preview_cache_path(f"text_{check_id}", check_id)
        
        if output_path.exists():
            return str(output_path)
        
        # Try to read text content from file
        text_content = text_preview
        if text_file_path and os.path.exists(text_file_path):
            try:
                with open(text_file_path, 'r', encoding='utf-8') as f:
                    text_content = f.read()
            except Exception as e:
                logger.warning(f"Could not read text file: {e}")
        
        # Clean up text content - remove excessive blank lines that cause rendering issues
        if text_content:
            # Normalize line endings and remove consecutive blank lines
            lines = text_content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            # Keep only non-empty lines
            text_content = '\n'.join(line for line in lines if line.strip())
        
        # Create a document-like image with actual text content at high resolution
        doc = fitz.open()
        page = doc.new_page(width=PREVIEW_WIDTH, height=int(PREVIEW_WIDTH * 1.4))
        
        # Fill with white/off-white background
        page.draw_rect(page.rect, color=(0.9, 0.9, 0.9), fill=(0.98, 0.98, 0.98))
        
        # Draw border
        page.draw_rect(page.rect, color=(0.7, 0.7, 0.7), width=2)
        
        # Draw actual text content if available
        margin = 40
        if text_content:
            # Create a text box for the content
            text_rect = fitz.Rect(margin, margin, PREVIEW_WIDTH - margin, int(PREVIEW_WIDTH * 1.4) - margin)
            
            # Truncate to first ~4000 chars for preview
            display_text = text_content[:4000]
            if len(text_content) > 4000:
                display_text += "\n\n..."
            
            # Insert text with readable font size
            page.insert_textbox(
                text_rect,
                display_text,
                fontsize=14,
                color=(0.15, 0.15, 0.15),
                fontname="helv"
            )
        else:
            # Fallback: Draw placeholder
            header_rect = fitz.Rect(margin, margin, PREVIEW_WIDTH - margin, margin + 60)
            page.insert_textbox(header_rect, "Pasted Text", fontsize=36, color=(0.3, 0.3, 0.5))
            
            # Draw placeholder lines
            line_height = 24
            y = margin + 100
            
            for i in range(20):
                line_width = PREVIEW_WIDTH - 2 * margin
                if i % 3 == 2:
                    line_width = line_width * 0.7
                
                page.draw_line(
                    fitz.Point(margin, y),
                    fitz.Point(margin + line_width, y),
                    color=(0.7, 0.7, 0.7),
                    width=3
                )
                y += line_height
        
        # Render to pixmap and save
        pix = page.get_pixmap(alpha=False)
        pix.save(str(output_path))
        doc.close()
        
        logger.info(f"Generated text preview: {output_path}")
        return str(output_path)
        
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed")
        return None
    except Exception as e:
        logger.error(f"Error generating text preview: {e}")
        return None


async def get_text_preview_async(check_id: int, text_preview: str = "", text_file_path: str = "") -> Optional[str]:
    """Async wrapper for text preview generation."""
    return await asyncio.to_thread(get_text_preview, check_id, text_preview, text_file_path)


async def get_text_thumbnail_async(check_id: int, text_preview: str = "", text_file_path: str = "") -> Optional[str]:
    """Async wrapper for text thumbnail generation."""
    return await asyncio.to_thread(get_text_thumbnail, check_id, text_preview, text_file_path)


def cleanup_old_thumbnails(max_age_days: int = 30):
    """
    Clean up old thumbnails from the cache.
    
    Args:
        max_age_days: Maximum age in days before thumbnails are deleted
    """
    try:
        import time
        
        if not THUMBNAIL_CACHE_DIR.exists():
            return
        
        max_age_seconds = max_age_days * 24 * 60 * 60
        current_time = time.time()
        
        for thumb_path in THUMBNAIL_CACHE_DIR.glob("thumb_*.png"):
            try:
                file_age = current_time - thumb_path.stat().st_mtime
                if file_age > max_age_seconds:
                    thumb_path.unlink()
                    logger.debug(f"Deleted old thumbnail: {thumb_path}")
            except Exception as e:
                logger.warning(f"Error deleting thumbnail {thumb_path}: {e}")
                
    except Exception as e:
        logger.error(f"Error cleaning up thumbnails: {e}")
