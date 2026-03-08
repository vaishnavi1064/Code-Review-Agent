# Code Review Agent

An AI-powered personalized code review system that analyzes your GitHub repository to extract your unique coding "fingerprint," then reviews new code against your personal patterns — not generic rules.

## What Makes This Different

Most code review tools flag violations of universal rules. This agent learns **your** coding DNA first:
- Your docstring habits
- Your naming conventions
- Your average function length
- Your error handling style
- Your comment density

Then it reviews new code against **your** established patterns, giving feedback like *"94% of your functions have docstrings but this one doesn't"* instead of generic warnings.

## Architecture
```
GitHub Repo → Pattern Extractor → Coding Fingerprint
                                          ↓
New Code → Groq LLM (Llama 3.3 70B) → Personalized Review
                ↑
         FAISS Vector Search
         (finds similar functions
          from your actual codebase)
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| LLM | Groq — Llama 3.3 70B |
| Embeddings | Google Gemini (gemini-embedding-001, 3072 dims) |
| Vector Store | FAISS (local) |
| GitHub Ingestion | PyGithub |
| Data Validation | Pydantic v2 |
| UI | Streamlit |
| Reports | ReportLab (PDF) + JSON |

## Features

- Analyzes any public GitHub repository
- Extracts per-language coding fingerprint (Python, Java, Kotlin, JS, TS)
- Reviews new code against your personal patterns using RAG pipeline
- Generates styled PDF and JSON reports with scores and actionable fixes
- 30-day caching to avoid re-analyzing the same repo
- Automatic rate limit handling for Gemini free tier

## Project Structure
```
code-review-agent/
├── app.py                  # Streamlit UI
├── src/
│   ├── models.py           # Pydantic data models
│   ├── github_ingestor.py  # GitHub repo fetching
│   ├── pattern_extractor.py# Coding fingerprint extraction
│   ├── embedder.py         # FAISS index builder + search
│   ├── cache_manager.py    # 30-day caching layer
│   ├── reviewer.py         # Groq LLM review engine
│   └── report_generator.py # PDF + JSON report generation
```

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/vaishnavi1064/Code-Review-Agent.git
cd Code-Review-Agent
```

### 2. Create virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Mac/Linux
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Set up environment variables
Create a `.env` file in the root directory:
```
GROQ_API_KEY=your_groq_api_key
GOOGLE_API_KEY=your_gemini_api_key
GITHUB_TOKEN=your_github_token  # optional, for private repos
```

Get your free API keys:
- Groq: https://console.groq.com
- Gemini: https://aistudio.google.com

### 5. Run the app
```bash
streamlit run app.py
```

## How to Use

1. **Step 1** — Enter a GitHub repository URL and click **Analyze Repository**. The agent will fetch all code files, extract your coding fingerprint, and build a FAISS vector index.

2. **Step 2** — Paste any code you want reviewed, select PDF/JSON export options, and click **Review Code**.

3. Download the generated PDF or JSON report with your personalized score and actionable feedback.

## Sample Output
```
Score: 85/100 — GOOD
Language: JAVA

Warning — Line 2 — DOCSTRING
Only 30% of your functions have docstrings, but this one is missing.
Fix: /** * Adds a product to the stock. * @param productId the ID */

Suggestion — Line 1 — FUNCTION_LENGTH  
Average function length in your codebase is 10 lines, this one is shorter.
Fix: Consider adding error handling to bring it in line with your patterns.
```

## API Keys (Free Tier)

| Service | Free Limit |
|---------|-----------|
| Groq | 30 req/min, 14,400 req/day |
| Gemini Embeddings | 100 req/min |
| GitHub | 60 req/hour (unauthenticated) |

## Author

**Vaishnavi Chaughule**  
M.S. Computer Science — Northeastern University, Seattle  
[GitHub](https://github.com/vaishnavi1064) | [LinkedIn](https://linkedin.com/in/vaishnavi-chaughule)
