import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from app.core.config import get_settings


# Ký tự ngoài Basic Multilingual Plane (emoji, ký hiệu đặc biệt) không có
# glyph trong font DejaVu → render thành □. Strip trước khi vẽ.
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]"
)


def _escape_ffmpeg_path(path: str) -> str:
    """Escape a filesystem path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _escape_drawtext(text: str) -> str:
    """Escape text for inline drawtext=text='...'. Convert ASCII apostrophe to
    the typographic right single quote (U+2019) — identical appearance but
    avoids ffmpeg's fragile quote-escape handling."""
    text = text.replace("'", "\u2019")
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def _shorten_title(text: str, max_words: int, max_chars: int) -> str:
    """Gọn title về 2-max_words từ, cap thêm theo max_chars để fit frame.
    Cắt ở word boundary, không thêm dấu chấm lửng (hook ngắn không cần)."""
    text = _EMOJI_RE.sub("", text)
    text = " ".join(text.split())
    if not text:
        return ""
    words = text.split(" ")
    if len(words) > max_words:
        words = words[:max_words]
    result = " ".join(words)
    if len(result) > max_chars:
        # Trim tiếp ở word boundary cho tới khi ≤ max_chars
        while len(result) > max_chars and " " in result:
            result = result.rsplit(" ", 1)[0]
        if len(result) > max_chars:
            result = result[:max_chars]
    return result.strip()


logger = logging.getLogger(__name__)


# Cross-platform font fallback: Linux (Docker) → Windows → macOS.
# Dùng để render watermark/title overlay khi LAUNDER_FONT_PATH config không tồn tại.
_FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _resolve_font_path(configured: str) -> str:
    """Trả font path đầu tiên tồn tại — config trước, sau đó fallback."""
    candidates = [configured] + [p for p in _FONT_FALLBACKS if p != configured]
    for path in candidates:
        if path and Path(path).exists():
            return path
    logger.warning("Không tìm thấy font nào — drawtext có thể fail. Configured: %s", configured)
    return configured


