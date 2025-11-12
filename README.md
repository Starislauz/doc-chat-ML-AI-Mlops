# RAG Document Chat API 🚀

A production-ready **Retrieval Augmented Generation (RAG)** document chat system with **multi-file upload**, **image OCR support**, and **hybrid AI mode**, built with FastAPI, ChromaDB, and Google Gemini AI.

## ✨ Key Features

### 📤 **Multi-File Upload**
- Upload up to **5 files at once** (PDFs, documents, images)
- Drag & drop interface with live preview
- Batch processing for multiple documents
- Individual file management

### 🖼️ **Image Support with OCR**
- Upload images: PNG, JPG, JPEG, BMP, TIFF
- Automatic text extraction using **Tesseract OCR**
- Perfect for:
  - 📸 Photos of handwritten notes
  - 📄 Scanned documents
  - 📊 Screenshots with text

### 🤖 **Hybrid AI Mode**
- **Smart Document Search**: Answers from uploaded documents first (with citations)
- **Research Assistant**: Offers general knowledge when info not in documents
- **Transparent**: Always tells you the source (documents vs. general knowledge)

### 🔐 **Authentication & Security**
- JWT-based authentication with Bearer tokens
- User registration and login
- Multi-tenant data isolation
- Password hashing with bcrypt
- Upload enforcement (must upload before chatting)

### 📚 **Document Management**
- Upload PDF, DOCX, TXT, MD, and **image files**
- Automatic text extraction and chunking
- Vector embeddings with sentence-transformers
- ChromaDB for persistent storage (no Docker required)
- **Delete documents** with one click

### 🔍 **Advanced RAG**
- Semantic search using embeddings
- Top-K retrieval with relevance scoring
- Context-aware question answering with citations
- Chat history with sessions
- Query transformation and coreference resolution
- Re-ranking with cross-encoder models
- Streaming responses (SSE)

### 🎯 **Multimodal Support**
- Extract images from PDFs
- AI-generated image captions using Gemini Vision
- Search across text and images
- Standalone image upload

