"""Image processing service - extraction, captioning, and storage"""

import os
from typing import List, Dict, Tuple, Optional
from PIL import Image
import PyPDF2
import uuid
from io import BytesIO

from ..config.settings import settings
from ..utils.logging_config import get_logger

logger = get_logger(__name__)


class ImageProcessor:
    """Service for extracting and processing images from documents"""
    
    def __init__(self):
        """Initialize image processor"""
        logger.info("ImageProcessor initialized")
    
    def extract_images_from_pdf(
        self,
        pdf_path: str,
        document_id: str,
        user_id: int
    ) -> List[Dict]:
        """
        Extract images from PDF file
        
        Args:
            pdf_path: Path to PDF file
            document_id: Document identifier
            user_id: User identifier
        
        Returns:
            List of extracted image information
        """
        logger.info(f"Extracting images from PDF: {pdf_path}")
        
        images = []
        
        try:
            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    
                    # Extract images from page
                    if '/XObject' in page['/Resources']:
                        xObject = page['/Resources']['/XObject'].get_object()
                        
                        for obj_name in xObject:
                            obj = xObject[obj_name]
                            
                            if obj['/Subtype'] == '/Image':
                                try:
                                    image_info = self._extract_image_from_xobject(
                                        obj,
                                        obj_name,
                                        page_num + 1,
                                        document_id,
                                        user_id
                                    )
                                    if image_info:
                                        images.append(image_info)
                                except Exception as e:
                                    logger.warning(f"Failed to extract image {obj_name}: {str(e)}")
        
        except Exception as e:
            logger.error(f"Error extracting images from PDF: {str(e)}")
        
        logger.info(f"Extracted {len(images)} images from PDF")
        return images
    
    def _extract_image_from_xobject(
        self,
        xobject,
        obj_name: str,
        page_num: int,
        document_id: str,
        user_id: int
    ) -> Optional[Dict]:
        """
        Extract and save image from XObject
        
        Args:
            xobject: PDF XObject
            obj_name: Object name
            page_num: Page number
            document_id: Document ID
            user_id: User ID
        
        Returns:
            Image information dictionary
        """
        try:
            # Get image data
            size = (xobject['/Width'], xobject['/Height'])
            data = xobject.get_data()
            
            # Skip very small images (likely icons or decorative)
            if size[0] < 50 or size[1] < 50:
                return None
            
            # Determine image mode
            color_space = xobject['/ColorSpace']
            if color_space == '/DeviceRGB':
                mode = "RGB"
            elif color_space == '/DeviceGray':
                mode = "L"
            elif color_space == '/DeviceCMYK':
                mode = "CMYK"
            else:
                mode = "RGB"
            
            # Create PIL Image
            try:
                img = Image.frombytes(mode, size, data)
            except:
                # Try with BytesIO
                img = Image.open(BytesIO(data))
            
            # Generate unique filename
            image_id = str(uuid.uuid4())
            filename = f"page{page_num}_{image_id}.png"
            
            # Create directory
            image_dir = os.path.join(settings.image_dir, str(user_id), document_id)
            os.makedirs(image_dir, exist_ok=True)
            
            # Save image
            image_path = os.path.join(image_dir, filename)
            img.save(image_path, "PNG")
            
            logger.info(f"Saved image: {filename} (size: {size})")
            
            return {
                "image_id": image_id,
                "filename": filename,
                "path": image_path,
                "page_number": page_num,
                "width": size[0],
                "height": size[1],
                "size_bytes": os.path.getsize(image_path)
            }
        
        except Exception as e:
            logger.error(f"Error extracting image: {str(e)}")
            return None
    
    def process_image_file(
        self,
        image_path: str,
        document_id: str,
        user_id: int
    ) -> Dict:
        """
        Process standalone image file
        
        Args:
            image_path: Path to image file
            document_id: Associated document ID
            user_id: User ID
        
        Returns:
            Image information
        """
        logger.info(f"Processing image file: {image_path}")
        
        try:
            # Open and validate image
            img = Image.open(image_path)
            
            # Get image info
            image_id = str(uuid.uuid4())
            filename = os.path.basename(image_path)
            
            return {
                "image_id": image_id,
                "filename": filename,
                "path": image_path,
                "page_number": None,
                "width": img.width,
                "height": img.height,
                "size_bytes": os.path.getsize(image_path),
                "format": img.format
            }
        
        except Exception as e:
            logger.error(f"Error processing image: {str(e)}")
            raise ValueError(f"Failed to process image: {str(e)}")
    
    def resize_image(
        self,
        image_path: str,
        max_size: Tuple[int, int] = (1024, 1024)
    ) -> str:
        """
        Resize image if too large
        
        Args:
            image_path: Path to image
            max_size: Maximum dimensions (width, height)
        
        Returns:
            Path to resized image (or original if no resize needed)
        """
        try:
            img = Image.open(image_path)
            
            # Check if resize needed
            if img.width <= max_size[0] and img.height <= max_size[1]:
                return image_path
            
            # Resize maintaining aspect ratio
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            # Save resized image
            resized_path = image_path.replace('.', '_resized.')
            img.save(resized_path)
            
            logger.info(f"Resized image from {img.size} to {img.width}x{img.height}")
            return resized_path
        
        except Exception as e:
            logger.error(f"Error resizing image: {str(e)}")
            return image_path
    
    def create_thumbnail(
        self,
        image_path: str,
        size: Tuple[int, int] = (200, 200)
    ) -> Optional[str]:
        """
        Create thumbnail of image
        
        Args:
            image_path: Path to original image
            size: Thumbnail size
        
        Returns:
            Path to thumbnail or None
        """
        try:
            img = Image.open(image_path)
            img.thumbnail(size, Image.Resampling.LANCZOS)
            
            # Save thumbnail
            thumb_path = image_path.replace('.', '_thumb.')
            img.save(thumb_path)
            
            logger.info(f"Created thumbnail: {thumb_path}")
            return thumb_path
        
        except Exception as e:
            logger.error(f"Error creating thumbnail: {str(e)}")
            return None
    
    def get_image_metadata(self, image_path: str) -> Dict:
        """
        Get image metadata
        
        Args:
            image_path: Path to image
        
        Returns:
            Metadata dictionary
        """
        try:
            img = Image.open(image_path)
            
            metadata = {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "size_bytes": os.path.getsize(image_path)
            }
            
            # Get EXIF data if available
            if hasattr(img, '_getexif') and img._getexif():
                exif_data = img._getexif()
                metadata["exif"] = exif_data
            
            return metadata
        
        except Exception as e:
            logger.error(f"Error getting image metadata: {str(e)}")
            return {}
    
    def validate_image(self, image_path: str) -> bool:
        """
        Validate that file is a valid image
        
        Args:
            image_path: Path to image
        
        Returns:
            True if valid image
        """
        try:
            img = Image.open(image_path)
            img.verify()
            return True
        except Exception as e:
            logger.warning(f"Invalid image: {str(e)}")
            return False


# Global image processor instance
image_processor = ImageProcessor()
