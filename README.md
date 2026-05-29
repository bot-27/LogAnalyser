# 🔍 LogAnalyzer Agent

AI-powered log analysis tool built with **FastAPI**, **LangChain**, and **Ollama** (local LLM). Upload a log file and get instant root cause analysis, error detection, and actionable insights — all running locally on your machine.

Based on the [freeCodeCamp article](https://share.google/8pdQfnkCgbNa8NNZU) by Manish Shivanandhan.

## Features

- 📤 **Drag & Drop Upload** — Simple file upload interface
- 🤖 **Local AI Analysis** — Uses Ollama (llama3.1, mistral, etc.) — no cloud, no API keys
- 🔍 **Root Cause Detection** — Identifies the most likely causes of failures
- 💡 **Actionable Insights** — Practical next steps to fix issues
- 🎯 **Pattern Recognition** — Spots repeated issues and suspicious patterns
- 🔒 **100% Private** — All data stays on your machine

## Prerequisites

- **Python 3.10+**
- **Ollama** — Download from [ollama.com](https://ollama.com/)

## Quick Start

### 1. Install Ollama and pull a model

```bash
# After installing Ollama, pull a model:
ollama pull llama3.1:8b
```

### 2. Set up the project

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the server

```bash
python app.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### 4. Test it

Upload the included `sample_log.txt` and click **Analyze Logs**.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web UI |
| POST | `/analyze` | Analyze uploaded log file |
| GET | `/models` | List available Ollama models |
| GET | `/health` | Health check |

### POST /analyze

```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@sample_log.txt" \
  -G -d "model=llama3.1:8b"
```

Response:
```json
{
  "analysis": "## Main Errors\n\nThe logs show a database connection failure..."
}
```

## Configuration

Optional environment variables (create a `.env` file):

```env
OLLAMA_BASE_URL=http://localhost:11434   # Ollama server URL
OLLAMA_MODEL=llama3.1:8b                # Default model
PORT=8000                                # Server port
```

## Recommended Models

| Model | Size | Best For |
|-------|------|----------|
| `llama3.1:8b` | ~4.7 GB | Best all-around |
| `mistral` | ~4.1 GB | Fast and capable |
| `qwen2.5:7b` | ~4.4 GB | Structured analysis |

## Architecture

```
Browser (HTML/CSS/JS)
    ↓ POST /analyze (multipart/form-data)
FastAPI Backend (app.py)
    ↓ Split logs into chunks (LangChain RecursiveCharacterTextSplitter)
    ↓ Send each chunk to LLM with SRE prompt
Ollama (Local LLM)
    ↓ Analysis per chunk
FastAPI Backend
    ↓ Combined analysis JSON
Browser (render markdown)
```

## License

MIT License — feel free to use for personal or commercial projects.
