# src/models.py
# Defines the structure of all data in the project.
# Every other file imports from here — never import in the other direction.

from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from enum import Enum


class Severity(str, Enum):
    """The 3 levels of feedback the agent can give. No other values are allowed."""
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"


class SupportedLanguage(str, Enum):
    """All file types the agent can analyze. Add new ones here if needed."""
    PYTHON = "python"
    JAVA = "java"
    JAVASCRIPT = "javascript"
    KOTLIN = "kotlin"
    TYPESCRIPT = "typescript"
    SHELL = "shell"


# Maps file extensions to their SupportedLanguage enum value
EXTENSION_TO_LANGUAGE: Dict[str, SupportedLanguage] = {
    ".py": SupportedLanguage.PYTHON,
    ".java": SupportedLanguage.JAVA,
    ".js": SupportedLanguage.JAVASCRIPT,
    ".kt": SupportedLanguage.KOTLIN,
    ".ts": SupportedLanguage.TYPESCRIPT,
    ".sh": SupportedLanguage.SHELL,
}


class ReviewIssue(BaseModel):
    """Represents one single problem found in the submitted code."""
    line_number: int
    severity: Severity
    category: str           # e.g. "naming", "docstring", "function_length"
    message: str            # e.g. "Function uses camelCase — your repo uses snake_case"
    suggestion: str         # e.g. "Rename to process_data"
    diff: Optional[str] = None  # side-by-side diff: "- old line\n+ suggested line"


class LanguagePattern(BaseModel):
    """Coding pattern fingerprint for a single language."""
    language: SupportedLanguage
    naming_convention: str          # "snake_case", "camelCase", "PascalCase", "mixed"
    avg_function_length: float      # average lines per function
    docstring_coverage: float       # 0.0 to 1.0 — % of functions with docstrings
    docstring_style: str            # "google", "numpy", "javadoc", "plain", "none"
    uses_type_hints: bool           # does this language's code use type hints?
    error_handling_style: str       # "try/except", "try/catch", "assertions", "none"
    import_organization: str        # "grouped", "alphabetical", "mixed", "none"
    comment_density: float          # avg comment lines per function
    total_files_analyzed: int       # how many files were read for this language
    total_functions_analyzed: int   # how many functions were found


class RepoPattern(BaseModel):
    """
    The complete coding fingerprint of a GitHub repo.
    Contains both a combined pattern and a per-language breakdown.
    """
    repo_url: str
    repo_name: str
    total_files_analyzed: int
    supported_languages_found: List[SupportedLanguage]

    # Combined pattern across ALL languages
    combined: LanguagePattern

    # Per-language breakdown — key is language name e.g. "python", "java"
    per_language: Dict[str, LanguagePattern] = Field(default_factory=dict)

    # Files that could not be read (binary, corrupted, encoding issues)
    skipped_files: List[str] = Field(default_factory=list)


class CodeReviewResult(BaseModel):
    """
    The complete output of a code review.
    This is what gets displayed in the Streamlit UI and exported as PDF/JSON.
    """
    # Counts
    total_issues: int
    critical_count: int
    warning_count: int
    suggestion_count: int

    # Score out of 100
    score: int = Field(ge=0, le=100)  # ge=0 means minimum 0, le=100 means maximum 100

    # All issues found
    issues: List[ReviewIssue]

    # 2-3 sentence overall summary
    summary: str

    # Language of the submitted code
    detected_language: SupportedLanguage

    # Files skipped during repo analysis (shown as warnings in UI)
    skipped_files: List[str] = Field(default_factory=list)


class IngestConfig(BaseModel):
    """
    Configuration for how to ingest a GitHub repo.
    This is what the user fills in on the Streamlit UI.
    """
    repo_url: str
    github_token: Optional[str] = None       # None = public repo only
    folder_path: Optional[str] = None        # None = entire repo
    selected_languages: List[SupportedLanguage] = Field(
        default_factory=lambda: list(SupportedLanguage)
    )
    force_refresh: bool = False              # True = re-analyze even if cached