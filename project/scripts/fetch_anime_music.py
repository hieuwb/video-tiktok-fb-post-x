"""Download viral anime OST / edit music via yt-dlp.

Usage:
    python scripts/fetch_anime_music.py --mood cinematic --limit 15
    python scripts/fetch_anime_music.py --mood viral --limit 20
    python scripts/fetch_anime_music.py --mood all --limit 10
    python scripts/fetch_anime_music.py --mood cinematic --limit 10 --cookies cookies.txt
    python scripts/fetch_anime_music.py --short --limit 30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MUSIC_ROOT = PROJECT_ROOT / "assets" / "music"

ANIME_QUERIES = {
    "cinematic": [
        # Anime OST viral
        "anime ost epic viral 2024 2025",
        "attack on titan ost",
        "demon slayer ost kamado tanjiro no uta",
        "jujutsu kaisen ost",
        "solo leveling ost arise",
        "vinland saga ost",
        "chainsaw man ost",
        "one punch man sad theme",
        "naruto sadness and sorrow",
        "bleach number one",
        "tokyo ghoul unravel ost",
        "spy x family ost",
        "frieren ost",
        "blue lock ost",
        "mushoku tensei ost",
        "made in abyss ost",
        "violet evergarden ost",
        "your name ost sparkle",
        "anime emotional ost playlist",
        "epic anime soundtrack mix",
    ],
    "viral": [
        # Phonk / edit music viral cho anime
        "phonk anime edit music",
        "anime edit phonk 2024",
        "close eyes dvrst",
        "metamorphosis interworld",
        "sahara hensonn",
        "brazilian phonk anime",
        "kordhell murder in my mind",
        "nxrth phonk anime",
        "catnappers phonk",
        "anime edit song viral tiktok",
        "montagem coral phonk",
        "drift phonk anime edit",
        "mc orochi mega phonk",
        "keraunos phonk",
        # Anime openings viral
        "idol yoasobi",
        "kick back kenshi yonezu",
        "zankyou zankyo no terror ost",
        "kaikai kitan jujutsu kaisen",
        "bling bang bang born mashle",
        "anime opening viral tiktok 2024",
    ],
    "chill": [
        # Lo-fi anime / chill anime vibes
        "lo-fi anime chill beats",
        "anime lofi hip hop mix",
        "chill anime ost study",
        "ghibli lofi",
        "anime rain lofi",
    ],
    "cute": [
        # Cute anime / kawaii
        "kawaii anime music",
        "cute anime ost",
        "anime slice of life ost",
        "spy x family comedy ost",
        "komi cant communicate ost",
    ],
}

# Queries targeting various durations for video content
SHORT_QUERIES = {
    "cinematic": [
        # ~15-30s
        "anime ost 15 seconds edit",
        "anime sad moment short clip",
        "anime emotional 30 seconds ost",
        "attack on titan ost short clip",
        "demon slayer ost 30 sec edit",
        "anime cinematic moment 30 sec",
        # ~45-60s
        "anime ost 1 minute epic",
        "jujutsu kaisen ost short edit",
        "frieren ost short version",
        "vinland saga ost 1 minute",
        "mushoku tensei ost short",
        "chainsaw man ost short",
        "anime battle ost 45 seconds",
        "one piece epic ost 1 min",
        "bleach ost short version",
        # ~75-90s
        "anime ost 90 seconds epic",
        "attack on titan rumbling short",
        "naruto ost emotional 90 sec",
        "anime soundtrack 90 seconds",
        "blue lock ost edit 1 min",
        # ~120-150s
        "anime ost 2 minutes epic",
        "demon slayer kamado tanjiro no uta short",
        "made in abyss ost 2 min",
        "violet evergarden ost short version",
        "your name sparkle 2 min edit",
        "anime emotional ost 2 minutes",
    ],
    "viral": [
        # ~15-30s
        "anime edit audio 15 seconds viral",
        "phonk beat 30 seconds short",
        "tiktok anime sound 15 sec",
        "anime amv audio short viral",
        "brazilian phonk 30 sec drop",
        "drift phonk 15 seconds",
        # ~45-60s
        "phonk 1 minute beat anime",
        "metamorphosis interworld edit audio",
        "anime tiktok trending sound 2024 2025",
        "kordhell phonk 1 minute",
        "anime edit audio viral 45 sec",
        "bling bang bang born edit audio",
        "next phonk beat 1 min",
        "mc orochi phonk beat",
        "anime badass moment audio edit",
        # ~75-90s
        "phonk beat 90 seconds anime",
        "brazilian phonk 90 sec slowed",
        "anime edit music 90 seconds viral",
        "nxrth phonk anime 90 sec",
        "override kslv noh 90 sec",
        # ~120-150s
        "phonk mix 2 minutes anime",
        "anime phonk edit compilation audio",
        "brazilian phonk 2 min slowed reverb",
        "close eyes dvrst full edit",
        "sahara hensonn edit audio full",
        "anime amv audio 2 minutes viral",
    ],
}


def fetch_short(limit: int = 30, cookies: str | None = None) -> int:
    """Download tracks (10-180s) for various video durations."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("[short] yt-dlp not installed. Run: pip install yt-dlp")
        return 0

    total = 0
    for mood, queries in SHORT_QUERIES.items():
        target = MUSIC_ROOT / mood
        target.mkdir(parents=True, exist_ok=True)

        manifest_path = target / "_anime_manifest.json"
        manifest: dict = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        opts = {
            "format": "140/251/bestaudio",
            "outtmpl": str(target / "anime_%(id)s.%(ext)s"),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
            ],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        if cookies:
            opts["cookiefile"] = cookies

        count = 0
        with YoutubeDL(opts) as ydl:
            for query in queries:
                if count >= limit:
                    break
                search_query = f"ytsearch5:{query}"
                try:
                    info = ydl.extract_info(search_query, download=False)
                except Exception as exc:
                    print(f"[short] search error '{query}': {exc}")
                    continue

                entries = (info or {}).get("entries", []) or []
                for entry in entries:
                    if count >= limit:
                        break
                    if not entry:
                        continue
                    vid = entry.get("id", "")
                    title = entry.get("title", "")
                    duration = entry.get("duration", 0) or 0

                    if vid in manifest:
                        continue
                    if duration < 10 or duration > 180:
                        continue

                    try:
                        ydl.download([f"https://www.youtube.com/watch?v={vid}"])
                    except Exception as exc:
                        print(f"[short] download error {vid}: {exc}")
                        continue

                    out_file = target / f"anime_{vid}.mp3"
                    if out_file.exists() and out_file.stat().st_size > 50_000:
                        manifest[vid] = {
                            "title": title,
                            "mood": mood,
                            "query": query,
                            "duration": duration,
                        }
                        count += 1
                        safe_title = title[:60].encode("ascii", "replace").decode()
                        print(f"[short/{mood}] OK anime_{vid}.mp3 - {safe_title} ({duration}s)")
                    else:
                        out_file.unlink(missing_ok=True)

        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[short] {mood}: +{count} tracks")
        total += count

    print(f"[short] Total: +{total} tracks (10-180s)")
    return total


def fetch_anime(mood: str, limit: int, cookies: str | None = None) -> int:
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("[anime] yt-dlp not installed. Run: pip install yt-dlp")
        return 0

    target = MUSIC_ROOT / mood
    target.mkdir(parents=True, exist_ok=True)

    manifest_path = target / "_anime_manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    queries = ANIME_QUERIES.get(mood, [])
    if not queries:
        print(f"[anime] No queries for mood '{mood}'")
        return 0

    opts = {
        "format": "140/251/bestaudio",
        "outtmpl": str(target / "anime_%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
        ],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    if cookies:
        opts["cookiefile"] = cookies

    count = 0
    with YoutubeDL(opts) as ydl:
        for query in queries:
            if count >= limit:
                break
            search_query = f"ytsearch3:{query}"
            try:
                info = ydl.extract_info(search_query, download=False)
            except Exception as exc:
                print(f"[anime] search error '{query}': {exc}")
                continue

            entries = (info or {}).get("entries", []) or []
            for entry in entries:
                if count >= limit:
                    break
                if not entry:
                    continue
                vid = entry.get("id", "")
                title = entry.get("title", "")
                duration = entry.get("duration", 0) or 0

                if vid in manifest:
                    continue
                if duration > 600 or duration < 30:
                    continue

                try:
                    ydl.download([f"https://www.youtube.com/watch?v={vid}"])
                except Exception as exc:
                    print(f"[anime] download error {vid}: {exc}")
                    continue

                out_file = target / f"anime_{vid}.mp3"
                if out_file.exists() and out_file.stat().st_size > 100_000:
                    manifest[vid] = {
                        "title": title,
                        "mood": mood,
                        "query": query,
                        "duration": duration,
                    }
                    count += 1
                    dur_str = f"{duration // 60}:{duration % 60:02d}"
                    safe_title = title[:60].encode("ascii", "replace").decode()
                    print(f"[anime] OK anime_{vid}.mp3 - {safe_title} ({dur_str})")
                else:
                    out_file.unlink(missing_ok=True)

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[anime] {mood}: +{count} tracks -> {target}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Download viral anime music via yt-dlp")
    parser.add_argument("--mood", choices=["chill", "cute", "cinematic", "viral", "all"], default="cinematic")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--short", action="store_true", help="Download short tracks (20-100s) for video content")
    parser.add_argument("--cookies", default="", help="YouTube cookie file for yt-dlp")
    args = parser.parse_args()

    total = 0
    if args.short:
        total = fetch_short(args.limit, args.cookies or None)
    else:
        moods = ["cinematic", "viral", "chill", "cute"] if args.mood == "all" else [args.mood]
        for mood in moods:
            total += fetch_anime(mood, args.limit, args.cookies or None)

    print(f"\n[DONE] Completed: {total} anime tracks. Library: {MUSIC_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
