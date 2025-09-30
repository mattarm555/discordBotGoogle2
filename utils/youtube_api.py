import os
import requests
from typing import Optional, Dict, Any

YT_API_KEY = os.getenv('YOUTUBE_API_KEY')


def _ensure_key():
    if not YT_API_KEY:
        raise EnvironmentError('YOUTUBE_API_KEY not set in environment')


def yt_api_search(query: str, max_results: int = 1) -> Dict[str, Any]:
    _ensure_key()
    url = 'https://www.googleapis.com/youtube/v3/search'
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': max_results,
        'key': YT_API_KEY
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def yt_api_videos(video_id: str) -> Dict[str, Any]:
    _ensure_key()
    url = 'https://www.googleapis.com/youtube/v3/videos'
    params = {
        'id': video_id,
        'part': 'snippet,contentDetails',
        'key': YT_API_KEY
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def yt_api_playlist_items(playlist_id: str, max_results: int = 50) -> Dict[str, Any]:
    """Fetch up to max_results items from a playlist (pageSize up to 50)."""
    _ensure_key()
    url = 'https://www.googleapis.com/youtube/v3/playlistItems'
    params = {
        'part': 'snippet,contentDetails',
        'playlistId': playlist_id,
        'maxResults': max_results,
        'key': YT_API_KEY
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()
