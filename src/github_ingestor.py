import os
from typing import List, Tuple, Optional
from github import Github, GithubException
from dotenv import load_dotenv
from src.models import IngestConfig, SupportedLanguage, EXTENSION_TO_LANGUAGE

load_dotenv()


class GitHubIngestor:
    def __init__(self, config: IngestConfig):
        self.config = config
        self.github = self._authenticate()

    def _authenticate(self) -> Github:
        token = self.config.github_token or os.getenv('GITHUB_TOKEN')
        if token:
            return Github(token)
        return Github()

    def _extract_repo_name(self) -> str:
        url = self.config.repo_url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        parts = url.split('/')
        if len(parts) < 2:
            raise ValueError(f'Invalid GitHub URL: {self.config.repo_url}')
        return f'{parts[-2]}/{parts[-1]}'

    def _get_file_language(self, filename: str) -> Optional[SupportedLanguage]:
        ext = os.path.splitext(filename)[1].lower()
        return EXTENSION_TO_LANGUAGE.get(ext, None)

    def _should_include_file(self, file_path: str) -> bool:
        language = self._get_file_language(file_path)
        if language is None:
            return False
        if language not in self.config.selected_languages:
            return False
        if self.config.folder_path:
            folder = self.config.folder_path.strip('/')
            if not file_path.startswith(folder):
                return False
        return True

    def fetch_files(self) -> Tuple[List[Tuple[str, str, SupportedLanguage]], List[str]]:
        repo_name = self._extract_repo_name()
        try:
            repo = self.github.get_repo(repo_name)
        except GithubException as e:
            if e.status == 404:
                raise ValueError(f'Repo not found: {repo_name}')
            raise ValueError(f'GitHub error: {e.data.get("message", str(e))}')

        files = []
        skipped = []
        contents = self._get_all_contents(repo, self.config.folder_path or '')

        for content_file in contents:
            if not self._should_include_file(content_file.path):
                continue
            try:
                file_content = content_file.decoded_content.decode('utf-8')
                language = self._get_file_language(content_file.path)
                files.append((content_file.path, file_content, language))
            except UnicodeDecodeError:
                skipped.append(content_file.path)
            except GithubException:
                skipped.append(content_file.path)
            except Exception:
                skipped.append(content_file.path)

        return files, skipped

    def _get_all_contents(self, repo, path: str = '') -> list:
        all_files = []
        try:
            contents = repo.get_contents(path)
        except GithubException:
            return []
        while contents:
            file_content = contents.pop(0)
            if file_content.type == 'dir':
                try:
                    contents.extend(repo.get_contents(file_content.path))
                except GithubException:
                    pass
            else:
                all_files.append(file_content)
        return all_files


def ingest_repo(config: IngestConfig) -> Tuple[List[Tuple[str, str, SupportedLanguage]], List[str]]:
    ingestor = GitHubIngestor(config)
    return ingestor.fetch_files()
