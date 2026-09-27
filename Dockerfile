# ---------------------------------------------------------------
# Single-container image for Hugging Face Spaces (Docker SDK).
# Serves the FastAPI backend AND the static frontend on port 7860.
#
# The local docker-compose setup (nginx + two containers) uses
# Dockerfile.backend / Dockerfile.frontend instead; this file is for Spaces.
# ---------------------------------------------------------------
FROM python:3.11-slim

# Pillow and the PDF stack need these. OCR itself is done by Gemini Vision,
# so Tesseract and poppler are deliberately not installed.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Spaces runs containers as a non-root user with uid 1000
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface

WORKDIR /home/user/app

# CPU-only torch first: avoids pulling ~2 GB of CUDA wheels
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r backend/requirements.txt \
 && pip install --no-cache-dir openai

# Bake both models into the image so a cold start is a model LOAD,
# not a 180 MB download. This is the single biggest startup win.
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY backend/ ./backend/
COPY frontend/ ./frontend/

# The app writes ChromaDB, the SQLite files and uploads next to its code,
# so the non-root user must own the app directory.
RUN chown -R user:user /home/user

USER user

EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--app-dir", "backend"]
