"""Document processing service - PDF, TXT, MD, DOCX, and IMAGE parsing and chunking"""

import os
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
        
        return text.strip()
    
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
        Split text into overlapping chunks
        
        Args:
            text: Full text to chunk
        
        Returns:
            List of text chunks
        """
        if not text:
            return []
        
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            # Get chunk
            end = start + self.chunk_size
            chunk = text[start:end]
            
            # Try to break at sentence or word boundary
            if end < text_length:
                # Look for sentence ending
                last_period = chunk.rfind('. ')
                last_newline = chunk.rfind('\n')
                last_break = max(last_period, last_newline)
                
                if last_break > self.chunk_size * 0.5:  # At least 50% of chunk size
                    chunk = chunk[:last_break + 1]
                    end = start + last_break + 1
            
            chunks.append(chunk.strip())
            
            # Move start position with overlap
            start = end - self.chunk_overlap
            
            # Ensure we're making progress
            if start <= 0 or start >= text_length:
                break
        
        return [c for c in chunks if c]  # Remove empty chunks
    
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
