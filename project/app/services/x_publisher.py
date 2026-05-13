from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import redis
import requests

from app.core.config import get_settings
from app.db.models import Job
from app.services.runtime_settings import RuntimeSettingsService


logger = logging.getLogger(__name__)


class XPublisherError(RuntimeError):
    pass


@contextmanager
def _gpm_profile_lock(profile_id: str, redis_url: str, ttl: int, wait: int):
    """Redis lock để 1 publish job độc quyền GPM profile cùng lúc.

    Tránh race khi 2 slot post trùng giờ hoặc admin /approve nhiều job liền nhau:
    chỉ 1 task chiếm browser, các task khác đợi (block-wait) tối đa `wait` giây.
    """
    client = redis.from_url(redis_url)
    lock = client.lock(
        f"gpm:profile:{profile_id}",
        timeout=ttl,
        blocking_timeout=wait,
        thread_local=False,
    )
    acquired = lock.acquire(blocking=True)
    if not acquired:
        raise XPublisherError(
            f"Không lấy được lock GPM profile {profile_id} sau {wait}s — có job khác đang chạy."
        )
    try:
        yield
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            # Lock đã expire (TTL) — không sao, log và tiếp tục.
            logger.warning("GPM lock TTL expired before release — increase GPM_LOCK_TTL_SEC.")


