import os
import re
import json
import asyncio
from typing import List
from groq import Groq, AsyncGroq
from dotenv import load_dotenv
from src.models import (
    RepoPattern, CodeReviewResult, ReviewIssue,
    Severity, SupportedLanguage, LanguagePattern
)
from src.embedder import search_similar

load_dotenv()

GROQ_MODEL = 'llama-3.3-70b-versatile'
MAX_TOKENS = 4096


def _detect_language(code: str) -> SupportedLanguage:
    if 'def ' in code or 'import ' in code or 'print(' in code:
        return SupportedLanguage.PYTHON
    elif 'public ' in code or 'private ' in code or 'void ' in code:
        return SupportedLanguage.JAVA
    elif 'fun ' in code and ':' in code:
        return SupportedLanguage.KOTLIN
    elif 'function ' in code or 'const ' in code or 'let ' in code:
        return SupportedLanguage.JAVASCRIPT
    elif ': ' in code and ('=>' in code or 'interface ' in code):
        return SupportedLanguage.TYPESCRIPT
    return SupportedLanguage.PYTHON


def _split_into_functions(code: str, language: SupportedLanguage) -> List[str]:
    import re
    if language == SupportedLanguage.PYTHON:
        import ast
        try:
            tree = ast.parse(code)
            lines = code.split('\n')
            functions = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if hasattr(node, 'end_lineno'):
                        func_lines = lines[node.lineno - 1:node.end_lineno]
                        functions.append('\n'.join(func_lines))
            return functions if functions else [code]
        except SyntaxError:
            return [code]
    else:
        patterns = {
            SupportedLanguage.JAVA: re.compile(
                r'(?:public|private|protected|static|\s)+[\w\<\>\[\]]+\s+\w+\s*\([^)]*\)\s*(?:throws\s+\w+)?\s*\{'
            ),
            SupportedLanguage.KOTLIN: re.compile(r'fun\s+\w+\s*\('),
            SupportedLanguage.JAVASCRIPT: re.compile(
                r'(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\(.*?\)\s*=>)'
            ),
            SupportedLanguage.TYPESCRIPT: re.compile(
                r'(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\(.*?\)\s*=>)'
            ),
        }
        pattern = patterns.get(language)
        if pattern:
            matches = list(pattern.finditer(code))
            if matches:
                chunks = []
                for i, match in enumerate(matches):
                    start = match.start()
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(code)
                    chunks.append(code[start:end].strip())
                return chunks
        return [code]


def _build_prompt(
    code_chunk: str,
    pattern: RepoPattern,
    similar_functions: List[dict],
    language: SupportedLanguage
) -> str:
    lang_pattern = pattern.per_language.get(language.value, pattern.combined)

    similar_code_str = ''
    for i, func in enumerate(similar_functions[:3]):
        file_path = func.get('file_path', '')
        preview = func.get('preview', '')
        similar_code_str += f'\nExample {i+1} from their repo ({file_path})\n'
        similar_code_str += preview + '\n'

    prompt = f'''You are a personalized code reviewer. Review the submitted code against THIS SPECIFIC DEVELOPER coding patterns from their GitHub repo. Do NOT use generic rules.

DEVELOPER CODING FINGERPRINT ({language.value}):
- Naming convention: {lang_pattern.naming_convention}
- Average function length: {lang_pattern.avg_function_length} lines
- Docstring coverage: {round(lang_pattern.docstring_coverage * 100, 1)}% of functions have documentation
- Docstring style: {lang_pattern.docstring_style}
- Uses type hints: {lang_pattern.uses_type_hints}
- Error handling style: {lang_pattern.error_handling_style}
- Import organization: {lang_pattern.import_organization}
- Comment density: {lang_pattern.comment_density} comments per file

SIMILAR FUNCTIONS FROM THEIR ACTUAL CODEBASE:
{similar_code_str}

CODE TO REVIEW:
{code_chunk}

Return ONLY valid JSON with NO text before or after. Use exactly this structure:
{{
  "score": <integer 0-100>,
  "summary": "<2-3 sentence summary>",
  "issues": [
    {{
      "line_number": <integer>,
      "severity": "<critical|warning|suggestion>",
      "category": "<naming|docstring|function_length|error_handling|type_hints|imports|comments|style>",
      "message": "<specific message referencing their actual patterns>",
      "suggestion": "<exact fix>",
      "diff": null
    }}
  ]
}}

Rules:
- Reference their actual stats e.g. 94% of your functions have docstrings
- score 90-100 excellent, 70-89 good, 50-69 needs work, below 50 critical
- Only flag violations of THEIR patterns not generic rules
- If code matches their patterns perfectly return empty issues and high score
- Always set diff to null'''

    return prompt


