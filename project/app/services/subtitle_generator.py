from pathlib import Path

from app.core.config import get_settings
from app.core.utils import format_srt_timestamp


class SubtitleGeneratorService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate_srt(self, job_id: int, transcript_payload: dict) -> str:
        segments = transcript_payload.get("segments", [])
        english_text = transcript_payload.get("text_en") or transcript_payload.get("text") or ""
        srt_path = Path(self.settings.subtitle_dir) / f"{job_id}.srt"

        if not segments:
            srt_path.write_text(
                f"1\n00:00:00,000 --> 00:00:10,000\n{english_text.strip()}\n",
                encoding="utf-8",
            )
            return str(srt_path)

        lines: list[str] = []
        for index, segment in enumerate(segments, start=1):
            lines.append(str(index))
            lines.append(
                f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}"
            )
            lines.append(segment["text"].strip())
            lines.append("")
        srt_path.write_text("\n".join(lines), encoding="utf-8")
        return str(srt_path)
