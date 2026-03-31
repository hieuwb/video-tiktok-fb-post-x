import subprocess
from pathlib import Path

from app.core.config import get_settings


class VideoProcessorService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def burn_subtitles(self, job_id: int, video_path: str, subtitle_path: str) -> str:
        output_path = Path(self.settings.output_video_dir) / f"{job_id}.mp4"
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
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return str(output_path)
