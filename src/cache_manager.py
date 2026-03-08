import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from src.models import RepoPattern, LanguagePattern, SupportedLanguage

CACHE_DIR = '.cache'
CACHE_EXPIRY_DAYS = 30


def _get_cache_path(repo_url: str) -> str:
    import hashlib
    repo_hash = hashlib.md5(repo_url.encode()).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f'{repo_hash}.json')


def save_cache(
    repo_url: str,
    pattern: RepoPattern,
    file_paths: List[str]
):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_data = {
        'repo_url': repo_url,
        'timestamp': datetime.now().isoformat(),
        'file_paths': file_paths,
        'pattern': pattern.model_dump(),
    }
    cache_path = _get_cache_path(repo_url)
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=2)
    print(f'Cache saved: {cache_path}')


def load_cache(repo_url: str) -> Optional[tuple]:
    cache_path = _get_cache_path(repo_url)
    if not os.path.exists(cache_path):
        return None

    with open(cache_path, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)

    timestamp = datetime.fromisoformat(cache_data['timestamp'])
    age = datetime.now() - timestamp
    if age > timedelta(days=CACHE_EXPIRY_DAYS):
        print(f'Cache expired ({age.days} days old). Re-analyzing recommended.')
        return None

    pattern = RepoPattern(**cache_data['pattern'])
    file_paths = cache_data['file_paths']
    cached_at = timestamp.strftime('%Y-%m-%d %H:%M')
    days_old = age.days

    print(f'Cache hit: {cache_path} (cached {days_old} days ago on {cached_at})')
    return pattern, file_paths, days_old


def cache_exists(repo_url: str) -> bool:
    cache_path = _get_cache_path(repo_url)
    if not os.path.exists(cache_path):
        return False
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)
    timestamp = datetime.fromisoformat(cache_data['timestamp'])
    age = datetime.now() - timestamp
    return age <= timedelta(days=CACHE_EXPIRY_DAYS)


def delete_cache(repo_url: str) -> bool:
    cache_path = _get_cache_path(repo_url)
    if os.path.exists(cache_path):
        os.remove(cache_path)
        print(f'Cache deleted: {cache_path}')
        return True
    return False


def get_cache_info(repo_url: str) -> Optional[dict]:
    cache_path = _get_cache_path(repo_url)
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache_data = json.load(f)
    timestamp = datetime.fromisoformat(cache_data['timestamp'])
    age = datetime.now() - timestamp
    return {
        'repo_url': repo_url,
        'cached_at': timestamp.strftime('%Y-%m-%d %H:%M'),
        'days_old': age.days,
        'expired': age > timedelta(days=CACHE_EXPIRY_DAYS),
        'file_count': len(cache_data.get('file_paths', [])),
    }
