from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass
class TranscriptResult:
    language: str
    text: str
    segments: list[dict]

    def to_payload(self, transcript_en: str, segments_en: list[dict] | None = None) -> dict:
        return {
            "language": self.language,
            "text": self.text,
            "text_en": transcript_en,
            "segments": segments_en or self.segments,
        }


class TranscriberService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model = None

    @property
    def model(self):
        if self._model is None:
            import whisper

            self._model = whisper.load_model("base")
        return self._model

    def extract_audio(self, job_id: int, video_path: str | None) -> str:
        if not video_path:
            raise ValueError("raw_video_path is missing.")
        output_path = Path(self.settings.audio_dir) / f"{job_id}.mp3"
        cmd = [
            self.settings.ffmpeg_bin,
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return str(output_path)

    def transcribe(self, audio_path: str) -> TranscriptResult:
        result = self.model.transcribe(audio_path, task="transcribe", verbose=False)
        segments = [
            {
                "id": seg.get("id"),
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": seg["text"].strip(),
            }
            for seg in result.get("segments", [])
        ]
        transcript_path = Path(self.settings.transcript_dir) / f"{Path(audio_path).stem}.json"
        transcript_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return TranscriptResult(
            language=result.get("language", "unknown"),
            text=result.get("text", "").strip(),
            segments=segments,
        )
