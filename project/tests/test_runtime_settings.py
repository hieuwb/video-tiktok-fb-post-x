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

    def test_set_post_mode_updates_approval_flag(self) -> None:
        service = RuntimeSettingsService()
        original_auto = service.get_auto_post_enabled()
        original_approval = service.get_require_approval_before_post()

        service.set_post_mode(True)
        self.assertTrue(service.get_auto_post_enabled())
        self.assertFalse(service.get_require_approval_before_post())

        service.set_post_mode(False)
        self.assertFalse(service.get_auto_post_enabled())
        self.assertTrue(service.get_require_approval_before_post())

        service.set_auto_post_enabled(original_auto)
        service.set_require_approval_before_post(original_approval)


if __name__ == "__main__":
    unittest.main()
