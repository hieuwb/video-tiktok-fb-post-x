from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.utils import ensure_utc_datetime
from app.db import crud


logger = logging.getLogger(__name__)


VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class PublishScheduler:
    """Cấp phát slot publish theo lịch cố định (3 slot/ngày, khung 13h-02h VN).

    Logic:
      - Đọc danh sách POST_SLOTS_VN (vd: ["14:00", "19:00", "01:00"]).
      - Quét tất cả Job có scheduled_publish_at trong tương lai → đánh dấu slot đã chiếm.
      - Slot 01:00 thuộc "ngày hôm sau" so với cụm 14:00/19:00 cùng ngày → để
        đơn giản, cứ duyệt từng ngày dương lịch → enumerate slots theo thứ tự
        khai báo. Người dùng có thể đặt thứ tự bất kỳ trong .env.
      - Trả về slot trống đầu tiên ≥ now (UTC).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.slots = self._parse_slots(self.settings.post_slots_vn)
        if not self.slots:
            raise ValueError("POST_SLOTS_VN trống. Cần ít nhất 1 slot HH:MM.")

    @staticmethod
    def _parse_slots(values: list[str]) -> list[time]:
        out: list[time] = []
        for raw in values:
            raw = str(raw).strip()
            if not raw:
                continue
            hh, mm = raw.split(":")
            out.append(time(int(hh), int(mm)))
        return out

    def next_slot_utc(self, db: Session, *, after: datetime | None = None) -> datetime:
        """Tìm slot trống đầu tiên ≥ `after` (UTC, mặc định = now).

        Sinh tất cả candidate trong 14 ngày tới rồi sort chronologically — quan
        trọng vì slot 01:00 thuộc 'ngày hôm sau' so với cụm 14:00/19:00, sort
        theo timestamp đảm bảo chronological order khớp window 13:00-02:00.
        """
        after_utc = (after or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
        used = self._used_slot_set(db, after_utc)

        cursor_date = after_utc.astimezone(VN_TZ).date()
        candidates: list[datetime] = []
        for day_offset in range(14):
            current_date: date = cursor_date + timedelta(days=day_offset)
            for slot_time in self.slots:
                slot_vn = datetime.combine(current_date, slot_time, tzinfo=VN_TZ)
                candidates.append(slot_vn.astimezone(timezone.utc).replace(second=0, microsecond=0))

        for slot_utc in sorted(candidates):
            if slot_utc < after_utc + timedelta(minutes=1):
                continue
            if slot_utc in used:
                continue
            return slot_utc
        raise RuntimeError("Không còn slot trống trong 14 ngày tới (queue quá đầy?).")

    def _used_slot_set(self, db: Session, from_utc: datetime) -> set[datetime]:
        """Tập slot đã chiếm bởi job đang chờ publish/awaiting_review/publishing."""
        used: set[datetime] = set()
        for job in crud.list_scheduled_after(db, from_utc - timedelta(minutes=2)):
            dt = ensure_utc_datetime(job.scheduled_publish_at)
            if dt:
                used.add(dt.replace(second=0, microsecond=0))
        return used
