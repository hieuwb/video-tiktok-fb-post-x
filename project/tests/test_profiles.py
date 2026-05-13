import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.profile_selector import ProfileSelectorService


class ProfileSelectorTests(unittest.TestCase):
    def test_hourly_profile_selection(self) -> None:
        # Map mặc định = all A1 (English) cho kênh global single-channel.
        # Test sample 1 giờ bất kỳ → phải trả profile từ map[hour].
        service = ProfileSelectorService()
        profile = service.get_active_profile(datetime(2026, 3, 31, 8, 0, tzinfo=ZoneInfo("UTC")))
        expected_code = service.settings.profile_hourly_map[8]
        self.assertEqual(profile.code, expected_code)
        self.assertEqual(
            profile.language,
            service.settings.caption_profiles_json[expected_code]["language"],
        )

    def test_explicit_profile_lookup(self) -> None:
        service = ProfileSelectorService()
        profile = service.get_profile("A4")
        self.assertEqual(profile.language, "zh")
        self.assertEqual(profile.style, "public_clean")


if __name__ == "__main__":
    unittest.main()