class XPublisherService:
    """Post lên X qua GPM Login (browser automation) — không dùng X API.

    Flow:
      1. GET {gpm_api_base}/api/v3/profiles/start/{profile_id}
         → trả Chrome remote-debug endpoint (ws://host:port hoặc host:port)
      2. Playwright.connect_over_cdp → attach vào browser GPM (đã đăng nhập X sẵn)
      3. Drive UI x.com/compose/post: set_input_files(video) → type(caption) →
         click Post → đợi tweet URL xuất hiện trong toast hoặc timeline
      4. GET /api/v3/profiles/close/{profile_id}

    Yêu cầu:
      - GPM Login app đang chạy + profile đã đăng nhập sẵn account X
      - playwright (>=1.40) — connect_over_cdp KHÔNG cần download browser binary
      - Nếu chạy worker trong Docker, GPM_API_BASE phải là host.docker.internal
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def publish(self, job: Job) -> dict[str, str]:
        require_approval = RuntimeSettingsService().get_require_approval_before_post()
        if require_approval and job.status != "publishing":
            raise ValueError("Job is not approved for publishing.")
        if not self.settings.gpm_profile_id:
            raise XPublisherError("GPM_PROFILE_ID chưa cấu hình trong .env")

        media_source = job.output_video_path or job.raw_video_path
        if not media_source or not Path(media_source).exists():
            raise FileNotFoundError("Video file not found for publishing.")

        text = (job.selected_caption or job.ai_caption_primary or "").strip()
        if job.hashtags:
            text = f"{text}\n\n{job.hashtags}".strip()
        text = text[:280]

        with _gpm_profile_lock(
            self.settings.gpm_profile_id,
            self.settings.redis_url,
            self.settings.gpm_lock_ttl_sec,
            self.settings.gpm_lock_wait_sec,
        ):
            cdp_endpoint = self._start_profile()
            try:
                return self._drive_post(cdp_endpoint, media_source, text)
            finally:
                self._close_profile()

    # ─────────── GPM Login API ───────────

    def _start_profile(self) -> str:
        s = self.settings
        url = f"{s.gpm_api_base.rstrip('/')}/api/v3/profiles/start/{s.gpm_profile_id}"
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise XPublisherError(f"GPM Login start API failed ({url}): {exc}") from exc

        if not payload.get("success", True) and payload.get("status") not in (200, "success"):
            raise XPublisherError(f"GPM Login start failed: {payload.get('message') or payload}")

        data = payload.get("data") or payload
        endpoint = (
            data.get("remote_debugging_address")
            or data.get("websocket_debugger_url")
            or data.get("debug_port")
            or data.get("port")
        )
        if not endpoint:
            raise XPublisherError(f"GPM Login response missing debug endpoint: {payload}")

        endpoint = str(endpoint).strip()
        if endpoint.startswith(("ws://", "http://", "https://")):
            return endpoint
        if ":" not in endpoint:
            endpoint = f"127.0.0.1:{endpoint}"
        return f"http://{endpoint}"

    def _close_profile(self) -> None:
        if not self.settings.gpm_close_after_post:
            return
        s = self.settings
        url = f"{s.gpm_api_base.rstrip('/')}/api/v3/profiles/close/{s.gpm_profile_id}"
        try:
            requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.warning("GPM Login close API failed: %s", exc)

    # ─────────── Browser automation ───────────

    def _drive_post(self, cdp_endpoint: str, video_path: str, text: str) -> dict[str, str]:
        try:
            from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright
        except ImportError as exc:
            raise XPublisherError(
                "Thiếu playwright. Chạy: pip install playwright (không cần playwright install — dùng connect_over_cdp)"
            ) from exc

        timeout_ms = self.settings.gpm_post_timeout_sec * 1000

        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(cdp_endpoint)
            except Exception as exc:
                raise XPublisherError(f"Playwright cannot connect to {cdp_endpoint}: {exc}") from exc

            try:
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()

                # /compose/post tạo modal trên home — chuẩn flow của X. Fallback
                # sang home + click sidebar nếu route lỗi.
                try:
                    page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=timeout_ms)
                    page.locator('[data-testid="SideNav_NewTweet_Button"]').first.click(timeout=30000)
                    page.wait_for_selector('[role="dialog"] [data-testid^="tweetTextarea_"]', timeout=30000)
                except PWTimeout:
                    page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_selector('[data-testid^="tweetTextarea_"]', timeout=30000)

                # Modal compose có 2 hidden file input (sidebar + dialog). Pick cái
                # trong dialog để khỏi attach nhầm vào sidebar compose ẩn.
                file_input = page.locator('[role="dialog"] input[data-testid="fileInput"]').first
                if file_input.count() == 0:
                    file_input = page.locator('input[data-testid="fileInput"]').last
                file_input.wait_for(state="attached", timeout=15000)
                file_input.set_input_files(video_path)

                editor = page.locator('[role="dialog"] [data-testid^="tweetTextarea_"] [role="textbox"]').first
                if editor.count() == 0:
                    editor = page.locator('[role="dialog"] [data-testid^="tweetTextarea_"] [contenteditable="true"]').first
                if editor.count() == 0:
                    editor = page.locator('[role="dialog"] [data-testid^="tweetTextarea_"]').first
                if editor.count() == 0:
                    editor = page.locator('[data-testid^="tweetTextarea_"] [role="textbox"]').first
                if editor.count() == 0:
                    editor = page.locator('[data-testid^="tweetTextarea_"]').first
                editor.click(timeout=30000)
                page.keyboard.type(text, delay=15)

                # CRITICAL: đợi video upload tới 100% trước khi click Post.
                # Tín hiệu chuẩn = tweetButton chuyển từ aria-disabled="true" sang
                # null. Đo thực tế: video 7MB upload xong sau ~15-20s. KHÔNG dùng
                # [role="progressbar"] — selector đó match elements khác trên page,
                # không phải upload indicator (always count=2).
                post_btn = page.locator('[role="dialog"] [data-testid="tweetButton"]').first
                if post_btn.count() == 0:
                    post_btn = page.locator('[data-testid="tweetButtonInline"], [data-testid="tweetButton"]').first

                logger.info("Waiting for media upload to complete (Post button to enable)...")
                upload_deadline = self.settings.gpm_post_timeout_sec
                upload_waited = 0
                while upload_waited < upload_deadline:
                    try:
                        # is_enabled() check cả `disabled` attr và aria-disabled.
                        # 'true' aria-disabled → False; null → True.
                        if post_btn.is_enabled():
                            logger.info("Media upload complete after %ss", upload_waited)
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)
                    upload_waited += 1
                else:
                    raise XPublisherError(
                        f"Post button stayed disabled for {upload_deadline}s — upload likely failed."
                    )

                # Click chain: normal → JS evaluate (bypass overlay) → Ctrl+Enter.
                # Overlay div đôi khi vẫn còn vài ms sau khi button enable, intercept
                # pointer events. force=True của Playwright VẪN gửi sự kiện qua DOM
                # nên overlay vẫn nuốt event (silent fail). page.evaluate("btn.click()")
                # gọi React onClick handler trực tiếp, bypass DOM event chain.
                clicked_via = None
                try:
                    post_btn.click(timeout=5000)
                    clicked_via = "playwright-click"
                except PWTimeout:
                    logger.warning("Post click intercepted, trying JS evaluate")

                if not clicked_via:
                    try:
                        ok = page.evaluate(
                            "() => { const b = document.querySelector('[role=\"dialog\"] [data-testid=\"tweetButton\"]'); if (b) { b.click(); return true; } return false; }"
                        )
                        if ok:
                            clicked_via = "js-evaluate"
                    except Exception as exc:
                        logger.warning("JS click failed: %s", exc)

                if not clicked_via:
                    logger.warning("Both clicks failed, falling back to Ctrl+Enter")
                    editor.click()
                    page.keyboard.press("Control+Enter")
                    clicked_via = "ctrl-enter"

                logger.info("Post submitted via %s", clicked_via)

                # CRITICAL: verify modal đã đóng = post submitted thật sự.
                # Modal STAY OPEN nếu click bị overlay nuốt → post fail silently.
                try:
                    page.wait_for_selector('[role="dialog"]', state="detached", timeout=15000)
                    logger.info("Modal closed — post confirmed submitted")
                except PWTimeout:
                    raise XPublisherError(
                        "Modal did not close after click — tweet was NOT submitted (overlay swallowed click)."
                    )

                tweet_url = self._capture_tweet_url(page)
                if not tweet_url:
                    raise XPublisherError("Posted but could not capture tweet URL.")

                post_id = tweet_url.rstrip("/").split("/")[-1]
                return {"post_id": post_id, "post_url": tweet_url}
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def _capture_tweet_url(self, page) -> str | None:
        """Capture URL của tweet vừa post.

        Strategy (high → low confidence):
          1. Toast "Your post was sent" có link "View" → URL chính xác (canonical).
          2. Navigate đến profile của user → tìm article KHÔNG phải pinned →
             match theo timestamp gần nhất.
        """
        from playwright.sync_api import TimeoutError as PWTimeout

        # 1. Toast — X luôn show toast sau khi post thành công, với link "View".
        # Đợi tới 15s vì sau click Post có animation đóng modal + network.
        for sel in (
            '[data-testid="toast"]',
            'div[role="alert"]',
        ):
            try:
                page.wait_for_selector(sel, timeout=15000)
                link = page.locator(f'{sel} a[href*="/status/"]').first
                if link.count() and (href := link.get_attribute("href")):
                    if "/status/" in href:
                        logger.info("Tweet URL captured from toast: %s", href)
                        return f"https://x.com{href}" if href.startswith("/") else href
            except PWTimeout:
                continue
            except Exception:
                continue

        # 2. Fallback: navigate own profile, filter article = OWN tweet (URL prefix
        # /<own_handle>/status/) + skip pinned + skip repost. Vẫn có thể trả tweet
        # cũ nếu tweet vừa đăng chưa render xong — caller nên gọi sau khi đã verify
        # modal đóng để giảm nhầm.
        try:
            profile_link = page.locator(
                '[data-testid="AppTabBar_Profile_Link"], [data-testid="DashButton_ProfileIcon_Link"]'
            ).first
            if not profile_link.count():
                return None
            own_path = profile_link.get_attribute("href") or ""
            if not own_path.startswith("/"):
                return None
            own_handle = own_path.lstrip("/").split("/")[0]
            page.goto(f"https://x.com{own_path}", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3500)
            urls = page.evaluate("""
                () => {
                    const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
                    return articles.map(art => {
                        const pinned = !!art.querySelector('[data-testid="socialContext"]');
                        const link = art.querySelector('a[href*="/status/"]');
                        return { pinned, href: link ? link.getAttribute('href') : null };
                    });
                }
            """)
            own_prefix = f"/{own_handle}/status/"
            for entry in urls:
                if entry.get("pinned"):
                    continue
                h = entry.get("href") or ""
                if not h.startswith(own_prefix):
                    continue  # Repost của user khác, dù show trên profile vẫn skip.
                full = f"https://x.com{h}"
                logger.info("Tweet URL captured from profile (own_handle=%s): %s", own_handle, full)
                return full
        except Exception as exc:
            logger.warning("Profile fallback for tweet URL failed: %s", exc)
        return None
