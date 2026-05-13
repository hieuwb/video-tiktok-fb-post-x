from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from app.core.config import get_settings
from app.db.models import Job
from app.services.profile_selector import CaptionProfile
from app.services.translator import TranslatorService


logger = logging.getLogger(__name__)


SILENT_PROMPT_TEMPLATE = """You are writing English social-media captions for a SILENT short video (no dialogue, no voice-over) reuploaded from {platform}.

CHANNEL: global English-speaking audience across all countries. Niches: ANIME (edits / AMV / aesthetic) and LIFE HACKS (kitchen / DIY / clever tricks).

YOUR STYLE: dramatic, provocative, hot-take. The caption must READ LIKE AN OPINIONATED JUDGMENT, not a neutral description. Turn any mundane visual into a universal-life-truth or harsh judgment that sparks debate in the comments. This drives engagement and viral shares.

Formula for x_caption (follow loosely, 2-3 sentences):
  1. Assert the skill/habit/aesthetic shown is ESSENTIAL / says something deep about the viewer.
  2. Explain the stakes — it shapes your future, reveals character, separates winners.
  3. Drop a HARSH verdict on people who lack it (failures, poor taste, doomed, behind).

Example (anime edit):
If this scene doesn't move you, you've already lost the part of yourself that dreams. The ones who feel it deep are the same people who go on to build something real.

Example (life hack):
If you are still doing this the old way in 2026, you are choosing to struggle. Small tricks like this separate the smart from the stuck.

Example (oddly satisfying):
The people who pause to watch this all the way through are the same ones who finish what they start. Everyone else wonders why life feels so chaotic.

Constraints:
- English ONLY (audience is global — English is the lingua franca of short-form).
- NO emojis, or at most 1 subtle one.
- NO hashtags inline (hashtags go in the x_hashtags field).
- Keep it 120-240 chars total.
- Do NOT invent specific facts (names, places, anime titles) not in the input.
- Do NOT mention the source platform.
- If source is anime: focus on the FEELING / aesthetic, not specific characters or plot.
- If source is life hack: focus on the JUDGMENT of those who don't know it.
- HASHTAGS: chỉ đề xuất 1 hashtag bổ sung. Topic hashtag (#anime hoặc #lifehack)
  sẽ được hệ thống tự thêm. Đừng đề xuất #anime / #lifehack — sẽ bị duplicate.

Source title: {source_title}
Source tags: {source_tags}
Mood: {mood}

Output valid JSON only:
{{
  "x_caption": "2-3 dramatic sentences, opinionated, ends with a harsh judgment",
  "x_hashtags": ["#OneSupplementaryTag"],
  "youtube_title": "<=90 chars, clickbait hook style, NO #Shorts (we add it)",
  "youtube_description": "2-4 sentences, dramatic hook + CTA. <=500 chars",
  "youtube_tags": ["tag1", "tag2", "...up to 12 lowercase tags"]
}}

Rules:
- x_hashtags: ĐÚNG 1 hashtag (lowercase hoặc CamelCase, no spaces). Đừng dùng #anime/#lifehack.
- youtube_tags: 8-12 tags để boost SEO discovery (separate from x_hashtags).
"""


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
        # Cap 2 hashtag/post (đồng nhất với silent path, nhẹ feed).
        hashtags = payload.get("hashtags", [])[:2]
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

    # ─────────── Silent / Auto-crawl pipeline ───────────

    def _topic_hashtag(
        self,
        source_title: str,
        source_tags: list[str] | None,
        mood: str | None,
    ) -> str:
        """Quyết định topic hashtag bắt buộc từ title/tags/mood.

        Kênh global scope = anime + life hack. Mọi video PHẢI có 1 trong 2.
        Decision tree (high → low priority):
          1. Title/tags chứa từ khoá anime → #anime
          2. Title/tags chứa từ khoá life hack → #lifehack
          3. Mood = cinematic → #anime (anime classify ra cinematic theo mood_for_tags)
          4. Mặc định → #lifehack
        """
        blob = (source_title + " " + " ".join(source_tags or [])).lower()
        anime_kws = (
            "anime", "amv", "manga", "ghibli", "shonen", "shoujo",
            "anime edit", "aesthetic anime",
        )
        lifehack_kws = (
            "life hack", "lifehack", "kitchen hack", "hack", "diy",
            "trick", "clever", "satisfying", "oddly satisfying",
            "organize", "kitchen tip",
        )
        if any(kw in blob for kw in anime_kws):
            return "#anime"
        if any(kw in blob for kw in lifehack_kws):
            return "#lifehack"
        if (mood or "").lower() == "cinematic":
            return "#anime"
        return "#lifehack"

    def generate_silent_package(
        self,
        source_title: str,
        source_tags: list[str] | None = None,
        platform: str = "tiktok",
        mood: str = "chill",
        music_credit: str = "",
    ) -> dict[str, Any]:
        """Sinh caption cho video không lời (animation/pet) → EN cho X + YouTube.

        Trả về:
        {
          "x_caption": str (≤240 ký tự, đã kèm hashtag inline),
          "x_hashtags": list[str],
          "youtube_title": str (≤100 ký tự, sẽ được thêm #Shorts ở service),
          "youtube_description": str,
          "youtube_tags": list[str],
        }
        """
        source_tags = source_tags or []
        topic_tag = self._topic_hashtag(source_title, source_tags, mood)

        if not self.settings.deepseek_api_key:
            return self._silent_fallback(source_title, source_tags, platform, mood, music_credit, topic_tag)

        prompt = SILENT_PROMPT_TEMPLATE.format(
            source_title=source_title or "",
            source_tags=", ".join(source_tags)[:300],
            platform=platform,
            mood=mood,
        )
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": "Return valid JSON only. English only. Be provocative and dramatic to maximize engagement."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.85,
            "response_format": {"type": "json_object"},
        }
        try:
            response = requests.post(
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(self._strip_code_fences(raw))
            return self._sanitize_silent(parsed, mood, music_credit, topic_tag)
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as exc:
            logger.warning("Silent caption LLM failed (%s), fallback", exc)
            return self._silent_fallback(source_title, source_tags, platform, mood, music_credit, topic_tag)

    def _sanitize_silent(
        self,
        payload: dict[str, Any],
        mood: str,
        music_credit: str,
        topic_tag: str,
    ) -> dict[str, Any]:
        # Tags raw từ LLM, bỏ rỗng + bỏ trùng topic_tag (nếu LLM lỡ đề xuất).
        raw_tags = [self._norm_hashtag(h) for h in payload.get("x_hashtags", []) if h]
        topic_lower = topic_tag.lower()
        raw_tags = [t for t in raw_tags if t and t.lower() != topic_lower]
        # 2 hashtags total: topic_tag (forced) + 1 từ LLM (hoặc fallback)
        if raw_tags:
            hashtags_x = [topic_tag, raw_tags[0]]
        else:
            hashtags_x = [topic_tag, "#shorts" if topic_tag == "#anime" else "#viral"]

        yt_tags = [self._norm_tag(t) for t in payload.get("youtube_tags", [])][:12]
        x_caption = self._cap_text(payload.get("x_caption", ""), 260)
        yt_title = self._cap_text(payload.get("youtube_title", ""), 95)
        yt_description = self._cap_text(payload.get("youtube_description", ""), 2500)

        if music_credit:
            credit_line = f"\n🎵 Music: {music_credit}"
            if len(yt_description) + len(credit_line) <= 2000:
                yt_description = yt_description + credit_line

        if not x_caption:
            x_caption = "Pure visual vibes ✨"
        if not yt_title:
            yt_title = "Relaxing silent moment"

        return {
            "x_caption": x_caption,
            "x_hashtags": hashtags_x,
            "youtube_title": yt_title,
            "youtube_description": yt_description,
            "youtube_tags": yt_tags,
        }

    def _silent_fallback(
        self,
        source_title: str,
        source_tags: list[str],
        platform: str,
        mood: str,
        music_credit: str,
        topic_tag: str,
    ) -> dict[str, Any]:
        # Fallback dramatic hot-take khi không có LLM. Không bịa chi tiết, chỉ
        # judgement chung chung để tạo engagement.
        # Hashtags: 2 cái = topic + 1 generic phù hợp.
        supplementary = "#shorts" if topic_tag == "#anime" else "#viral"
        hashtags = [topic_tag, supplementary]
        # YouTube tags vẫn nhiều để hỗ trợ SEO discovery.
        if topic_tag == "#anime":
            yt_tags = ["shorts", "anime", "anime edit", "amv", "aesthetic", "anime shorts", mood]
            caption = (
                "Those who pause to feel a scene like this are the same ones who "
                "build something real with their lives. Everyone else just scrolls "
                "past their own dreams."
            )
            yt_title = "Only People With Taste Notice This"
        else:
            yt_tags = ["shorts", "life hack", "lifehack", "kitchen hack", "diy", "satisfying", "trick", mood]
            caption = (
                "If you are still doing this the old way in 2026, you are choosing "
                "to struggle. Small tricks like this separate the smart from the stuck."
            )
            yt_title = "The Hack That Separates The Smart From The Stuck"
        desc = f"{caption}\n\nDrop a comment if you agree. Save this one."
        if music_credit:
            desc += f"\n🎵 Music: {music_credit}"
        return {
            "x_caption": caption[:240],
            "x_hashtags": hashtags,
            "youtube_title": yt_title[:90],
            "youtube_description": desc,
            "youtube_tags": yt_tags,
        }

    def _cap_text(self, value: Any, limit: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        return text[:limit]

    def _norm_hashtag(self, value: Any) -> str:
        tag = str(value or "").strip().lstrip("#")
        tag = re.sub(r"[^0-9A-Za-z_]+", "", tag)
        return f"#{tag}" if tag else ""

    def _norm_tag(self, value: Any) -> str:
        tag = str(value or "").strip().lstrip("#").lower()
        tag = re.sub(r"\s+", " ", tag)
        return tag[:30]
