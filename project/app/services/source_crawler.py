from __future__ import annotations

import logging
import random
from dataclasses import asdict, dataclass, field
from typing import Iterable

from yt_dlp import DownloadError, YoutubeDL

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


TIKTOK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://www.tiktok.com/",
    "Accept-Language": "en-US,en;q=0.9",
}
YOUTUBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.youtube.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class VideoCandidate:
    platform: str
    source_id: str
    url: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    duration: int = 0
    uploader: str = ""
    thumbnail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SourceCrawlerService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def crawl_all(self, limit_per_source: int = 10) -> list[VideoCandidate]:
        candidates: list[VideoCandidate] = []
        try:
            candidates.extend(self.crawl_tiktok(limit=limit_per_source))
        except Exception as exc:
            logger.warning("TikTok crawl failed: %s", exc)
        try:
            candidates.extend(self.crawl_youtube(limit=limit_per_source))
        except Exception as exc:
            logger.warning("YouTube crawl failed: %s", exc)

        filtered = self._filter_platform(candidates)
        filtered = self._filter_silent(filtered)
        filtered = self._filter_duration(filtered)
        random.shuffle(filtered)
        logger.info(
            "Crawl result: %d raw → %d silent-safe candidates", len(candidates), len(filtered)
        )
        return filtered

    # ─────────── TikTok ───────────

    def crawl_tiktok(self, limit: int = 10) -> list[VideoCandidate]:
        collected: list[VideoCandidate] = []
        for url in self.settings.tiktok_hashtag_urls:
            collected.extend(self._tiktok_extract(url, limit))
        return self._dedup(collected)

    def _tiktok_extract(self, hashtag_url: str, limit: int) -> list[VideoCandidate]:
        headers = dict(TIKTOK_HEADERS)
        if self.settings.tiktok_cookie_header:
            headers["Cookie"] = self.settings.tiktok_cookie_header
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": self.settings.crawl_max_candidates,
            "http_headers": headers,
            "socket_timeout": 20,
            "ignoreerrors": True,
        }
        candidates: list[VideoCandidate] = []
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(hashtag_url, download=False)
        except DownloadError as exc:
            logger.warning("TikTok extract error for %s: %s", hashtag_url, exc)
            return []
        except Exception as exc:
            logger.warning("TikTok unexpected error for %s: %s", hashtag_url, exc)
            return []

        for entry in (info or {}).get("entries", []) or []:
            if not entry:
                continue
            video_id = str(entry.get("id") or "")
            uploader_id = entry.get("uploader_id") or entry.get("uploader") or ""
            page_url = entry.get("url") or entry.get("webpage_url") or ""
            if not page_url and video_id and uploader_id:
                uploader_id = uploader_id.lstrip("@")
                page_url = f"https://www.tiktok.com/@{uploader_id}/video/{video_id}"
            if not page_url and video_id:
                page_url = f"https://www.tiktok.com/embed/v2/{video_id}"
            # Safety: chỉ giữ URL TikTok thật.
            if "tiktok.com" not in page_url:
                logger.warning("TikTok crawl: skip non-TikTok URL %s", page_url[:80])
                continue
            candidates.append(
                VideoCandidate(
                    platform="tiktok",
                    source_id=video_id,
                    url=page_url,
                    title=entry.get("title", "") or entry.get("description", "") or "",
                    description=entry.get("description", "") or "",
                    tags=list(entry.get("tags") or []),
                    duration=int(entry.get("duration") or 0),
                    uploader=entry.get("uploader", "") or "",
                    thumbnail=entry.get("thumbnail", "") or "",
                )
            )
            if len(candidates) >= limit * 3:
                break
        return candidates

    # ─────────── YouTube ───────────

    def crawl_youtube(self, limit: int = 10) -> list[VideoCandidate]:
        collected: list[VideoCandidate] = []
        for query in self.settings.youtube_search_queries:
            collected.extend(self._youtube_search(query, limit))
        for url in self.settings.youtube_hashtag_urls:
            collected.extend(self._youtube_extract_url(url, limit))
        return self._dedup(collected)

    def _youtube_search(self, query: str, limit: int) -> list[VideoCandidate]:
        # ytsearchN: yt-dlp pseudo-protocol — trả N search results, không cần API key.
        n = max(1, min(self.settings.crawl_max_candidates, 50))
        search_url = f"ytsearch{n}:{query}"
        return self._youtube_extract_url(search_url, limit)

    def _youtube_extract_url(self, url: str, limit: int) -> list[VideoCandidate]:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": self.settings.crawl_max_candidates,
            "http_headers": dict(YOUTUBE_HEADERS),
            "socket_timeout": 20,
            "ignoreerrors": True,
        }
        candidates: list[VideoCandidate] = []
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            logger.warning("YouTube extract error for %s: %s", url, exc)
            return []
        except Exception as exc:
            logger.warning("YouTube unexpected error for %s: %s", url, exc)
            return []

        excluded = {
            u.strip().lower().lstrip("@")
            for u in self.settings.youtube_exclude_uploaders
            if u and u.strip()
        }
        for entry in (info or {}).get("entries", []) or []:
            if not entry:
                continue
            video_id = str(entry.get("id") or "")
            page_url = entry.get("url") or entry.get("webpage_url") or ""
            if not page_url and video_id:
                page_url = f"https://www.youtube.com/watch?v={video_id}"
            # Safety guard: ytsearch đôi khi trả entry có URL không phải YouTube
            # (Bilibili/Vimeo/...) khiến yt-dlp download routes sang extractor sai
            # → fail cryptic. Reject ngay tại source.
            if "youtube.com" not in page_url and "youtu.be" not in page_url:
                logger.warning("YouTube crawl: skip non-YT URL %s", page_url[:80])
                continue
            uploader = entry.get("uploader", "") or entry.get("channel", "") or ""
            uploader_id = entry.get("uploader_id", "") or entry.get("channel_id", "") or ""
            if excluded and (
                uploader.lower().lstrip("@") in excluded
                or uploader_id.lower().lstrip("@") in excluded
            ):
                continue
            candidates.append(
                VideoCandidate(
                    platform="youtube",
                    source_id=video_id,
                    url=page_url,
                    title=entry.get("title", "") or "",
                    description=entry.get("description", "") or "",
                    tags=list(entry.get("tags") or []),
                    duration=int(entry.get("duration") or 0),
                    uploader=uploader,
                    thumbnail=entry.get("thumbnail", "") or "",
                )
            )
            if len(candidates) >= limit * 3:
                break
        return candidates

    # ─────────── Filters ───────────

    _ALLOWED_DOMAINS = ("tiktok.com", "youtube.com", "youtu.be")

    def _filter_platform(self, candidates: Iterable[VideoCandidate]) -> list[VideoCandidate]:
        kept: list[VideoCandidate] = []
        for c in candidates:
            if any(d in c.url for d in self._ALLOWED_DOMAINS):
                kept.append(c)
        return kept

    def _filter_silent(self, candidates: Iterable[VideoCandidate]) -> list[VideoCandidate]:
        positive = [kw.lower() for kw in self.settings.silent_keywords_positive]
        negative = [kw.lower() for kw in self.settings.silent_keywords_negative]
        kept: list[VideoCandidate] = []
        for candidate in candidates:
            blob = " ".join(
                [
                    candidate.title,
                    candidate.description,
                    " ".join(candidate.tags),
                ]
            ).lower()
            if any(neg in blob for neg in negative):
                continue
            if positive and not any(pos in blob for pos in positive):
                continue
            kept.append(candidate)
        return kept

    def _filter_duration(self, candidates: Iterable[VideoCandidate]) -> list[VideoCandidate]:
        lo = self.settings.crawl_min_duration_sec
        hi = self.settings.crawl_max_duration_sec
        kept: list[VideoCandidate] = []
        for candidate in candidates:
            if candidate.duration <= 0:
                kept.append(candidate)
                continue
            if lo <= candidate.duration <= hi:
                kept.append(candidate)
        return kept

    def _dedup(self, candidates: list[VideoCandidate]) -> list[VideoCandidate]:
        seen: set[str] = set()
        unique: list[VideoCandidate] = []
        for candidate in candidates:
            key = f"{candidate.platform}:{candidate.source_id or candidate.url}"
            if key in seen or not candidate.url:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique
