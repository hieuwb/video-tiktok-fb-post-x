from __future__ import annotations

import json
import logging
import random
import subprocess
from pathlib import Path

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}


class AudioReplacerError(RuntimeError):
    pass


class AudioReplacerService:
    """Xóa audio gốc của video và ghép nhạc No-Copyright từ assets/music/<mood>/.

    Luồng chuẩn:
        svc.replace_audio(video_path, mood='cute') → Path (video mới, đã thay audio)

    Các bước nhỏ (dùng riêng nếu cần):
        strip_audio() → video silent
        pick_music(mood, duration) → mp3 trong library
        mix_music(silent_video, music_track) → video có nhạc mới
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # ─────────── High-level API ───────────

    def replace_audio(
        self,
        video_path: str | Path,
        mood: str | None = None,
        music_path: str | Path | None = None,
    ) -> Path:
        video_path = Path(video_path)
        if not video_path.exists():
            raise AudioReplacerError(f"Video not found: {video_path}")

        duration = self._probe_duration(video_path)
        if duration <= 0:
            raise AudioReplacerError(f"Cannot probe duration: {video_path}")

        if mood is not None:
            mood = self.refine_mood_by_energy(video_path, mood)

        if music_path is None:
            music_path = self.pick_music(mood or self.settings.music_default_mood, duration)
        music_path = Path(music_path)
        if not music_path.exists():
            raise AudioReplacerError(f"Music track not found: {music_path}")

        silent = self.strip_audio(video_path)
        try:
            return self.mix_music(silent, music_path, duration)
        finally:
            silent.unlink(missing_ok=True)

    # ─────────── Steps ───────────

    def strip_audio(self, video_path: str | Path) -> Path:
        video_path = Path(video_path)
        out = video_path.with_name(f"{video_path.stem}.silent{video_path.suffix}")
        cmd = [
            self.settings.ffmpeg_bin, "-y",
            "-loglevel", "error",
            "-i", str(video_path),
            "-c:v", "copy",
            "-an",
            str(out),
        ]
        self._run(cmd)
        return out

    def pick_music(self, mood: str, target_duration: float = 0) -> Path:
        library = Path(self.settings.music_library_dir)
        preferred = library / mood
        fallback = library / self.settings.music_default_mood

        tracks = self._list_tracks(preferred)
        if not tracks and preferred != fallback:
            logger.info("Mood '%s' empty, fallback '%s'", mood, self.settings.music_default_mood)
            tracks = self._list_tracks(fallback)
        if not tracks:
            tracks = self._list_tracks(library, recursive=True)
        if not tracks:
            raise AudioReplacerError(
                f"No music in {library}. Run scripts/fetch_anime_music.py first."
            )

        recent = self._load_recent(library)
        fresh = [t for t in tracks if t.name not in recent]
        if not fresh:
            self._clear_recent(library)
            fresh = tracks

        anime_fresh = [t for t in fresh if t.stem.startswith("anime_")]
        pool = anime_fresh if anime_fresh else fresh

        if target_duration > 0:
            pick = self._pick_best_fit(pool, target_duration)
        else:
            pick = random.choice(pool)

        self._record_recent(library, pick.name)
        return pick

    _DURATION_TOLERANCE = 5.0  # seconds

    def _pick_best_fit(self, tracks: list[Path], target: float) -> Path:
        """Pick track whose duration is within ±5s of the video duration.

        Priority:
        1. Tracks within ±5s of target → pick randomly from top 3 closest.
        2. If none within tolerance, pick the closest overall (will be looped/trimmed).
        """
        scored: list[tuple[float, float, Path]] = []
        for t in tracks:
            dur = self._probe_duration(t)
            if dur <= 0:
                continue
            diff = abs(dur - target)
            scored.append((diff, dur, t))
        if not scored:
            return random.choice(tracks)

        scored.sort(key=lambda x: x[0])

        within_tolerance = [(diff, dur, t) for diff, dur, t in scored
                           if diff <= self._DURATION_TOLERANCE]
        if within_tolerance:
            top_n = min(3, len(within_tolerance))
            pick = random.choice([s[2] for s in within_tolerance[:top_n]])
            logger.info(
                "pick_music: target=%.1fs, picked %s (%.1fs, diff=%.1fs) — within ±5s",
                target, pick.name,
                within_tolerance[0][1] if top_n == 1 else self._probe_duration(pick),
                abs(self._probe_duration(pick) - target),
            )
            return pick

        best = scored[0]
        logger.warning(
            "pick_music: no track within ±%.0fs of target %.1fs. "
            "Best match: %s (%.1fs, diff=%.1fs). Will loop/trim.",
            self._DURATION_TOLERANCE, target, best[2].name, best[1], best[0],
        )
        return scored[0][2]

    # ─────────── Recent-picks dedup ───────────

    _RECENT_FILE = "_recent_picks.json"
    _RECENT_MAX = 20

    def _load_recent(self, library: Path) -> set[str]:
        path = library / self._RECENT_FILE
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, OSError):
            return set()

    def _record_recent(self, library: Path, filename: str) -> None:
        path = library / self._RECENT_FILE
        recent = list(self._load_recent(library))
        recent.append(filename)
        if len(recent) > self._RECENT_MAX:
            recent = recent[-self._RECENT_MAX:]
        try:
            path.write_text(json.dumps(recent, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def _clear_recent(self, library: Path) -> None:
        path = library / self._RECENT_FILE
        path.unlink(missing_ok=True)

    def mix_music(
        self,
        silent_video: str | Path,
        music_path: str | Path,
        target_duration: float | None = None,
    ) -> Path:
        silent_video = Path(silent_video)
        music_path = Path(music_path)
        out = silent_video.with_name(silent_video.stem.replace(".silent", "") + ".audioreplaced.mp4")

        video_dur = self._probe_duration(silent_video)
        music_dur = self._probe_duration(music_path)

        output_dur = video_dur

        volume = max(0.0, min(2.0, self.settings.music_volume))
        fade_in = max(0.0, self.settings.music_fade_in_sec)
        fade_out = max(0.0, self.settings.music_fade_out_sec)

        gap = (output_dur - music_dur) if music_dur > 0 else 0

        # Determine strategy based on duration difference
        # Case 1: Music within ±5s of video → trim to video length, fade at video end
        # Case 2: Music much shorter (>5s gap) → loop to fill video duration
        # Case 3: Music much longer → trim at video duration with fade-out
        loop_music = self.settings.music_loop_if_shorter and gap > self._DURATION_TOLERANCE

        # Fade-out always anchored to video end (not music end)
        fade_out_start = max(0.0, output_dur - fade_out)

        audio_filter_parts = [f"volume={volume}"]
        if fade_in > 0:
            audio_filter_parts.append(f"afade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            audio_filter_parts.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out}")

        # If music is slightly shorter than video (within tolerance), pad silence
        # so audio track matches video length exactly (no abrupt cut)
        if not loop_music and 0 < gap <= self._DURATION_TOLERANCE:
            audio_filter_parts.append(f"apad=whole_dur={output_dur:.3f}")

        audio_filter = ",".join(audio_filter_parts)

        cmd = [self.settings.ffmpeg_bin, "-y", "-loglevel", "error"]
        cmd += ["-i", str(silent_video)]
        if loop_music:
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(music_path)]
        cmd += [
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-af", audio_filter,
            "-t", f"{output_dur:.3f}",
            "-movflags", "+faststart",
            str(out),
        ]
        logger.info(
            "mix_music: video=%.1fs music=%.1fs → output=%.1fs (gap=%.1fs loop=%s pad=%s)",
            video_dur, music_dur, output_dur, gap, loop_music,
            (not loop_music and 0 < gap <= self._DURATION_TOLERANCE),
        )
        self._run(cmd)
        return out

    # ─────────── Energy detection ───────────

    _SOFT_MOODS = {"chill", "cute"}
    _INTENSE_MOODS = {"cinematic", "viral"}

    _ENERGY_MAP_SOFT = {"cinematic": "chill", "viral": "chill"}
    _ENERGY_MAP_INTENSE = {"chill": "cinematic", "cute": "viral"}

    def refine_mood_by_energy(self, video_path: str | Path, tag_mood: str) -> str:
        rms = self._probe_energy(video_path)
        if rms is None:
            return tag_mood

        if rms < -28.0:
            logger.info("Audio soft (RMS %.1f dB), mood %s -> %s",
                        rms, tag_mood,
                        self._ENERGY_MAP_SOFT.get(tag_mood, tag_mood))
            return self._ENERGY_MAP_SOFT.get(tag_mood, tag_mood)

        if rms > -18.0:
            logger.info("Audio intense (RMS %.1f dB), mood %s -> %s",
                        rms, tag_mood,
                        self._ENERGY_MAP_INTENSE.get(tag_mood, tag_mood))
            return self._ENERGY_MAP_INTENSE.get(tag_mood, tag_mood)

        return tag_mood

    def _probe_energy(self, media_path: str | Path) -> float | None:
        cmd = [
            self.settings.ffmpeg_bin,
            "-i", str(media_path),
            "-vn",
            "-af", "astats=metadata=1:reset=0,ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f", "null", "-",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            last_rms = None
            for line in result.stderr.splitlines():
                if "lavfi.astats.Overall.RMS_level" in line:
                    val = line.split("=")[-1].strip()
                    if val != "-inf":
                        last_rms = float(val)
            return last_rms
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            logger.warning("Energy probe failed for %s: %s", media_path, exc)
            return None

    # ─────────── Helpers ───────────

    def _list_tracks(self, folder: Path, recursive: bool = False) -> list[Path]:
        if not folder.exists() or not folder.is_dir():
            return []
        iterator = folder.rglob("*") if recursive else folder.iterdir()
        return sorted(
            p for p in iterator if p.is_file() and p.suffix.lower() in _AUDIO_EXTS
        )

    def _probe_duration(self, media_path: str | Path) -> float:
        cmd = [
            self.settings.ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(media_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            payload = json.loads(result.stdout or "{}")
            return float((payload.get("format") or {}).get("duration") or 0.0)
        except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("ffprobe duration failed for %s: %s", media_path, exc)
            return 0.0

    def _run(self, cmd: list[str]) -> None:
        logger.debug("ffmpeg cmd: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise AudioReplacerError(
                f"ffmpeg failed (code {result.returncode}): {result.stderr.strip()[:500]}"
            )


def mood_for_tags(title: str, tags: list[str] | None = None) -> str:
    """Suy đoán mood từ title + tags → chọn thư mục nhạc phù hợp.

    Scope: anime + life hack (kênh global).
    - Anime edit / AMV / aesthetic: → cinematic (epic music boost engagement)
    - Life hack / satisfying / DIY: → viral (upbeat)
    - ASMR / soothing: → chill (calming track)
    """
    blob = (title + " " + " ".join(tags or [])).lower()
    cinematic_hits = (
        "anime", "amv", "anime edit", "anime shorts", "manga", "edit",
        "aesthetic", "cinematic", "epic", "dramatic", "landscape", "aerial",
    )
    viral_hits = (
        "hack", "life hack", "lifehack", "kitchen hack", "trick", "diy",
        "craft", "satisfying", "oddly satisfying", "clever", "kitchen tip",
        "organize", "viral", "trending", "challenge",
    )
    asmr_hits = (
        "asmr", "tingles", "soothing", "relaxing", "sleep", "calm",
        "white noise", "rain sound", "kinetic sand", "slime", "soap cut",
    )
    # Order: cinematic first (anime is high priority), then viral, then asmr.
    if any(kw in blob for kw in cinematic_hits):
        return "cinematic"
    if any(kw in blob for kw in viral_hits):
        return "viral"
    if any(kw in blob for kw in asmr_hits):
        return "chill"
    return "cinematic"
