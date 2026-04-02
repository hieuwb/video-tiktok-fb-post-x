from app.core.config import get_settings


class TranslatorService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def translate_to_english(self, text: str) -> str:
        return self.translate_text(text, "en")

    def translate_text(self, text: str, target_language: str) -> str:
        if not text.strip():
            return text
        try:
            from deep_translator import GoogleTranslator

            return GoogleTranslator(source="auto", target=self._normalize_target_language(target_language)).translate(text)
        except Exception:
            return text

    def translate_segments(self, segments: list[dict]) -> list[dict]:
        translated: list[dict] = []
        for segment in segments:
            translated.append(
                {
                    **segment,
                    "text": self.translate_to_english(segment.get("text", "")),
                }
            )
        return translated

    def _normalize_target_language(self, language: str) -> str:
        mapping = {
            "zh": "zh-CN",
        }
        return mapping.get(language, language)
