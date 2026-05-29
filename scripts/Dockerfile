FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy the source files
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Expose the API port
EXPOSE 8000

# Set environment variables (defaults, can be overridden by docker-compose)
ENV PORT=8000
ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
ENV OLLAMA_MODEL=llama3.1:8b
ENV MAX_FILE_SIZE_MB=10
ENV KNOWLEDGE_GRAPH_DIR=/app/data/knowledge_graph

# Run the app
CMD ["python", "backend/app.py"]
