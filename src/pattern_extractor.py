import ast
import re
from collections import defaultdict
from typing import List, Tuple, Dict, Optional
from src.models import RepoPattern, LanguagePattern, SupportedLanguage, EXTENSION_TO_LANGUAGE

MIN_FILES_FOR_RELIABLE_PATTERN = 5

SNAKE_CASE_RE = re.compile(r'^[a-z][a-z0-9_]*$')
CAMEL_CASE_RE = re.compile(r'^[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$')
PASCAL_CASE_RE = re.compile(r'^[A-Z][a-zA-Z0-9]*$')

FUNCTION_PATTERNS = {
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
    SupportedLanguage.SHELL: re.compile(r'^(\w+)\s*\(\s*\)\s*\{'),
}


def _get_naming(function_names):
    total = len(function_names)
    if total == 0:
        return 'unknown'
    snake = sum(1 for n in function_names if SNAKE_CASE_RE.match(n))
    camel = sum(1 for n in function_names if CAMEL_CASE_RE.match(n))
    pascal = sum(1 for n in function_names if PASCAL_CASE_RE.match(n))
    snake_pct = round(snake / total * 100, 1)
    camel_pct = round(camel / total * 100, 1)
    pascal_pct = round(pascal / total * 100, 1)
    counts = {'snake_case': snake_pct, 'camelCase': camel_pct, 'PascalCase': pascal_pct}
    dominant = max(counts, key=counts.get)
    return f'Dominant: {dominant} | snake_case: {snake_pct}% | camelCase: {camel_pct}% | PascalCase: {pascal_pct}%'


class PythonASTAnalyzer:
    def __init__(self):
        self.function_names = []
        self.function_lengths = []
        self.docstring_styles = []
        self.has_docstring = []
        self.has_type_hints = []
        self.error_handling_styles = []
        self.import_styles = []
        self.comment_counts = []
        self.skipped_files = []

    def analyze_file(self, file_path: str, content: str) -> bool:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            self.skipped_files.append(file_path)
            return False
        lines = content.split('\n')
        self._extract_functions(tree, lines)
        self._extract_imports(tree)
        self._extract_comments(lines)
        return True

    def _extract_functions(self, tree, lines):
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            self.function_names.append(node.name)
            if hasattr(node, 'end_lineno'):
                self.function_lengths.append(node.end_lineno - node.lineno + 1)
            docstring = ast.get_docstring(node)
            self.has_docstring.append(docstring is not None)
            if docstring:
                self.docstring_styles.append(self._detect_docstring_style(docstring))
            has_hints = (
                any(arg.annotation is not None for arg in node.args.args) or
                node.returns is not None
            )
            self.has_type_hints.append(has_hints)
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    self.error_handling_styles.append('try/except')
                    break
                elif isinstance(child, ast.Assert):
                    self.error_handling_styles.append('assertions')
                    break
            else:
                self.error_handling_styles.append('none')

    def _detect_docstring_style(self, docstring: str) -> str:
        if 'Args:' in docstring or 'Returns:' in docstring or 'Raises:' in docstring:
            return 'google'
        elif 'Parameters\n----------' in docstring or 'Returns\n-------' in docstring:
            return 'numpy'
        elif docstring.strip():
            return 'plain'
        return 'none'

    def _extract_imports(self, tree):
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        if not imports:
            self.import_styles.append('none')
            return
        import_lines = [n.lineno for n in imports]
        self.import_styles.append('grouped' if import_lines == sorted(import_lines) else 'mixed')

    def _extract_comments(self, lines):
        self.comment_counts.append(sum(1 for l in lines if l.strip().startswith('#')))

    def build_pattern(self, total_files: int) -> LanguagePattern:
        total_functions = len(self.function_names)
        style_counts = defaultdict(int)
        for s in self.docstring_styles:
            style_counts[s] += 1
        top_style = max(style_counts, key=style_counts.get) if style_counts else 'none'
        eh_counts = defaultdict(int)
        for e in self.error_handling_styles:
            eh_counts[e] += 1
        top_eh = max(eh_counts, key=eh_counts.get) if eh_counts else 'none'
        import_counts = defaultdict(int)
        for i in self.import_styles:
            import_counts[i] += 1
        top_import = max(import_counts, key=import_counts.get) if import_counts else 'none'
        return LanguagePattern(
            language=SupportedLanguage.PYTHON,
            naming_convention=_get_naming(self.function_names),
            avg_function_length=round(sum(self.function_lengths) / len(self.function_lengths), 1) if self.function_lengths else 0.0,
            docstring_coverage=round(sum(self.has_docstring) / len(self.has_docstring), 2) if self.has_docstring else 0.0,
            docstring_style=top_style,
            uses_type_hints=sum(self.has_type_hints) / len(self.has_type_hints) > 0.5 if self.has_type_hints else False,
            error_handling_style=top_eh,
            import_organization=top_import,
            comment_density=round(sum(self.comment_counts) / total_files, 1) if total_files > 0 else 0.0,
            total_files_analyzed=total_files,
            total_functions_analyzed=total_functions,
        )


