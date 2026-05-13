"""Download No-Copyright music to assets/music/<mood>/.

Sources:
  - mixkit: scrape directly, no API key needed
  - pixabay: scrape Pixabay Music (free, no attribution required)
  - ncs: yt-dlp from YouTube NCS channel (needs cookies if VPS blocked)

Usage:
    python scripts/fetch_music.py --source mixkit --mood all --limit 20
    python scripts/fetch_music.py --source pixabay --mood viral --limit 25
    python scripts/fetch_music.py --source ncs --mood chill --limit 10 --cookies cookies.txt

License Mixkit: free for commercial + personal, no attribution.
License Pixabay: free for commercial + personal, no attribution.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MUSIC_ROOT = PROJECT_ROOT / "assets" / "music"
BLACKLIST_PATH = MUSIC_ROOT / "_blacklist.json"


MIXKIT_MOOD_GENRES = {
    "chill": ["chill", "lo-fi", "ambient"],
    "cute": ["happy", "kids", "funny"],
    "cinematic": ["cinematic", "epic", "dramatic", "action"],
    "viral": [
        "upbeat", "dance", "electronic", "pop", "hip-hop",
        "trap", "funk", "edm", "dubstep", "techno", "disco",
    ],
}

PIXABAY_MOOD_QUERIES = {
    "chill": ["chill", "lofi", "ambient", "calm beat"],
    "cute": ["happy", "fun", "cheerful", "playful"],
    "cinematic": ["cinematic", "epic", "dramatic", "trailer"],
    "viral": [
        "trending", "tiktok", "viral beat", "dance", "edm", "trap",
        "hip hop beat", "electronic", "bass", "pop beat", "energetic",
        "upbeat", "party", "phonk", "future bass",
    ],
}

NCS_PLAYLISTS = {
    "chill": ["https://www.youtube.com/playlist?list=PLRBp0Fe2GpgnIh0AiYKh7o7HnYAej-5ph"],
    "cute": ["https://www.youtube.com/playlist?list=PLRBp0Fe2GpglKZxbe7WgoMzPAHEsZ0WVa"],
    "cinematic": ["https://www.youtube.com/playlist?list=PLRBp0Fe2Gpgkm5S8fhRI1Q0KkoF6iCBe4"],
    "viral": ["https://www.youtube.com/playlist?list=PLRBp0Fe2GpgnYaRjryb6dCnSGMuMYrRap"],
}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)


def load_blacklist() -> set[str]:
    if BLACKLIST_PATH.exists():
        return set(json.loads(BLACKLIST_PATH.read_text(encoding="utf-8")))
    return set()


def save_blacklist(bl: set[str]) -> None:
    BLACKLIST_PATH.write_text(
        json.dumps(sorted(bl), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ensure_dir(mood: str) -> Path:
    target = MUSIC_ROOT / mood
    target.mkdir(parents=True, exist_ok=True)
    return target


def fetch_mixkit(mood: str, limit: int, max_pages: int = 6) -> int:
    target = ensure_dir(mood)
    genres = MIXKIT_MOOD_GENRES.get(mood, [mood])
    existing = {p.stem for p in target.glob("mixkit_*.mp3")}
    blacklist = load_blacklist()

    url_re = re.compile(r'https://assets\.mixkit\.co/(music|active)/[^"\s]+\.mp3')
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})

    urls: list[str] = []
    for genre in genres:
        for page in range(1, max_pages + 1):
            page_url = f"https://mixkit.co/free-stock-music/{genre}/"
            if page > 1:
                page_url = f"https://mixkit.co/free-stock-music/{genre}/?page={page}"
            try:
                resp = session.get(page_url, timeout=20)
                resp.raise_for_status()
            except requests.RequestException:
                continue
            new_full = list(dict.fromkeys(m.group(0) for m in url_re.finditer(resp.text)))
            urls.extend(u for u in new_full if u not in urls)
            time.sleep(0.6)
            if len(urls) >= limit * 3:
                break
        if len(urls) >= limit * 3:
            break

    if not urls:
        print(f"[mixkit] No tracks found for mood '{mood}'.")
        return 0

    count = 0
    for url in urls:
        if count >= limit:
            break
        track_id = url.rstrip("/").split("/")[-1].replace(".mp3", "")
        name = f"mixkit_{mood}_{track_id}"
        if name in existing or name in blacklist:
            continue
        out_path = target / f"{name}.mp3"
        try:
            r = session.get(url, stream=True, timeout=60)
            r.raise_for_status()
            with out_path.open("wb") as fh:
                for chunk in r.iter_content(8192):
                    fh.write(chunk)
            size = out_path.stat().st_size
            if size < 50_000:
                out_path.unlink(missing_ok=True)
                blacklist.add(name)
                continue
            count += 1
            print(f"[mixkit] OK {name}.mp3 ({size // 1024} KB)")
            time.sleep(0.4)
        except requests.RequestException as exc:
            print(f"[mixkit] download error {url}: {exc}")

    save_blacklist(blacklist)
    print(f"[mixkit] {mood}: +{count} tracks -> {target}")
    return count


def fetch_pixabay(mood: str, limit: int) -> int:
    target = ensure_dir(mood)
    queries = PIXABAY_MOOD_QUERIES.get(mood, [mood])
    existing = {p.stem for p in target.glob("pixabay_*.mp3")}
    blacklist = load_blacklist()

    session = requests.Session()
    session.headers.update({
        "User-Agent": BROWSER_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://pixabay.com/music/",
    })

    download_re = re.compile(r'https://cdn\.pixabay\.com/download/audio[^"\s\?]+')
    track_id_re = re.compile(r'/music/([^/]+)-(\d+)/')

    urls: list[tuple[str, str]] = []
    for query in queries:
        search_url = f"https://pixabay.com/music/search/{query.replace(' ', '%20')}/"
        try:
            resp = session.get(search_url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException:
            continue

        for m in track_id_re.finditer(resp.text):
            slug, tid = m.group(1), m.group(2)
            detail_url = f"https://pixabay.com/music/{slug}-{tid}/"
            try:
                detail = session.get(detail_url, timeout=15)
                detail.raise_for_status()
            except requests.RequestException:
                continue
            dl_matches = download_re.findall(detail.text)
            if dl_matches:
                urls.append((tid, dl_matches[0]))
            time.sleep(0.5)
            if len(urls) >= limit * 2:
                break
        time.sleep(0.8)
        if len(urls) >= limit * 2:
            break

    if not urls:
        print(f"[pixabay] No tracks found for mood '{mood}'.")
        return 0

    count = 0
    for tid, url in urls:
        if count >= limit:
            break
        name = f"pixabay_{mood}_{tid}"
        if name in existing or name in blacklist:
            continue
        out_path = target / f"{name}.mp3"
        try:
            r = session.get(url, stream=True, timeout=60)
            r.raise_for_status()
            with out_path.open("wb") as fh:
                for chunk in r.iter_content(8192):
                    fh.write(chunk)
            size = out_path.stat().st_size
            if size < 50_000:
                out_path.unlink(missing_ok=True)
                blacklist.add(name)
                continue
            count += 1
            print(f"[pixabay] OK {name}.mp3 ({size // 1024} KB)")
            time.sleep(0.4)
        except requests.RequestException as exc:
            print(f"[pixabay] download error {url}: {exc}")

    save_blacklist(blacklist)
    print(f"[pixabay] {mood}: +{count} tracks -> {target}")
    return count


def fetch_ncs(mood: str, limit: int, cookies: str | None) -> int:
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("[ncs] yt-dlp not installed. Run: pip install yt-dlp")
        return 0

    target = ensure_dir(mood)
    playlists = NCS_PLAYLISTS.get(mood, [])
    if not playlists:
        return 0

    manifest_path = target / "_ncs_manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(target / "ncs_%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
        ],
        "noplaylist": False,
        "playlistend": limit,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
    }
    if cookies:
        opts["cookiefile"] = cookies

    count = 0
    with YoutubeDL(opts) as ydl:
        for playlist_url in playlists:
            try:
                info = ydl.extract_info(playlist_url, download=True)
            except Exception as exc:
                print(f"[ncs] Playlist error {playlist_url}: {exc}")
                continue
            for entry in (info or {}).get("entries", []) or []:
                if not entry:
                    continue
                video_id = entry.get("id")
                if video_id and video_id not in existing:
                    existing[video_id] = {"title": entry.get("title") or video_id, "mood": mood}
                    count += 1
                if count >= limit:
                    break
            if count >= limit:
                break

    manifest_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    print(f"[ncs] {mood}: +{count} tracks -> {target}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Download No-Copyright music to assets/music/")
    parser.add_argument("--source", choices=["mixkit", "pixabay", "ncs", "all"], default="mixkit")
    parser.add_argument("--mood", choices=["chill", "cute", "cinematic", "viral", "all"], default="all")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--max-pages", type=int, default=6, help="Max pages per tag (mixkit)")
    parser.add_argument("--cookies", default="", help="(NCS) cookie file for yt-dlp")
    args = parser.parse_args()

    moods = ["chill", "cute", "cinematic", "viral"] if args.mood == "all" else [args.mood]
    sources = (
        ["mixkit", "pixabay", "ncs"] if args.source == "all"
        else [args.source]
    )

    total = 0
    for mood in moods:
        for source in sources:
            if source == "mixkit":
                total += fetch_mixkit(mood, args.limit, args.max_pages)
            elif source == "pixabay":
                total += fetch_pixabay(mood, args.limit)
            elif source == "ncs":
                total += fetch_ncs(mood, args.limit, args.cookies or None)

    print(f"\n[DONE] Completed: {total} new tracks. Library: {MUSIC_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
