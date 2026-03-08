import os
import json
import time
import hashlib
import faiss
import numpy as np
from typing import List, Tuple, Optional
from google import genai
from dotenv import load_dotenv
from src.models import SupportedLanguage

load_dotenv()

EMBEDDING_MODEL = 'gemini-embedding-001'
EMBEDDING_DIM = 3072
FAISS_INDEX_DIR = '.faiss_index'


def _get_repo_hash(repo_url: str) -> str:
    return hashlib.md5(repo_url.encode()).hexdigest()[:12]


def _get_index_paths(repo_url: str) -> Tuple[str, str]:
    repo_hash = _get_repo_hash(repo_url)
    index_path = os.path.join(FAISS_INDEX_DIR, f'{repo_hash}.index')
    meta_path = os.path.join(FAISS_INDEX_DIR, f'{repo_hash}.meta.json')
    return index_path, meta_path


def _chunk_by_function(file_path: str, content: str, language: SupportedLanguage) -> List[Tuple[str, str]]:
    chunks = []
    if language == SupportedLanguage.PYTHON:
        import ast
        try:
            tree = ast.parse(content)
            lines = content.split('\n')
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, 'end_lineno'):
                        func_lines = lines[node.lineno - 1:node.end_lineno]
                        chunk_text = '\n'.join(func_lines)
                        chunk_id = f'{file_path}::{node.name}::{node.lineno}'
                        chunks.append((chunk_id, chunk_text))
        except SyntaxError:
            chunks.append((file_path, content))
    else:
        import re
        patterns = {
            SupportedLanguage.JAVA: re.compile(
                r'(?:public|private|protected|static|\s)+[\w\<\>\[\]]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+)?\s*\{'
            ),
            SupportedLanguage.JAVASCRIPT: re.compile(
                r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(.*?\)\s*=>)'
            ),
            SupportedLanguage.KOTLIN: re.compile(r'fun\s+(\w+)\s*\('),
            SupportedLanguage.TYPESCRIPT: re.compile(
                r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(.*?\)\s*=>)'
            ),
            SupportedLanguage.SHELL: re.compile(r'^(\w+)\s*\(\s*\)\s*\{', re.MULTILINE),
        }
        pattern = patterns.get(language)
        if pattern:
            matches = list(pattern.finditer(content))
            for i, match in enumerate(matches):
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                chunk_text = content[start:end].strip()
                name = next((g for g in match.groups() if g), f'func_{i}')
                chunk_id = f'{file_path}::{name}::{start}'
                chunks.append((chunk_id, chunk_text))
        if not chunks:
            chunks.append((file_path, content))
    return chunks


def _embed_texts(texts: List[str]) -> np.ndarray:
    client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
    embeddings = []
    batch_size = 5
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=batch,
                )
                for emb in result.embeddings:
                    embeddings.append(emb.values)
                break
            except Exception as e:
                error_str = str(e)
                if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str:
                    wait = 35 * (attempt + 1)
                    print(f'Rate limit hit, waiting {wait}s before retry {attempt + 1}/{max_retries}...')
                    time.sleep(wait)
                else:
                    raise
        else:
            raise RuntimeError(f'Failed to embed batch after {max_retries} retries.')
        time.sleep(1)
    return np.array(embeddings, dtype=np.float32)


def build_index(
    files: List[Tuple[str, str, SupportedLanguage]],
    repo_url: str
) -> Tuple[faiss.Index, List[dict]]:
    os.makedirs(FAISS_INDEX_DIR, exist_ok=True)
    index_path, meta_path = _get_index_paths(repo_url)

    all_chunks = []
    metadata = []

    for file_path, content, language in files:
        chunks = _chunk_by_function(file_path, content, language)
        for chunk_id, chunk_text in chunks:
            if len(chunk_text.strip()) < 20:
                continue
            all_chunks.append(chunk_text)
            metadata.append({
                'chunk_id': chunk_id,
                'file_path': file_path,
                'language': language.value,
                'preview': chunk_text[:200],
            })

    print(f'Embedding {len(all_chunks)} chunks from {len(files)} files...')
    embeddings = _embed_texts(all_chunks)

    index = faiss.IndexFlatL2(EMBEDDING_DIM)
    index.add(embeddings)

    faiss.write_index(index, index_path)
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f'Index saved: {index.ntotal} vectors at {index_path}')
    return index, metadata


def load_index(repo_url: str) -> Tuple[Optional[faiss.Index], List[dict]]:
    index_path, meta_path = _get_index_paths(repo_url)
    if not os.path.exists(index_path):
        return None, []
    index = faiss.read_index(index_path)
    with open(meta_path, 'r') as f:
        metadata = json.load(f)
    return index, metadata


def index_exists(repo_url: str) -> bool:
    index_path, _ = _get_index_paths(repo_url)
    return os.path.exists(index_path)


def search_similar(
    query_code: str,
    repo_url: str,
    top_k: int = 5
) -> List[dict]:
    index, metadata = load_index(repo_url)
    if index is None:
        raise ValueError(f'No index found for repo: {repo_url}. Run build_index first.')

    query_embedding = _embed_texts([query_code])
    distances, indices = index.search(query_embedding, top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx == -1:
            continue
        result = metadata[idx].copy()
        result['similarity_score'] = round(float(1 / (1 + dist)), 4)
        results.append(result)

    return results
