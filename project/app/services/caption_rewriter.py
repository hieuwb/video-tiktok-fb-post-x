from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.core.config import get_settings
from app.db.models import Job
from app.services.profile_selector import CaptionProfile
from app.services.translator import TranslatorService


PROMPT_TEMPLATE = """You are a social media caption rewriting model.

Task:
Given a source video URL, source title, source caption, original transcript, English transcript, detected language, target output language, and style profile, generate a public-safe caption package for posting on X.

Output valid JSON only:
{{
  "summary": "string",
  "risk_flags": ["string"],
  "captions": {{
    "neutral": "string",
    "public_clean": "string",
    "more_engaging": "string"
  }},
  "hashtags": ["#tag1", "#tag2", "#tag3"]
}}

Rules:
- Output summary and all captions in the target output language
- Preserve the original source caption meaning as closely as possible
- Prefer translating the original source caption instead of rewriting it
- Only edit wording when needed to remove explicit sensitive language, private personal details, insults, harassment, or unsafe wording
- If the source caption is already public-safe, keep the wording very close to the original
- do not invent facts
- do not include private or sensitive details unless already clearly public in the source
- captions must be concise and suitable for X
- each caption must be <= 260 characters
- public_clean should be the safest default
- if content is sensitive, add appropriate risk_flags
- Use style and tone lightly; do not over-polish or add hype unless necessary
- Hashtags should match the target language where appropriate

Source video URL: {source_url}
Source title: {source_title}
Source caption: {source_caption}
Original transcript: {transcript_original}
English transcript: {transcript_en}
Detected language: {language}
Target language code: {target_language}
Target language name: {target_language_name}
Profile code: {profile_code}
Caption style: {caption_style}
Tone guidance: {tone_guidance}
"""


class CaptionRewriterService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.translator = TranslatorService()

    def generate_caption_package(self, job: Job, profile: CaptionProfile) -> dict[str, Any]:
        if not self.settings.deepseek_api_key:
            return self._fallback(job, profile)

        prompt = PROMPT_TEMPLATE.format(
            source_url=job.source_url,
            source_title=job.source_title or "",
            source_caption=job.source_caption or "",
            transcript_original=job.transcript_original or "",
            transcript_en=job.transcript_en or "",
            language="unknown" if not job.transcript_original else "detected_from_transcript",
            target_language=profile.language,
            target_language_name=profile.language_name,
            profile_code=profile.code,
            caption_style=profile.style,
            tone_guidance=profile.tone,
        )

        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        try:
            response = requests.post(
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            raw_content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(self._strip_code_fences(raw_content))
            return self._sanitize(parsed, profile)
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError):
            return self._fallback(job, profile)

    def _sanitize(self, payload: dict[str, Any], profile: CaptionProfile) -> dict[str, Any]:
        captions = payload.get("captions", {})
        hashtags = payload.get("hashtags", [])[:6]
        neutral = self._translate_for_profile(self._ensure_caption(captions.get("neutral", ""), profile), profile)
        public_clean = self._translate_for_profile(self._ensure_caption(captions.get("public_clean", ""), profile), profile)
        more_engaging = self._translate_for_profile(self._ensure_caption(captions.get("more_engaging", ""), profile), profile)
        return {
            "summary": self._translate_for_profile(str(payload.get("summary", ""))[:500], profile),
            "risk_flags": [str(item) for item in payload.get("risk_flags", [])][:10],
            "captions": {
                "neutral": neutral,
                "public_clean": public_clean,
                "more_engaging": more_engaging,
            },
            "hashtags": [tag if str(tag).startswith("#") else f"#{tag}" for tag in hashtags],
        }

    def _strip_code_fences(self, raw_content: str) -> str:
        content = raw_content.strip()
        if content.startswith("```"):
            lines = content.splitlines()
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        return content

    def _fallback(self, job: Job, profile: CaptionProfile) -> dict[str, Any]:
        base = (job.source_caption or job.source_title or job.transcript_en or "Video update").strip()
        trimmed = " ".join(base.split())[:220]
        safe = self._sanitize_caption_text(trimmed or "Video update")
        translated = self._localize_fallback(safe, profile)
        hashtags = self._hashtags_for_profile(profile)
        return {
            "summary": translated[:500],
            "risk_flags": [],
            "captions": {
                "neutral": self._ensure_caption(translated, profile),
                "public_clean": self._ensure_caption(translated, profile),
                "more_engaging": self._ensure_caption(translated, profile),
            },
            "hashtags": hashtags,
        }

    def _ensure_caption(self, text: str, profile: CaptionProfile) -> str:
        value = self._strip_hashtags(str(text))
        value = " ".join(value.split()).strip()
        if not value:
            value = self._localize_fallback("Video update", profile)
        return value[:260]

    def _hashtags_for_profile(self, profile: CaptionProfile) -> list[str]:
        defaults = {
            "en": ["#video"],
            "ja": ["#動画"],
            "ko": ["#영상"],
            "ar": ["#فيديو"],
            "es": ["#video"],
            "la": ["#video"],
        }
        return defaults.get(profile.language, ["#video", "#update", "#trending"])

    def _localize_fallback(self, text: str, profile: CaptionProfile) -> str:
        return self._translate_for_profile(text, profile)

    def _sanitize_caption_text(self, text: str) -> str:
        value = self._strip_hashtags(text)
        value = " ".join(value.split()).strip()
        replacements = {
            "fuck": "f*ck",
            "shit": "s**t",
            "bitch": "b****",
            "asshole": "a**hole",
            "kill yourself": "harm yourself",
            "dm me at": "contact me at",
            "call me at": "contact me at",
            "my phone number is": "contact info removed",
            "my address is": "address removed",
        }
        lowered = value.lower()
        for source, target in replacements.items():
            if source in lowered:
                value = value.replace(source, target)
                value = value.replace(source.title(), target)
                value = value.replace(source.upper(), target.upper())
        return value[:260]

    def _strip_hashtags(self, text: str) -> str:
        value = re.sub(r"(?<!\w)#[^\s#]+", " ", text)
        return re.sub(r"\s+", " ", value).strip(" ,.-")

    def _translate_for_profile(self, text: str, profile: CaptionProfile) -> str:
        value = " ".join(str(text).split()).strip()
        if not value or profile.language == "en":
            return value
        return self.translator.translate_text(value, profile.language)[:260]