class RegexAnalyzer:
    def __init__(self, language: SupportedLanguage):
        self.language = language
        self.function_names = []
        self.function_lengths = []
        self.has_docstring = []
        self.error_handling_styles = []
        self.comment_counts = []
        self.uses_type_hints = []

    def analyze_file(self, content: str):
        lines = content.split('\n')
        self._extract_functions(content, lines)
        self._extract_comments(lines)

    def _extract_functions(self, content: str, lines: List[str]):
        pattern = FUNCTION_PATTERNS.get(self.language)
        if not pattern:
            return
        for match in pattern.finditer(content):
            name = next((g for g in match.groups() if g), None)
            if not name:
                continue
            self.function_names.append(name)
            start_line = content[:match.start()].count('\n')
            self.function_lengths.append(10)
            if start_line > 0:
                preceding = lines[max(0, start_line - 3): start_line]
                self.has_docstring.append(any('/**' in l or '/*' in l or '///' in l for l in preceding))
            func_snippet = content[match.start():match.start() + 300]
            if 'try' in func_snippet and ('catch' in func_snippet or 'except' in func_snippet):
                self.error_handling_styles.append('try/catch')
            else:
                self.error_handling_styles.append('none')
            if self.language in (SupportedLanguage.TYPESCRIPT, SupportedLanguage.KOTLIN):
                self.uses_type_hints.append(':' in match.group(0))
            elif self.language == SupportedLanguage.JAVA:
                self.uses_type_hints.append(True)
            else:
                self.uses_type_hints.append(False)

    def _extract_comments(self, lines: List[str]):
        self.comment_counts.append(sum(
            1 for l in lines if l.strip().startswith(('//', '#', '/*', '*', '/**'))
        ))

    def build_pattern(self, total_files: int) -> LanguagePattern:
        total_functions = len(self.function_names)
        eh_counts = defaultdict(int)
        for e in self.error_handling_styles:
            eh_counts[e] += 1
        top_eh = max(eh_counts, key=eh_counts.get) if eh_counts else 'none'
        return LanguagePattern(
            language=self.language,
            naming_convention=_get_naming(self.function_names),
            avg_function_length=round(sum(self.function_lengths) / len(self.function_lengths), 1) if self.function_lengths else 0.0,
            docstring_coverage=round(sum(self.has_docstring) / len(self.has_docstring), 2) if self.has_docstring else 0.0,
            docstring_style='javadoc' if self.language == SupportedLanguage.JAVA else 'inline',
            uses_type_hints=sum(self.uses_type_hints) / len(self.uses_type_hints) > 0.5 if self.uses_type_hints else False,
            error_handling_style=top_eh,
            import_organization='unknown',
            comment_density=round(sum(self.comment_counts) / total_files, 1) if total_files > 0 else 0.0,
            total_files_analyzed=total_files,
            total_functions_analyzed=total_functions,
        )


class PatternExtractor:
    def __init__(self, repo_url: str, repo_name: str):
        self.repo_url = repo_url
        self.repo_name = repo_name

    def extract(self, files: List[Tuple[str, str, SupportedLanguage]]) -> RepoPattern:
        by_language = defaultdict(list)
        for path, content, language in files:
            by_language[language].append((path, content))

        per_language_patterns = {}
        all_skipped = []

        for language, lang_files in by_language.items():
            total_files = len(lang_files)
            if total_files < MIN_FILES_FOR_RELIABLE_PATTERN:
                print(f'Warning: Only {total_files} {language.value} files found. Need {MIN_FILES_FOR_RELIABLE_PATTERN} for reliable pattern.')
            if language == SupportedLanguage.PYTHON:
                analyzer = PythonASTAnalyzer()
                for path, content in lang_files:
                    analyzer.analyze_file(path, content)
                all_skipped.extend(analyzer.skipped_files)
                pattern = analyzer.build_pattern(total_files)
            else:
                analyzer = RegexAnalyzer(language)
                for _, content in lang_files:
                    analyzer.analyze_file(content)
                pattern = analyzer.build_pattern(total_files)
            per_language_patterns[language.value] = pattern

        combined = self._build_combined_pattern(per_language_patterns)
        return RepoPattern(
            repo_url=self.repo_url,
            repo_name=self.repo_name,
            total_files_analyzed=len(files),
            supported_languages_found=list(by_language.keys()),
            combined=combined,
            per_language=per_language_patterns,
            skipped_files=all_skipped,
        )

    def _build_combined_pattern(self, per_language) -> LanguagePattern:
        if not per_language:
            return LanguagePattern(
                language=SupportedLanguage.PYTHON,
                naming_convention='unknown',
                avg_function_length=0.0,
                docstring_coverage=0.0,
                docstring_style='none',
                uses_type_hints=False,
                error_handling_style='none',
                import_organization='none',
                comment_density=0.0,
                total_files_analyzed=0,
                total_functions_analyzed=0,
            )
        patterns = list(per_language.values())
        total_functions = sum(p.total_functions_analyzed for p in patterns)
        total_files = sum(p.total_files_analyzed for p in patterns)

        def weighted_avg(attr):
            if total_functions == 0:
                return 0.0
            return round(sum(getattr(p, attr) * p.total_functions_analyzed for p in patterns) / total_functions, 2)

        eh_counts = defaultdict(int)
        for p in patterns:
            eh_counts[p.error_handling_style] += p.total_functions_analyzed
        top_eh = max(eh_counts, key=eh_counts.get) if eh_counts else 'none'
        type_hint_langs = sum(1 for p in patterns if p.uses_type_hints)

        return LanguagePattern(
            language=SupportedLanguage.PYTHON,
            naming_convention='see per-language breakdown',
            avg_function_length=weighted_avg('avg_function_length'),
            docstring_coverage=weighted_avg('docstring_coverage'),
            docstring_style='see per-language breakdown',
            uses_type_hints=type_hint_langs > len(patterns) / 2,
            error_handling_style=top_eh,
            import_organization='see per-language breakdown',
            comment_density=weighted_avg('comment_density'),
            total_files_analyzed=total_files,
            total_functions_analyzed=total_functions,
        )


def extract_patterns(
    files: List[Tuple[str, str, SupportedLanguage]],
    repo_url: str,
    repo_name: str
) -> RepoPattern:
    extractor = PatternExtractor(repo_url, repo_name)
    return extractor.extract(files)