class VideoProcessorService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def burn_subtitles(
        self,
        job_id: int,
        video_path: str,
        subtitle_path: str,
        output_path: str | None = None,
    ) -> str:
        out = Path(output_path) if output_path else Path(self.settings.output_video_dir) / f"{job_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        subtitle_filter_path = subtitle_path.replace("\\", "\\\\").replace(":", "\\:")
        cmd = [
            self.settings.ffmpeg_bin,
            "-y",
            "-i",
            video_path,
            "-vf",
            f"subtitles={subtitle_filter_path}",
            "-c:a",
            "copy",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return str(out)

    # ─────────────────────── LAUNDER PIPELINE ───────────────────────
    # Xem plan.md (creator-x-bot) MODULE 3C cho spec đầy đủ. Tóm tắt:
    # Visual: auto-detect aspect ratio;
    #   - 16:9 → blur bg cover 1080x1920 + foreground scale 1080:-2 centered
    #   - 9:16 → blur bg + foreground thu 90% (khung viền động)
    # Audio: asetrate (pitch +4%) → atempo (tempo tổng 1.15x) → EQ notch
    #   1.5kHz -2dB → aecho 40ms/10% → mix noise 15% (nếu có file noise).
    # Video được setpts=PTS/tempo để khớp với audio speedup.

    def launder(
        self,
        job_id: int,
        video_path: str,
        title_text: str | None = None,
    ) -> str:
        """Apply visual + audio anti-fingerprint pass.

        Args:
            job_id: DB job id (used for output filename).
            video_path: any aspect ratio source video.
            title_text: optional headline vẽ lên vùng blur phía trên.

        Returns output path (always 1080×1920 MP4 in output_video_dir).
        """
        s = self.settings
        input_path = Path(video_path)
        out_path = Path(s.output_video_dir) / f"{job_id}.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        src_w, src_h = self._probe_dims(video_path)
        is_landscape = (src_w / max(src_h, 1)) >= s.launder_landscape_threshold

        # Resolve font once — cross-platform fallback.
        font_path = _resolve_font_path(s.launder_font_path)

        W, H = s.launder_target_w, s.launder_target_h
        if is_landscape:
            fg_chain = f"scale={W}:-2:flags=lanczos"
        else:
            fw = (int(W * s.launder_fg_scale_portrait) // 2) * 2
            fh = (int(H * s.launder_fg_scale_portrait) // 2) * 2
            fg_chain = f"scale={fw}:{fh}:flags=lanczos"

        tempo = s.launder_total_tempo

        # Overlay: title + watermark. Title đọc từ textfile để an toàn với
        # unicode/Vietnamese. Watermark inline vì text cố định ASCII.
        overlay_filters: list[str] = []
        title_file: Path | None = None
        if title_text:
            short = _shorten_title(
                title_text,
                max_words=s.launder_title_max_words,
                max_chars=s.launder_title_max_chars,
            )
            if short:
                title_file = Path(tempfile.mkstemp(prefix=f"launder_title_{job_id}_", suffix=".txt")[1])
                title_file.write_text(short, encoding="utf-8")
                # Title nhỏ gọn, 1 dòng. Auto-fit theo len(title) để không
                # tràn width. Ước lượng char-width tiếng Anh ~0.55×fontsize.
                n = max(1, len(short))
                max_fontsize = int(980 / (n * 0.55))
                if is_landscape:
                    # Landscape: blur band trên ~656px — đủ chỗ nhưng vẫn
                    # giữ gọn, cap font h/28 ≈ 68px.
                    fontsize_cap = 1920 // 28
                    title_y = "h/10"
                else:
                    # Portrait: blur border top chỉ ~96px — font phải nhỏ để
                    # cả text + box padding nằm vừa, cap h/42 ≈ 45px.
                    fontsize_cap = 1920 // 42
                    title_y = "h/48"     # ~40px — sát top, trong border
                fontsize = max(32, min(fontsize_cap, max_fontsize))
                # box padding tỉ lệ fontsize để không đè vào foreground
                box_pad = max(6, fontsize // 8)
                overlay_filters.append(
                    f"drawtext=textfile='{_escape_ffmpeg_path(str(title_file))}':"
                    f"fontfile='{_escape_ffmpeg_path(font_path)}':"
                    f"fontsize={fontsize}:fontcolor=white:"
                    f"box=1:boxcolor=black@0.55:boxborderw={box_pad}:"
                    f"x=(w-text_w)/2:y={title_y}"
                )

        wm_text = s.launder_watermark_text
        if wm_text:
            overlay_filters.append(
                f"drawtext=text='{_escape_drawtext(wm_text)}':"
                f"fontfile='{_escape_ffmpeg_path(font_path)}':"
                f"fontsize=h/38:fontcolor=white@{s.launder_watermark_opacity}:"
                f"box=1:boxcolor=black@0.30:boxborderw=6:"
                f"x=w-text_w-24:y=h-text_h-24"
            )

        overlay_chain = ("," + ",".join(overlay_filters)) if overlay_filters else ""

        # Video chain: split → blur bg + fg overlay → setpts speedup → overlays.
        video_fc = (
            f"[0:v]split=2[v_bg_src][v_fg_src];"
            f"[v_bg_src]scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H},"
            f"boxblur={s.launder_blur_strength}:{s.launder_blur_passes}[v_bg];"
            f"[v_fg_src]{fg_chain}[v_fg];"
            f"[v_bg][v_fg]overlay=(W-w)/2:(H-h)/2:format=auto,"
            f"setpts=PTS/{tempo}{overlay_chain},format=yuv420p[vout]"
        )

        # Audio chain: chuẩn hoá 48kHz (asetrate cần biết rate thật của input) →
        # pitch shift → resample về 48kHz → atempo bù → EQ → echo → aformat.
        shifted_rate = int(48000 * s.launder_pitch_shift)
        post_tempo = tempo / s.launder_pitch_shift
        audio_core = (
            f"[0:a]aresample=48000,"
            f"asetrate={shifted_rate},aresample=48000,"
            f"atempo={post_tempo:.4f},"
            f"equalizer=f={s.launder_eq_freq}:t=q:w={s.launder_eq_width}:"
            f"g={s.launder_eq_gain},"
            f"aecho={s.launder_echo_in_gain}:{s.launder_echo_out_gain}:"
            f"{s.launder_echo_delay_ms}:{s.launder_echo_decay},"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000[a0]"
        )

        has_noise = bool(s.launder_noise_path and Path(s.launder_noise_path).exists())
        inputs = ["-i", str(input_path)]
        if has_noise:
            inputs += ["-i", s.launder_noise_path]
            noise_chain = (
                f";[1:a]aloop=loop=-1:size=2e9,volume={s.launder_noise_volume},"
                f"aformat=channel_layouts=stereo[noise];"
                f"[a0][noise]amix=inputs=2:duration=first:dropout_transition=0:"
                f"normalize=0[aout]"
            )
            a_out = "[aout]"
        else:
            noise_chain = ""
            a_out = "[a0]"

        filter_complex = f"{video_fc};{audio_core}{noise_chain}"

        # Trim cuối: cắt N giây cuối ở output để bỏ end-card watermark của creator gốc.
        # tempo đã làm video ngắn lại (src_dur / tempo); trim_end_sec áp dụng SAU.
        trim_args: list[str] = []
        if s.launder_trim_end_sec > 0:
            src_dur = self._probe_duration(video_path)
            if src_dur > 0:
                target_dur = (src_dur / tempo) - s.launder_trim_end_sec
                if target_dur > 1.0:
                    trim_args = ["-t", f"{target_dur:.3f}"]
                else:
                    logger.warning(
                        "trim_end_sec=%s quá lớn so với video %ss — skip trim",
                        s.launder_trim_end_sec, src_dur,
                    )

        maxrate = f"{s.launder_maxrate_kbps}k"
        bufsize = f"{s.launder_maxrate_kbps * 2}k"
        cmd = [
            s.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", a_out,
            *trim_args,
            "-c:v", "libx264",
            "-preset", s.launder_preset,
            "-crf", str(s.launder_crf),
            "-maxrate", maxrate,
            "-bufsize", bufsize,
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
            "-ac", "2", "-ar", "48000",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]
        logger.info(
            "[launder] job=%s landscape=%s title=%r → %s",
            job_id, is_landscape, (title_text or "")[:40], out_path,
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            logger.error(
                "[launder] job=%s ffmpeg failed: %s",
                job_id,
                exc.stderr.decode(errors="ignore")[-1500:] if exc.stderr else "",
            )
            raise
        finally:
            if title_file:
                title_file.unlink(missing_ok=True)
        return str(out_path)

    def _probe_dims(self, video_path: str) -> tuple[int, int]:
        """Return (width, height) of first video stream."""
        cmd = [
            self.settings.ffprobe_bin, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            video_path,
        ]
        out = subprocess.check_output(cmd, text=True)
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        return int(stream.get("width") or 1920), int(stream.get("height") or 1080)

    def _probe_duration(self, video_path: str) -> float:
        """Return container duration in seconds (0.0 nếu probe fail)."""
        cmd = [
            self.settings.ffprobe_bin, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path,
        ]
        try:
            out = subprocess.check_output(cmd, text=True)
            return float((json.loads(out).get("format") or {}).get("duration") or 0.0)
        except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("ffprobe duration failed for %s: %s", video_path, exc)
            return 0.0
