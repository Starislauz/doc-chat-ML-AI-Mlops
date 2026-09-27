"""Document processing service - PDF, TXT, MD, DOCX, and IMAGE parsing and chunking"""

import os
import re
import unicodedata
from typing import List, Tuple, Dict
import PyPDF2
from io import BytesIO
from PIL import Image
import pytesseract

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class DocumentProcessor:
    """Service for processing and chunking documents"""
    
    def __init__(self):
        """Initialize document processor"""
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        logger.info("DocumentProcessor initialized")
    
    def process_document(self, file_path: str, file_type: str) -> Tuple[str, List[str]]:
        """
        Process a document and extract text
        
        Args:
            file_path: Path to the document file
            file_type: File extension (.pdf, .txt, .md, .docx, .doc, .png, .jpg, .jpeg)
        
        Returns:
            Tuple of (full_text, chunks)
        """
        logger.info(f"Processing document: {file_path} (type: {file_type})")
        
        if file_type == ".pdf":
            text = self._extract_pdf_text(file_path)
        elif file_type in [".txt", ".md"]:
            text = self._extract_text_file(file_path)
        elif file_type in [".docx", ".doc"]:
            text = self._extract_docx_text(file_path)
        elif file_type.lower() in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
            text = self._extract_image_text(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        # Normalise unicode first: NFKC turns ligatures (ﬁ, ﬂ) into plain
        # letters, which otherwise break keyword matching and look like typos.
        text = self._normalize_text(text)
        
        # Create chunks
        chunks = self._create_chunks(text)
        
        logger.info(f"Extracted {len(text)} characters, created {len(chunks)} chunks")
        
        return text, chunks
    
    def _extract_pdf_text(self, file_path: str) -> str:
        """
        Extract text from PDF file (handles both text-based and scanned PDFs)
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            Extracted text
        """
        text = ""
        
        # Layout-aware extraction first. Some PDFs position every glyph
        # individually, which makes naive extractors insert spaces inside words
        # ("Unof ficial", "Studen t name", "c ourses"). pdfplumber with a tight
        # x_tolerance merges those glyph runs back into real words.
        plumber_text = self._extract_pdf_text_pdfplumber(file_path)
        
        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                
                logger.info(f"Processing PDF with {num_pages} pages")
                
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        text += f"\n--- Page {page_num + 1} ---\n{page_text}"
                        logger.info(f"Extracted {len(page_text)} chars from page {page_num + 1}")
                    else:
                        logger.warning(f"Page {page_num + 1} has no extractable text (might be scanned/image-based)")
                
                # If no text was extracted, this might be a scanned PDF
                if not text.strip():
                    logger.warning("⚠️ No text found in PDF - this appears to be a scanned/image-based PDF")
                    logger.info("Attempting to extract text using Gemini Vision AI for scanned PDF...")
                    
                    try:
                        # Try to convert PDF pages to images and use OCR
                        text = self._extract_scanned_pdf_text(file_path, pdf_reader)
                        if text and text.strip():
                            logger.info(f"✓ Successfully extracted {len(text)} chars from scanned PDF using Vision AI")
                        else:
                            logger.warning("Vision AI extraction returned empty text")
                    except Exception as ocr_error:
                        logger.error(f"Failed to process scanned PDF: {str(ocr_error)}")
                        # Return a placeholder so the document still gets indexed
                        return f"[Scanned PDF: {os.path.basename(file_path)} - Text extraction failed. Please try uploading as images instead.]"
        
        except Exception as e:
            logger.error(f"Error extracting PDF text: {str(e)}")
            raise ValueError(f"Failed to process PDF: {str(e)}")
        
        # Keep whichever extraction is less fragmented (see _text_quality).
        # Measured comparison, not a guess: the scores are logged either way.
        if plumber_text:
            plumber_quality = self._text_quality(plumber_text)
            pypdf_quality = self._text_quality(text)
            if plumber_quality >= pypdf_quality:
                logger.info(
                    f"PDF text: using pdfplumber (quality {plumber_quality:.3f} "
                    f"vs PyPDF2 {pypdf_quality:.3f})"
                )
                text = plumber_text
            else:
                logger.info(
                    f"PDF text: using PyPDF2 (quality {pypdf_quality:.3f} "
                    f"vs pdfplumber {plumber_quality:.3f})"
                )
        
        fragments = self.find_fragments(text, limit=3)
        if fragments:
            logger.warning(
                f"Extracted PDF text still shows {len(fragments)}+ suspected "
                f"mid-word splits, e.g. {fragments}"
            )
        
        return text.strip()
    
    # ---------------------------------------------------------------- helpers
    # Short tokens that are legitimate English words (excluded from the
    # fragmentation check so normal prose is not flagged).
    _SHORT_OK = {
        "a", "i", "am", "an", "as", "at", "be", "by", "do", "go", "he",
        "if", "in", "is", "it", "me", "my", "no", "of", "ok", "on", "or",
        "so", "to", "up", "us", "we",
    }
    
    @staticmethod
    def _normalize_text(text: str) -> str:
        """NFKC-normalise text: ligatures (ﬁ, ﬂ) become plain letters."""
        return unicodedata.normalize("NFKC", text) if text else text
    
    @classmethod
    def _text_quality(cls, text: str) -> float:
        """Score extracted text from 0..1 (higher = fewer mid-word splits).

        Fragmented extractions ("Unof ficial", "c ourses", "Studen t") produce
        many short lowercase shards that are not real English words. Real prose
        produces very few.
        """
        tokens = re.findall(r"[A-Za-z]+", text or "")
        if not tokens:
            return 0.0
        shards = sum(
            1 for token in tokens
            if len(token) <= 2 and token.islower() and token not in cls._SHORT_OK
        )
        return 1.0 - (shards / len(tokens))
    
    @classmethod
    def find_fragments(cls, text: str, limit: int = 20) -> List[str]:
        """Return examples of suspected mid-word splits, for diagnostics."""
        examples: List[str] = []
        for match in re.finditer(r"\b[A-Za-z]{2,}\s+([a-z]{1,2})\b", text or ""):
            shard = match.group(1)
            if shard in cls._SHORT_OK:  # legitimate short word, not a shard
                continue
            start = max(0, match.start() - 25)
            snippet = text[start:match.end() + 25].replace("\n", " ").strip()
            examples.append(snippet)
            if len(examples) >= limit:
                break
        return examples
    
    def _extract_pdf_text_pdfplumber(self, file_path: str) -> str:
        """Extract PDF text with pdfplumber, tuning character tolerance.

        Tries several x_tolerance values per page and keeps the cleanest result,
        which repairs PDFs whose glyphs are individually positioned.
        """
        try:
            import pdfplumber
        except ImportError:
            logger.info("pdfplumber not installed - skipping layout-aware extraction")
            return ""
        
        try:
            parts: List[str] = []
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    best = ""
                    for tolerance in (1, 2.5, 5):
                        try:
                            candidate = page.extract_text(x_tolerance=tolerance) or ""
                        except Exception:
                            candidate = ""
                        if candidate and self._text_quality(candidate) > self._text_quality(best):
                            best = candidate
                        if best and self._text_quality(best) > 0.9:
                            break
                    if best.strip():
                        parts.append(f"\n--- Page {page_number} ---\n{best}")
            
            text = "".join(parts).strip()
            if text:
                logger.info(
                    f"pdfplumber extracted {len(text)} chars "
                    f"(quality {self._text_quality(text):.3f})"
                )
            return text
        except Exception as exc:
            logger.warning(f"pdfplumber extraction failed: {exc}")
            return ""
    
    def _extract_docx_text(self, file_path: str) -> str:
        """
        Extract text from DOCX file
        
        Args:
            file_path: Path to DOCX file
        
        Returns:
            Extracted text
        """
        try:
            from docx import Document
            
            doc = Document(file_path)
            text = ""
            
            # Extract paragraphs
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text += paragraph.text + "\n\n"
            
            # Extract tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text for cell in row.cells)
                    text += row_text + "\n"
                text += "\n"
            
            return text.strip()
        
        except ImportError:
            logger.error("python-docx library not installed")
            raise ValueError("DOCX processing not available. Please install python-docx.")
        except Exception as e:
            logger.error(f"Error extracting DOCX text: {str(e)}")
            raise ValueError(f"Failed to process DOCX: {str(e)}")
    
    def _extract_text_file(self, file_path: str) -> str:
        """
        Extract text from TXT or MD file
        
        Args:
            file_path: Path to text file
        
        Returns:
            File contents
        """
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                text = file.read()
            return text.strip()
        except Exception as e:
            logger.error(f"Error reading text file: {str(e)}")
            raise ValueError(f"Failed to read file: {str(e)}")
    
    def _extract_image_text(self, file_path: str) -> str:
        """
        Extract text from image file using OCR (Tesseract) or fallback to Gemini Vision
        
        Args:
            file_path: Path to image file
        
        Returns:
            Extracted text
        """
        try:
            # Try Tesseract OCR first (if available)
            image = Image.open(file_path)
            tesseract_available = False
            
            try:
                # Check if Tesseract is available
                text = pytesseract.image_to_string(image, lang='eng')
                tesseract_available = True
                
                if text.strip():
                    logger.info(f"✓ Extracted {len(text)} characters from image using Tesseract OCR")
                    return text.strip()
                else:
                    logger.info(f"Tesseract found no text, trying Gemini Vision for: {file_path}")
                    return self._fallback_image_description(file_path)
            
            except pytesseract.TesseractNotFoundError:
                logger.info("⚠️ Tesseract OCR not installed - using Gemini Vision AI (this is normal)")
                logger.info("To install Tesseract: https://github.com/UB-Mannheim/tesseract/wiki")
                return self._fallback_image_description(file_path)
            except Exception as ocr_error:
                error_msg = str(ocr_error)
                if "tesseract is not installed" in error_msg.lower() or "tesseract_cmd" in error_msg.lower():
                    logger.info("⚠️ Tesseract not configured - using Gemini Vision AI")
                else:
                    logger.warning(f"Tesseract OCR failed: {error_msg}, using Gemini Vision fallback")
                return self._fallback_image_description(file_path)
        
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}", exc_info=True)
            raise ValueError(f"Failed to process image: {str(e)}")
    
    def _fallback_image_description(self, file_path: str) -> str:
        """
        Fallback method for image processing when Tesseract is not available
        Uses Gemini Vision API to generate description and extract text
        
        Args:
            file_path: Path to image file
        
        Returns:
            Image description text with any visible text transcribed
        """
        try:
            # Try using Gemini Vision for image description
            from .llm_service import llm_service
            
            logger.info(f"🤖 Using Gemini Vision AI to read image: {file_path}")
            caption = llm_service.generate_image_caption(file_path)
            
            if not caption or "failed" in caption.lower():
                logger.error(f"Gemini Vision returned empty or failed caption: {caption}")
                return f"[Image file: {os.path.basename(file_path)} - Could not extract content. Error: {caption}]"
            
            logger.info(f"✓ Successfully extracted image content using Gemini Vision ({len(caption)} chars)")
            
            # Format the response
            result = f"[Image: {os.path.basename(file_path)}]\n\n{caption}"
            return result
        
        except Exception as e:
            logger.error(f"❌ Gemini Vision also failed: {str(e)}", exc_info=True)
            # Ultimate fallback - just note the image exists
            return f"[Image file: {os.path.basename(file_path)} - Visual content could not be extracted. Error: {str(e)}. Install Tesseract OCR for local text extraction, or check your Gemini API connection.]"
    
    def _extract_scanned_pdf_text(self, file_path: str, pdf_reader: PyPDF2.PdfReader) -> str:
        """
        Extract text from scanned PDF using Gemini Vision AI
        
        Args:
            file_path: Path to PDF file
            pdf_reader: PyPDF2 reader object
        
        Returns:
            Extracted text from all pages
        """
        try:
            from .llm_service import llm_service
            
            # SIMPLE APPROACH: Send PDF directly to Gemini for analysis
            logger.info("🤖 Using Gemini AI to analyze PDF document...")
            
            try:
                # Gemini can read PDFs directly!
                from google import genai
                
                # Upload the PDF file
                uploaded_file = llm_service.client.files.upload(path=file_path)
                logger.info(f"Uploaded PDF to Gemini: {uploaded_file.name}")
                
                # Ask Gemini to extract all text
                prompt = """Extract ALL text from this document. 
                
Please transcribe EVERY word, number, and piece of text visible in this PDF document.
Maintain the original structure and formatting as much as possible.
Include:
- All headings and titles
- All paragraphs and body text
- All bullet points and lists
- All tables and data
- All captions and labels
- All page numbers and headers/footers

Start transcription now:"""
                
                response = llm_service.client.models.generate_content(
                    model=llm_service.client._model_name,
                    contents=[prompt, uploaded_file]
                )
                
                # Clean up uploaded file
                try:
                    llm_service.client.files.delete(name=uploaded_file.name)
                except:
                    pass
                
                extracted_text = response.text
                logger.info(f"✓ Gemini extracted {len(extracted_text)} characters from PDF")
                
                return extracted_text
                
            except Exception as gemini_error:
                logger.warning(f"Gemini PDF upload failed: {str(gemini_error)}")
                logger.info("Trying alternative method with pdf2image...")
            
            # FALLBACK: Try using pdf2image if available
            try:
                from pdf2image import convert_from_path
                logger.info("Using pdf2image to convert PDF pages to images...")
                
                # Convert PDF to images
                images = convert_from_path(file_path, dpi=200)
                logger.info(f"Converted PDF to {len(images)} images")
                
                # Process each page with Gemini Vision
                all_text = ""
                
                for page_num, image in enumerate(images, 1):
                    # Save temporary image
                    temp_image_path = f"{file_path}_temp_page_{page_num}.png"
                    image.save(temp_image_path, "PNG")
                    
                    try:
                        # Extract text using Gemini Vision
                        logger.info(f"Processing page {page_num} with Gemini Vision...")
                        page_text = llm_service.generate_image_caption(temp_image_path)
                        
                        if page_text and "failed" not in page_text.lower():
                            all_text += f"\n--- Page {page_num} ---\n{page_text}\n"
                            logger.info(f"✓ Extracted {len(page_text)} chars from page {page_num}")
                        else:
                            logger.warning(f"No text extracted from page {page_num}")
                    
                    finally:
                        # Clean up temp file
                        try:
                            os.remove(temp_image_path)
                        except:
                            pass
                
                return all_text.strip()
            
            except ImportError:
                logger.warning("pdf2image not installed - cannot convert PDF pages to images")
                logger.info("Install with: pip install pdf2image")
                logger.info("Also install poppler: https://github.com/oschwartz10612/poppler-windows/releases/")
                return ""
        
        except Exception as e:
            logger.error(f"Error processing scanned PDF: {str(e)}", exc_info=True)
            return ""
    
    def _create_chunks(self, text: str) -> List[str]:
        """
        Split text into coherent chunks (structure-aware).

        Old behaviour cut the text every N characters, which produced
        fragments like "funding." and chunks that mixed two unrelated
        sections (statistics + funding). That destroyed both retrieval and
        cross-encoder re-ranking quality.

        New behaviour:
          1. Split into sections at headings (markdown, ALL-CAPS/"7. TITLE"
             lines, and PDF "--- Page N ---" markers).
          2. Pack whole paragraphs into chunks up to chunk_size characters.
          3. Prepend the section heading to every chunk so it is
             self-contained, and carry a word-aligned overlap between
             chunks of the same section.
          4. Only split inside a paragraph if a single paragraph is longer
             than chunk_size, and then at sentence boundaries.
        """
        if not text:
            return []
        
        chunks: List[str] = []
        for heading, body in self._split_sections(text):
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip()]
            if not paragraphs:
                if heading:
                    chunks.append(heading)
                continue
            
            prefix = (heading + "\n\n") if heading else ""
            current = ""
            
            for para in paragraphs:
                for piece in self._split_long_paragraph(para, self.chunk_size):
                    if not current:
                        current = piece
                    elif len(current) + len(piece) + 2 <= self.chunk_size:
                        current = f"{current}\n\n{piece}"
                    else:
                        chunks.append((prefix + current).strip())
                        tail = self._tail_overlap(current, self.chunk_overlap)
                        current = f"{tail}\n\n{piece}" if tail else piece
            
            if current:
                chunks.append((prefix + current).strip())
        
        # Drop degenerate fragments (e.g. a stray heading or "funding.")
        # 25 chars keeps short but real content (image captions) while
        # discarding the 8-char shards the old chunker produced.
        return [c for c in chunks if len(c.strip()) > 25]
    
    # Section headings: markdown (## X), numbered ALL-CAPS ("7. DATA RETENTION")
    # and PDF page markers ("--- Page 3 ---").
    _HEADING_PATTERNS = (
        re.compile(r'^#{1,6}\s+\S.*$'),
        re.compile(r'^\s*\d+\.\s+[A-Z][A-Z0-9 ,&/\-()]{2,59}$'),
        re.compile(r'^---\s*Page\s+\d+\s*---$', re.IGNORECASE),
    )
    
    @classmethod
    def _is_heading(cls, line: str) -> bool:
        return any(p.match(line.strip()) for p in cls._HEADING_PATTERNS)
    
    @classmethod
    def _split_sections(cls, text: str) -> List[Tuple[str, str]]:
        """Split text into (heading, body) sections."""
        sections: List[Tuple[str, str]] = []
        heading = ""
        body: List[str] = []
        
        for line in text.split("\n"):
            if cls._is_heading(line):
                if heading or any(l.strip() for l in body):
                    sections.append((heading, "\n".join(body)))
                heading = line.strip()
                body = []
            else:
                body.append(line)
        
        if heading or any(l.strip() for l in body):
            sections.append((heading, "\n".join(body)))
        
        return sections
    
    @staticmethod
    def _tail_overlap(text: str, overlap: int) -> str:
        """Last `overlap` characters of text, trimmed to a word boundary."""
        if overlap <= 0 or len(text) <= overlap:
            return ""
        tail = text[-overlap:]
        space = tail.find(' ')
        return tail[space + 1:].strip() if space != -1 else tail.strip()
    
    def _split_long_paragraph(self, para: str, max_size: int) -> List[str]:
        """Split an over-long paragraph at sentence boundaries."""
        if len(para) <= max_size:
            return [para]
        
        sentences = re.split(r'(?<=[.!?])\s+', para)
        packed: List[str] = []
        current = ""
        
        for sentence in sentences:
            if not current:
                current = sentence
            elif len(current) + len(sentence) + 1 <= max_size:
                current = f"{current} {sentence}"
            else:
                packed.append(current)
                current = sentence
        if current:
            packed.append(current)
        
        # Hard-split anything still too long (e.g. a wall of text with no periods)
        final: List[str] = []
        for piece in packed:
            while len(piece) > max_size:
                final.append(piece[:max_size])
                piece = piece[max_size:]
            if piece:
                final.append(piece)
        return final
    
    def extract_pdf_pages(self, file_path: str) -> Dict[int, str]:
        """
        Extract text from each PDF page separately
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            Dictionary mapping page number to text
        """
        pages = {}
        
        try:
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text:
                        pages[page_num + 1] = page_text.strip()
        
        except Exception as e:
            logger.error(f"Error extracting PDF pages: {str(e)}")
        
        return pages
    
    def create_chunks_with_metadata(
        self,
        text: str,
        document_id: str,
        document_name: str,
        page_number: int = None
    ) -> List[Dict[str, any]]:
        """
        Create chunks with metadata
        
        Args:
            text: Text to chunk
            document_id: ID of the source document
            document_name: Name of the source document
            page_number: Optional page number
        
        Returns:
            List of chunk dictionaries with metadata
        """
        chunks = self._create_chunks(text)
        
        chunk_data = []
        for i, chunk in enumerate(chunks):
            metadata = {
                "chunk_id": f"{document_id}_chunk_{i}",
                "document_id": document_id,
                "document_name": document_name,
                "chunk_index": i,
                "chunk_text": chunk,
            }
            
            if page_number is not None:
                metadata["page_number"] = page_number
            
            chunk_data.append(metadata)
        
        return chunk_data


# Global document processor instance
document_processor = DocumentProcessor()