def _clean_json(text: str) -> str:
    if '`' in text:
        parts = text.split('`')
        for part in parts:
            part = part.strip()
            if part.startswith('json'):
                text = part[4:].strip()
                break
            elif part.strip().startswith('{'):
                text = part.strip()
                break
    start = text.find('{')
    end = text.rfind('}') + 1
    if start != -1 and end > start:
        text = text[start:end]
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            escape = True
            result.append(ch)
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ord(ch) < 32 and ch not in ('\t',):
            result.append(' ')
            continue
        result.append(ch)
    return ''.join(result)


def _parse_review(response_text: str, language: SupportedLanguage) -> CodeReviewResult:
    clean = _clean_json(response_text)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        data = {'score': 70, 'summary': 'Review completed.', 'issues': []}

    issues = []
    for issue_data in data.get('issues', []):
        try:
            issues.append(ReviewIssue(
                line_number=issue_data.get('line_number', 1),
                severity=Severity(issue_data.get('severity', 'suggestion')),
                category=issue_data.get('category', 'style'),
                message=issue_data.get('message', ''),
                suggestion=issue_data.get('suggestion', ''),
                diff=None,
            ))
        except Exception:
            continue

    # Normalize inconsistent LLM outputs:
    # - If there are no issues but the score is < 100, treat it as a failure
    #   (likely parsing error or language mismatch) instead of silently
    #   reporting "no issues" with a low score.
    score = max(0, min(100, int(data.get('score', 70))))
    summary = data.get('summary', '')
    if not issues and score < 100:
        summary = (
            "Language mismatch or parsing error detected. "
            "Please confirm the submitted code matches the analyzed repository language and structure."
        )
        score = 0

    return CodeReviewResult(
        total_issues=len(issues),
        critical_count=sum(1 for i in issues if i.severity == Severity.CRITICAL),
        warning_count=sum(1 for i in issues if i.severity == Severity.WARNING),
        suggestion_count=sum(1 for i in issues if i.severity == Severity.SUGGESTION),
        score=score,
        issues=issues,
        summary=summary,
        detected_language=language,
    )


def review_code(
    code: str,
    repo_url: str,
    pattern: RepoPattern,
    log_callback=None,
) -> CodeReviewResult:
    """
    Synchronous wrapper around the asynchronous review pipeline.
    Keeps the public API unchanged for callers like the Streamlit app.
    """
    return asyncio.run(
        review_code_async(
            code=code,
            repo_url=repo_url,
            pattern=pattern,
            log_callback=log_callback,
        )
    )


async def review_code_async(
    code: str,
    repo_url: str,
    pattern: RepoPattern,
    log_callback=None,
) -> CodeReviewResult:
    """
    Asynchronous review that fires LLM calls for each function concurrently.
    """
    client = AsyncGroq(api_key=os.getenv('GROQ_API_KEY'))
    language = _detect_language(code)
    functions = _split_into_functions(code, language)

    if log_callback:
        log_callback(f"Spawning {len(functions)} specialized Review Agents...", "INFO")

    async def review_chunk(func_chunk: str, index: int) -> CodeReviewResult:
        if log_callback:
            log_callback(f"Agent-{index + 1}: Analyzing logic block...", "INFO")

        similar = search_similar(func_chunk, repo_url, top_k=3)
        prompt = _build_prompt(func_chunk, pattern, similar, language)

        response = await client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=0.1,
        )
        return _parse_review(response.choices[0].message.content, language)

    tasks = [review_chunk(chunk, i) for i, chunk in enumerate(functions)]
    results = await asyncio.gather(*tasks)

    all_issues: List[ReviewIssue] = []
    all_scores: List[int] = []
    all_summaries: List[str] = []

    for res in results:
        all_issues.extend(res.issues)
        all_scores.append(res.score)
        all_summaries.append(res.summary)

    final_score = round(sum(all_scores) / len(all_scores)) if all_scores else 70

    return CodeReviewResult(
        total_issues=len(all_issues),
        critical_count=sum(1 for i in all_issues if i.severity == Severity.CRITICAL),
        warning_count=sum(1 for i in all_issues if i.severity == Severity.WARNING),
        suggestion_count=sum(1 for i in all_issues if i.severity == Severity.SUGGESTION),
        score=final_score,
        issues=all_issues,
        summary=" ".join(all_summaries) if all_summaries else "Review complete.",
        detected_language=language,
    )