### ⚡ **Production Ready**
- Comprehensive error handling
- Request validation with Pydantic
- Logging and monitoring
- Health check endpoints
- CORS support
- Optional Redis caching

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+** (Windows, macOS, or Linux)
- **Google Gemini API Key** - Get it from [Google AI Studio](https://makersuite.google.com/app/apikey)
- **Tesseract OCR (Optional)** - For better image text extraction
  - **Not required!** Application uses Gemini Vision as fallback
  - See [TESSERACT_SETUP.md](TESSERACT_SETUP.md) for installation instructions
  - Windows: [Download installer](https://github.com/UB-Mannheim/tesseract/wiki)
  - Linux: `sudo apt-get install tesseract-ocr`
  - Mac: `brew install tesseract`

### Important Notes

⚠️ **Network Connectivity Required**
- Gemini API requires internet connection
- If you see network errors, see [NETWORK_TROUBLESHOOTING.md](NETWORK_TROUBLESHOOTING.md)
- Application has offline fallback mode for document search

✅ **Tesseract is Optional**
- Images work without Tesseract (uses Gemini Vision API)
- Install Tesseract for better local text extraction
- See [TESSERACT_SETUP.md](TESSERACT_SETUP.md) for details

### Installation

1. **Clone or download this project**

2. **Get your Gemini API key**
   - Visit https://makersuite.google.com/app/apikey
   - Create a new API key
   - Copy it for the next step

3. **Run the startup script (Windows)**
   ```batch
   START_SERVER.bat
   ```

   The script will automatically:
   - Check Python installation
   - Create virtual environment
   - Install all dependencies
   - Start the server

4. **Configure your API key**
   - Edit the `.env` file that was created
   - Replace `your_gemini_api_key_here` with your actual API key
   - Save the file and restart the server

### Manual Installation (Alternative)

If you prefer manual setup:

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
copy .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Start server
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Documentation

Once the server is running, access the interactive API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## API Endpoints

### Public Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Welcome message |
| GET | `/health` | Health check with service status |
| POST | `/register` | Create user account |
| POST | `/login` | Get JWT token |

### Protected Endpoints (Require Authentication)

**User Management**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/me` | Get current user info |

**Document Management**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload document (PDF/TXT/MD) |
| POST | `/upload/multimodal` | Upload with image extraction |
| POST | `/upload/image` | Upload standalone image |
| GET | `/documents` | List user's documents |
| DELETE | `/documents/{id}` | Delete document |

**Question Answering**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ask` | Basic Q&A |
| POST | `/ask/enhanced` | Q&A with re-ranking and history |
| POST | `/ask/multimodal` | Q&A with text and images |
| POST | `/ask/stream` | Streaming Q&A responses |

**Chat Sessions**
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/chat/sessions` | Create chat session |
| GET | `/chat/sessions` | List user's sessions |
| GET | `/chat/sessions/{id}` | Get chat history |
| DELETE | `/chat/sessions/{id}` | Delete session |

**Images**
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/images/{doc_id}/{filename}` | Get image file |

## Usage Examples

### 1. Register and Login

```bash
# Register
curl -X POST "http://localhost:8000/register" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "email": "test@example.com",
    "password": "password123"
  }'

# Login
curl -X POST "http://localhost:8000/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "password123"
  }'

# Save the access_token from the response
```

### 2. Upload Document

```bash
# Upload a PDF document
curl -X POST "http://localhost:8000/upload" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -F "file=@document.pdf"

# Upload with multimodal processing (extracts images)
curl -X POST "http://localhost:8000/upload/multimodal" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -F "file=@document.pdf"
```

### 3. Ask Questions

```bash
# Basic question
curl -X POST "http://localhost:8000/ask" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the main topic of the document?",
    "top_k": 5
  }'

# Enhanced question with re-ranking
curl -X POST "http://localhost:8000/ask/enhanced" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Explain the key findings",
    "session_id": "optional-session-id",
    "top_k": 5,
    "use_reranking": true
  }'
```

### 4. Python Client Example

```python
import requests

BASE_URL = "http://localhost:8000"

# 1. Register
response = requests.post(
    f"{BASE_URL}/register",
    json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "password123"
    }
)
token = response.json()["access_token"]

# 2. Upload document
headers = {"Authorization": f"Bearer {token}"}
with open("document.pdf", "rb") as f:
    files = {"file": f}
    response = requests.post(
        f"{BASE_URL}/upload",
        headers=headers,
        files=files
    )
document_id = response.json()["id"]

# 3. Ask question
response = requests.post(
    f"{BASE_URL}/ask",
    headers=headers,
    json={
        "question": "What is this document about?",
        "top_k": 5
    }
)
answer = response.json()
print(f"Answer: {answer['answer']}")
print(f"Sources: {len(answer['sources'])}")
```

## Configuration

Edit `.env` file to customize settings:

```env
# Required
GEMINI_API_KEY=your_api_key_here

# Optional - Security
SECRET_KEY=your-secret-key-change-this-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=10080  # 7 days

# Optional - Redis Cache (system works without it)
REDIS_HOST=localhost
REDIS_PORT=6379
CACHE_ENABLED=true
```

### Configuration Options

All settings can be customized in `backend/app/config/settings.py`:

- **File Upload**: Max size (10 MB), allowed types
- **Chunking**: Chunk size (500 chars), overlap (50 chars)
- **Embedding Model**: all-MiniLM-L6-v2 (can be changed)
- **LLM Model**: gemini-2.0-flash-exp
- **RAG**: Top-K (5), re-ranking model

## Project Structure

```
project/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app
│   │   ├── config/
│   │   │   └── settings.py            # Configuration
│   │   ├── models/
│   │   │   └── schemas.py             # Pydantic models
│   │   ├── services/
│   │   │   ├── document_processor.py  # Document processing
│   │   │   ├── vector_store.py        # ChromaDB operations
│   │   │   ├── llm_service.py         # Gemini API
│   │   │   ├── user_service.py        # User management
│   │   │   ├── chat_service.py        # Chat history
│   │   │   ├── rag_enhanced.py        # Advanced RAG
│   │   │   └── image_processor.py     # Image processing
│   │   └── utils/
│   │       ├── auth.py                # JWT authentication
│   │       ├── file_handler.py        # File operations
│   │       └── logging_config.py      # Logging setup
│   ├── chroma_db/                     # Vector database (created automatically)
│   ├── users.db                       # User database (created automatically)
│   └── chat_history.db                # Chat database (created automatically)
├── uploads/                           # Uploaded files (created automatically)
├── images/                            # Extracted images (created automatically)
├── requirements.txt                   # Python dependencies
├── .env                               # Configuration (create from .env.example)
├── .env.example                       # Configuration template
├── README.md                          # This file
└── START_SERVER.bat                   # Windows startup script
```

## Architecture

### Data Flow

1. **Document Upload**
   - User uploads PDF/TXT/MD file
   - Text extracted and split into chunks
   - Chunks embedded using sentence-transformers
   - Stored in ChromaDB with user_id for isolation

2. **Question Answering**
   - User asks question
   - Question embedded and compared to stored chunks
   - Top-K most relevant chunks retrieved
   - Gemini generates answer using context
   - Answer returned with source citations

3. **Chat History**
   - Chat sessions stored in SQLite
   - Previous messages used for context
   - Query transformation resolves references

### Multi-Tenancy

All data is isolated by `user_id`:
- Documents in ChromaDB filtered by user_id
- Files stored in user-specific directories
- Chat sessions linked to user accounts
- Images accessible only to owners

### Security

- Passwords hashed with bcrypt
- JWT tokens for authentication
- Bearer token required for protected endpoints
- User ownership validated on all operations
- File size and type validation
- SQL injection prevention (parameterized queries)

## Troubleshooting

### Common Issues

**1. Network Error: `[Errno 11001] getaddrinfo failed`**
- **Cause:** Cannot connect to Google's Gemini API
- **Solutions:**
  - Check internet connection
  - Check firewall settings
  - Configure proxy if behind corporate network
  - See detailed guide: [NETWORK_TROUBLESHOOTING.md](NETWORK_TROUBLESHOOTING.md)
- **Note:** Application provides offline fallback with document excerpts

**2. Image Upload Error: "tesseract is not installed"**
- **No worries!** Tesseract is optional
- **Application uses Gemini Vision as fallback** (works without Tesseract)
- **To install Tesseract:** See [TESSERACT_SETUP.md](TESSERACT_SETUP.md)
- **With Tesseract:** Better local text extraction from images
- **Without Tesseract:** Images still work via Gemini Vision API

**3. "Gemini API key not found"**
- Edit `.env` file and add your API key
- Get key from https://makersuite.google.com/app/apikey
- Restart the server after editing .env

**4. "Module not found" errors**
- Activate virtual environment: `venv\Scripts\activate`
- Install dependencies: `pip install -r requirements.txt`

**5. ChromaDB errors**
- Delete `backend/chroma_db` folder and restart
- System will recreate the database

**6. Port 8000 already in use**
- Stop other processes using port 8000
- Or change port: `uvicorn app.main:app --port 8001`

**7. Slow first question**
- First question loads embedding models (normal)
- Subsequent questions will be faster
- Models are cached after first load

### Detailed Troubleshooting Guides

📘 **[NETWORK_TROUBLESHOOTING.md](NETWORK_TROUBLESHOOTING.md)** - Fix connection errors
- DNS resolution issues
- Firewall configuration
- Proxy setup
- VPN issues
- Offline fallback mode

📘 **[TESSERACT_SETUP.md](TESSERACT_SETUP.md)** - Install OCR (optional)
- Windows installation
- PATH configuration
- Verification steps
- Gemini Vision fallback

### Application Behavior

**With Network Connection:**
- ✅ Full AI-powered responses
- ✅ Image captioning with Gemini Vision
- ✅ Smart document-based answers

**Without Network Connection:**
- ✅ Document upload (without image AI)
- ✅ Document search (vector search works)
- ✅ Document excerpts shown
- ❌ No AI-generated responses (offline fallback provided)

**With Tesseract:**
- ✅ Fast local OCR for images
- ✅ Works offline for text extraction

**Without Tesseract:**
- ✅ Images still work (Gemini Vision)
- ❌ Requires internet for image processing

### Logs

- Check console output for detailed logs
- Errors include specific messages
- Log level: INFO (production), DEBUG (development)

## Performance

- **Document Upload**: < 10 seconds for 10-page PDF
- **Question Answering**: < 3 seconds (after model loading)
- **First Query**: May take 10-30 seconds (loads models)
- **Embeddings**: Batch processed for efficiency
- **Caching**: Optional Redis for frequently asked questions

## Technologies

- **FastAPI** - Modern Python web framework
- **ChromaDB** - Vector database (local, no Docker)
- **sentence-transformers** - Text embeddings
- **Google Gemini** - Large language model
- **SQLite** - User and chat storage
- **PyPDF2** - PDF processing
- **Pillow** - Image handling
- **JWT** - Authentication tokens
- **bcrypt** - Password hashing

## License

This project is provided as-is for educational and commercial use.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs for error details
3. Verify API key is set correctly
4. Ensure all dependencies are installed

## Roadmap

Potential future enhancements:
- [ ] Multiple LLM providers (OpenAI, Anthropic)
- [ ] Advanced document types (DOCX, Excel)
- [ ] Batch document upload
- [ ] Document versioning
- [ ] User groups and sharing
- [ ] Custom embeddings fine-tuning
- [ ] Web UI frontend

---

**Built with ❤️ using FastAPI, ChromaDB, and Google Gemini**
