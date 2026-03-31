from app.core.config import get_settings


class TranslatorService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def translate_to_english(self, text: str) -> str:
        if not self.settings.enable_auto_translate_to_en or not text.strip():
            return text
        try:
            from deep_translator import GoogleTranslator

            return GoogleTranslator(source="auto", target="en").translate(text)
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
