import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.profile_selector import ProfileSelectorService


class ProfileSelectorTests(unittest.TestCase):
    def test_hourly_profile_selection(self) -> None:
        service = ProfileSelectorService()
        profile = service.get_active_profile(datetime(2026, 3, 31, 8, 0, tzinfo=ZoneInfo("UTC")))
        self.assertEqual(profile.code, "A4")
        self.assertEqual(profile.language, "ko")

    def test_explicit_profile_lookup(self) -> None:
        service = ProfileSelectorService()
        profile = service.get_profile("A5")
        self.assertEqual(profile.language, "ar")
        self.assertEqual(profile.style, "public_clean")


if __name__ == "__main__":
    unittest.main()
