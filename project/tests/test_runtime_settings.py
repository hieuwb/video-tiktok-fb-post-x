import unittest

from app.services.runtime_settings import RuntimeSettingsService


class RuntimeSettingsTests(unittest.TestCase):
    def test_toggle_autopost_runtime(self) -> None:
        service = RuntimeSettingsService()
        original = service.get_auto_post_enabled()
        service.set_auto_post_enabled(not original)
        self.assertEqual(service.get_auto_post_enabled(), (not original))
        service.set_auto_post_enabled(original)
        self.assertEqual(service.get_auto_post_enabled(), original)


if __name__ == "__main__":
    unittest.main()
