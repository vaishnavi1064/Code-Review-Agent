"""
Tests for GitHub repo URL handling and live repository analysis.
Run with: python -m pytest tests/test_github_analysis.py -v
Or:       python -m unittest tests.test_github_analysis -v
"""
import unittest
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import IngestConfig, SupportedLanguage, RepoPattern, LanguagePattern
from src.github_ingestor import ingest_repo, GitHubIngestor
from src.pattern_extractor import extract_patterns


def extract_repo_name_from_url(url: str) -> str:
    """Mirror app's extract_repo_name: last path segment."""
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else url


class TestGitHubUrlParsing(unittest.TestCase):
    """Test that different GitHub URL formats are accepted and parsed correctly."""

    def test_standard_https_url(self):
        config = IngestConfig(repo_url="https://github.com/owner/repo")
        ingestor = GitHubIngestor(config)
        name = ingestor._extract_repo_name()
        self.assertEqual(name, "owner/repo")

    def test_url_with_trailing_slash(self):
        config = IngestConfig(repo_url="https://github.com/owner/repo/")
        ingestor = GitHubIngestor(config)
        name = ingestor._extract_repo_name()
        self.assertEqual(name, "owner/repo")

    def test_url_with_dot_git(self):
        config = IngestConfig(repo_url="https://github.com/owner/repo.git")
        ingestor = GitHubIngestor(config)
        name = ingestor._extract_repo_name()
        self.assertEqual(name, "owner/repo")

    def test_org_repo_format(self):
        config = IngestConfig(repo_url="https://github.com/python/cpython")
        ingestor = GitHubIngestor(config)
        name = ingestor._extract_repo_name()
        self.assertEqual(name, "python/cpython")

    def test_app_repo_name_display(self):
        """App uses last segment for display; ensure we get repo name."""
        url = "https://github.com/vaishnavi1064/Code-Review-Agent"
        self.assertEqual(extract_repo_name_from_url(url), "Code-Review-Agent")


class TestInvalidGitHubUrls(unittest.TestCase):
    """Test that invalid or non-existent repos raise clear errors."""

    def test_nonexistent_repo_raises(self):
        config = IngestConfig(repo_url="https://github.com/this-org/does-not-exist-xyz-12345")
        with self.assertRaises(ValueError) as ctx:
            ingest_repo(config)
        self.assertIn("not found", str(ctx.exception).lower())

    def test_invalid_url_too_short_raises(self):
        config = IngestConfig(repo_url="github.com")
        with self.assertRaises(ValueError):
            ingest_repo(config)

    def test_malformed_url_missing_parts(self):
        config = IngestConfig(repo_url="https://github.com/onlyowner")
        try:
            files, skipped = ingest_repo(config)
            self.assertIsInstance(files, list)
            self.assertIsInstance(skipped, list)
        except ValueError:
            pass


class TestLiveGitHubAnalysis(unittest.TestCase):
    """
    Test with real public GitHub repositories.
    Uses GitHub API without token (public repos). Rate limit: 60/hour unauthenticated.
    """

    @classmethod
    def setUpClass(cls):
        cls.repos_to_test = [
            "https://github.com/vaishnavi1064/Code-Review-Agent",
            "https://github.com/pallets/click",
        ]

    def test_ingest_returns_files_for_valid_repo(self):
        """Valid public repo URL should return at least some code files."""
        config = IngestConfig(repo_url=self.repos_to_test[0])
        files, skipped = ingest_repo(config)
        self.assertIsInstance(files, list)
        self.assertIsInstance(skipped, list)
        self.assertGreater(len(files), 0, "Expected at least one code file from Code-Review-Agent repo")
        for item in files:
            self.assertEqual(len(item), 3)
            path, content, lang = item
            self.assertIsInstance(path, str)
            self.assertIsInstance(content, str)
            self.assertIn(lang, SupportedLanguage)

    def test_ingest_supported_extensions_only(self):
        """Only .py, .java, .js, .kt, .ts, .sh should be included."""
        config = IngestConfig(repo_url=self.repos_to_test[0])
        files, _ = ingest_repo(config)
        allowed = {".py", ".java", ".js", ".kt", ".ts", ".sh"}
        for path, _, _ in files:
            ext = os.path.splitext(path)[1].lower()
            self.assertIn(ext, allowed, f"Unexpected extension in path: {path}")

    def test_extract_patterns_produces_valid_repo_pattern(self):
        """Full pipeline: ingest -> extract_patterns should produce a valid RepoPattern."""
        config = IngestConfig(repo_url=self.repos_to_test[0])
        files, _ = ingest_repo(config)
        self.assertGreater(len(files), 0)
        repo_url = config.repo_url
        repo_name = extract_repo_name_from_url(repo_url)
        pattern = extract_patterns(files, repo_url, repo_name)
        self.assertIsInstance(pattern, RepoPattern)
        self.assertEqual(pattern.repo_url, repo_url)
        self.assertEqual(pattern.repo_name, repo_name)
        self.assertEqual(pattern.total_files_analyzed, len(files))
        self.assertGreater(len(pattern.supported_languages_found), 0)
        self.assertIsInstance(pattern.combined, LanguagePattern)
        self.assertIsInstance(pattern.per_language, dict)

    def test_second_repo_also_analyzes(self):
        """Another public repo (click) should also be ingestible and analyzable."""
        config = IngestConfig(repo_url=self.repos_to_test[1])
        files, skipped = ingest_repo(config)
        self.assertGreater(len(files), 0, "Expected code files from pallets/click")
        repo_url = config.repo_url
        repo_name = extract_repo_name_from_url(repo_url)
        pattern = extract_patterns(files, repo_url, repo_name)
        self.assertEqual(pattern.repo_name, "click")
        self.assertIn(SupportedLanguage.PYTHON, pattern.supported_languages_found)
        self.assertGreater(pattern.combined.total_functions_analyzed, 0)

    def test_combined_pattern_has_sane_numbers(self):
        """Combined pattern should have non-negative, sane metrics."""
        config = IngestConfig(repo_url=self.repos_to_test[0])
        files, _ = ingest_repo(config)
        repo_url = config.repo_url
        repo_name = extract_repo_name_from_url(repo_url)
        pattern = extract_patterns(files, repo_url, repo_name)
        c = pattern.combined
        self.assertGreaterEqual(c.total_files_analyzed, 0)
        self.assertGreaterEqual(c.total_functions_analyzed, 0)
        self.assertGreaterEqual(c.docstring_coverage, 0.0)
        self.assertLessEqual(c.docstring_coverage, 1.0)
        self.assertGreaterEqual(c.avg_function_length, 0.0)


if __name__ == "__main__":
    unittest.main()
