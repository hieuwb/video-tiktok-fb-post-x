import unittest

from app.db import crud
from app.db.models import Job
from app.db.session import SessionLocal, init_db
from app.services.profile_selector import ProfileSelectorService


class ProfileOverrideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def setUp(self) -> None:
        self.db = SessionLocal()
        self.db.query(Job).delete()
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_set_job_profile(self) -> None:
        job = crud.create_job(
            self.db,
            source_url="https://www.tiktok.com/@demo/video/123",
            source_platform="tiktok",
            status="queued",
        )
        profile = ProfileSelectorService().get_profile("A4")
        updated = crud.set_job_profile(self.db, job, profile.code, profile.language)
        self.assertEqual(updated.selected_profile, "A4")
        self.assertEqual(updated.target_language, "zh")


if __name__ == "__main__":
    unittest.main()
