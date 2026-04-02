import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.api.routes_jobs import JobCreateRequest, create_job
from app.bot.commands import parse_add_arguments
from app.core.security import detect_platform_from_url, validate_source_url
from app.db import crud
from app.db.models import Job
from app.db.session import SessionLocal, init_db
from app.services.caption_rewriter import CaptionRewriterService
from app.services.downloader import DownloaderService
from app.services.profile_selector import ProfileSelectorService


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
            ("https://www.tiktok.com/@demo/video/123", "A4", None),
        )
        self.assertEqual(
            parse_add_arguments(["https://www.tiktok.com/@demo/video/123"]),
            ("https://www.tiktok.com/@demo/video/123", None, None),
        )
        self.assertIsNone(parse_add_arguments([]))

        parsed = parse_add_arguments(
            ["https://www.tiktok.com/@demo/video/123", "A2", "2026-04-02", "19:30"]
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], "https://www.tiktok.com/@demo/video/123")
        self.assertEqual(parsed[1], "A2")
        self.assertIsNotNone(parsed[2])

    def test_job_create_route(self) -> None:
        response = create_job(
            JobCreateRequest(source_url="https://www.tiktok.com/@demo/video/123"),
            self.db,
        )
        self.assertEqual(response.source_platform, "tiktok")
        self.assertEqual(response.status, "queued")

    def test_caption_fallback_generation(self) -> None:
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

    def test_caption_fallback_removes_old_hashtags(self) -> None:
        job = crud.create_job(
            self.db,
            source_url="https://www.tiktok.com/@demo/video/123",
            source_platform="tiktok",
            status="queued",
        )
        job = crud.update_job(
            self.db,
            job,
            source_caption="Awesome badminton skills. #thegioicaulong #caulongvietnam #xuhuong",
        )
        profile = ProfileSelectorService().get_profile("A1")
        package = CaptionRewriterService().generate_caption_package(job, profile)
        self.assertEqual(package["captions"]["public_clean"], "Awesome badminton skills")

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

    def test_sanitize_removes_hashtags_from_ai_caption_output(self) -> None:
        profile = ProfileSelectorService().get_profile("A1")
        service = CaptionRewriterService()
        package = service._sanitize(
            {
                "summary": "demo",
                "risk_flags": [],
                "captions": {
                    "neutral": "Nice clip #tag1",
                    "public_clean": "Great rally #badminton #sports",
                    "more_engaging": "#viral Amazing play",
                },
                "hashtags": ["#badminton", "#sports"],
            },
            profile,
        )
        self.assertEqual(package["captions"]["neutral"], "Nice clip")
        self.assertEqual(package["captions"]["public_clean"], "Great rally")
        self.assertEqual(package["captions"]["more_engaging"], "Amazing play")

    @patch("app.services.translator.TranslatorService.translate_text")
    def test_non_english_profile_localizes_caption_output(self, mock_translate: Mock) -> None:
        mock_translate.side_effect = lambda text, target: f"[{target}] {text}"
        profile = ProfileSelectorService().get_profile("A2")
        service = CaptionRewriterService()
        package = service._sanitize(
            {
                "summary": "hello",
                "risk_flags": [],
                "captions": {
                    "neutral": "Nice clip",
                    "public_clean": "Great rally",
                    "more_engaging": "Amazing play",
                },
                "hashtags": ["#video"],
            },
            profile,
        )
        self.assertEqual(package["captions"]["public_clean"], "[ja] Great rally")
        self.assertEqual(package["summary"], "[ja] hello")

    def test_downloader_selects_matching_entry_by_source_url(self) -> None:
        service = DownloaderService()
        info = {
            "entries": [
                {"webpage_url": "https://www.tiktok.com/@other/video/999", "title": "Wrong"},
                {"webpage_url": "https://www.tiktok.com/@demo/video/123?foo=1", "title": "Correct"},
            ]
        }
        selected = service._select_primary_info(
            info,
            "https://www.tiktok.com/@demo/video/123?foo=1&utm_source=telegram",
        )
        self.assertEqual(selected["title"], "Correct")

    def test_downloader_resolves_downloaded_filepath(self) -> None:
        service = DownloaderService()
        resolved = service._resolve_downloaded_file_path(
            {"requested_downloads": [{"filepath": "/tmp/final.mp4"}]},
            None,  # type: ignore[arg-type]
        )
        self.assertEqual(resolved, "/tmp/final.mp4")

    def test_downloader_builds_instagram_headers_with_cookie(self) -> None:
        service = DownloaderService()
        service.settings.instagram_cookie_header = "csrftoken=demo; sessionid=demo"
        headers = service._build_request_headers("instagram")
        self.assertEqual(headers["Referer"], "https://www.instagram.com/")
        self.assertIn("Cookie", headers)

    def test_downloader_builds_facebook_headers_with_cookie(self) -> None:
        service = DownloaderService()
        service.settings.facebook_cookie_header = "c_user=1; xs=demo"
        headers = service._build_request_headers("facebook")
        self.assertEqual(headers["Referer"], "https://www.facebook.com/")
        self.assertIn("Cookie", headers)

    def test_downloader_builds_cookie_file_from_header(self) -> None:
        service = DownloaderService()
        service.settings.instagram_cookie_header = "csrftoken=demo; sessionid=abc123"
        cookie_file = service._build_cookie_file_from_header(
            "instagram",
            "https://www.instagram.com/reel/demo/",
        )
        self.assertIsNotNone(cookie_file)
        self.assertTrue(Path(cookie_file).exists())
        content = Path(cookie_file).read_text(encoding="utf-8")
        self.assertIn("csrftoken", content)
        self.assertIn("sessionid", content)
        Path(cookie_file).unlink(missing_ok=True)

    @patch("app.services.downloader.requests.get")
    def test_downloader_resolves_short_source_url(self, mock_get: Mock) -> None:
        mock_response = Mock()
        mock_response.url = "https://www.tiktok.com/@demo/video/1234567890"
        mock_get.return_value = mock_response

        service = DownloaderService()
        resolved = service._resolve_source_url("https://vt.tiktok.com/ZSHFWVCCe/")
        self.assertEqual(resolved, "https://www.tiktok.com/@demo/video/1234567890")


if __name__ == "__main__":
    unittest.main()
