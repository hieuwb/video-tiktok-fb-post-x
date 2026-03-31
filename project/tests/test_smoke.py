import unittest

from app.api.routes_jobs import JobCreateRequest, create_job
from app.bot.commands import parse_add_arguments
from app.core.security import detect_platform_from_url, validate_source_url
from app.db import crud
from app.db.models import Job
from app.db.session import SessionLocal, init_db
from app.services.caption_rewriter import CaptionRewriterService
from app.services.profile_selector import ProfileSelectorService
from app.services.subtitle_generator import SubtitleGeneratorService


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        self.db = SessionLocal()
        self.db.query(Job).delete()
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_url_validation(self) -> None:
        self.assertTrue(validate_source_url("https://www.tiktok.com/@demo/video/123"))
        self.assertTrue(validate_source_url("https://www.facebook.com/watch/?v=123"))
        self.assertFalse(validate_source_url("https://evil.example/video"))

    def test_add_argument_parsing(self) -> None:
        self.assertEqual(
            parse_add_arguments(["https://www.tiktok.com/@demo/video/123", "a4"]),
            ("https://www.tiktok.com/@demo/video/123", "A4"),
        )
        self.assertEqual(
            parse_add_arguments(["https://www.tiktok.com/@demo/video/123"]),
            ("https://www.tiktok.com/@demo/video/123", None),
        )
        self.assertIsNone(parse_add_arguments([]))

    def test_job_create_route(self) -> None:
        response = create_job(
            JobCreateRequest(source_url="https://www.tiktok.com/@demo/video/123"),
            self.db,
        )
        self.assertEqual(response.source_platform, "tiktok")
        self.assertEqual(response.status, "queued")

    def test_caption_fallback_and_subtitle_generation(self) -> None:
        job = crud.create_job(
            self.db,
            source_url="https://www.tiktok.com/@demo/video/123",
            source_platform=detect_platform_from_url("https://www.tiktok.com/@demo/video/123"),
            status="queued",
        )
        job = crud.update_job(
            self.db,
            job,
            transcript_original="xin chao",
            transcript_en="hello world",
            source_title="Sample title",
            source_caption="Sample caption",
        )
        profile = ProfileSelectorService().get_profile("A1")
        package = CaptionRewriterService().generate_caption_package(job, profile)
        self.assertIn("public_clean", package["captions"])
        self.assertTrue(package["captions"]["public_clean"])
        self.assertEqual(package["captions"]["public_clean"], "Sample caption")

        srt_path = SubtitleGeneratorService().generate_srt(
            job.id,
            {
                "text_en": "hello world",
                "segments": [{"start": 0.0, "end": 1.5, "text": "hello world"}],
            },
        )
        from pathlib import Path

        self.assertTrue(Path(srt_path).exists())

    def test_caption_sanitizes_only_sensitive_words(self) -> None:
        job = crud.create_job(
            self.db,
            source_url="https://www.tiktok.com/@demo/video/123",
            source_platform="tiktok",
            status="queued",
        )
        job = crud.update_job(
            self.db,
            job,
            source_caption="This is shit but my phone number is 123",
        )
        profile = ProfileSelectorService().get_profile("A1")
        package = CaptionRewriterService().generate_caption_package(job, profile)
        self.assertIn("s**t", package["captions"]["public_clean"])
        self.assertIn("contact info removed", package["captions"]["public_clean"])


if __name__ == "__main__":
    unittest.main()
