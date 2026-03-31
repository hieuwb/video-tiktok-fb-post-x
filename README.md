# Video X Bot MVP

Pipeline Telegram -> X de dang cho video tu Facebook, TikTok va Instagram.

## Tong quan

He thong nay cho phep ban gui link video vao Telegram bot. Bot se:

1. Kiem tra link co hop le hay khong.
2. Tao job xu ly trong SQLite.
3. Tai video bang `yt-dlp`.
4. Tach audio bang `ffmpeg`.
5. Transcribe noi dung.
6. Tao subtitle tieng Anh `.srt`.
7. Burn subtitle vao video neu bat tinh nang nay.
8. Rewrite caption bang DeepSeek theo profile `A1-A8`.
9. Gui preview ve Telegram.
10. Dang len X sau khi duyet, hoac tu dong dang neu bat auto-post.

## Nen tang duoc ho tro

- Facebook
- TikTok
- Instagram

## Cong nghe su dung

- Python 3.11
- FastAPI
- python-telegram-bot
- Celery + Redis
- SQLite
- yt-dlp
- ffmpeg
- DeepSeek API
- X API
- Docker Compose

## Cau truc thu muc

```text
project/
  app/
    api/
    bot/
    workers/
    services/
    db/
    core/
  storage/
    raw/
    audio/
    transcript/
    subtitle/
    output/
    logs/
```

## Chuan bi `.env`

```bash
cd /root/video-x-bot/project
cp .env.example .env
```

Can dien toi thieu:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`
- `DEEPSEEK_API_KEY`
- `X_API_KEY`
- `X_API_KEY_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `X_BEARER_TOKEN`

Neu tai Instagram bi chan boi login, co the cau hinh them:

- `YTDLP_COOKIE_FILE=/app/storage/instagram_cookies.txt`
hoac
- `YTDLP_COOKIES_FROM_BROWSER=firefox`
- `YTDLP_BROWSER_PROFILE=default-release`

Neu muon bat tu dong dang:

```env
ENABLE_AUTO_POST=true
REQUIRE_APPROVAL_BEFORE_POST=false
```

## Chay bang Docker

```bash
cd /root/video-x-bot/project
docker compose up -d --build
```

Kiem tra trang thai:

```bash
docker compose ps
docker compose logs api --tail=100
docker compose logs worker --tail=100
docker compose logs bot --tail=100
docker compose logs redis --tail=100
```

## Lenh Telegram

- `/start`
- `/help`
- `/add <url>`
- `/status <job_id>`
- `/approve <job_id>`
- `/reject <job_id>`
- `/retry <job_id>`
- `/profiles`
- `/autopost on|off`
- `/profile <job_id> <A1-A8>`
- `/caption <job_id>`
- `/sub <job_id>`

## Y nghia cac lenh moi

### `/profiles`

Liet ke toan bo profile `A1-A8`, bao gom:

- ma profile
- ngon ngu dich
- style caption
- tone

Vi du:

```text
/profiles
```

### `/autopost on|off`

Bat/tat che do tu dong dang ngay tren Telegram, khong can sua `.env` moi lan.

Vi du:

```text
/autopost on
/autopost off
```

### `/profile <job_id> <A1-A8>`

Ep mot job dung profile cu the thay vi lay theo khung gio.

Vi du:

```text
/profile 12 A5
```

Neu job da co transcript, he thong se tu queue caption generation lai voi profile moi.

## A1 - A8 dang mac dinh

- `A1`: English, an toan, gon gang
- `A2`: English, engaging
- `A3`: Japanese, lich su, ngan gon
- `A4`: Korean, tu nhien, trendy
- `A5`: Arabic, ro rang, an toan
- `A6`: Spanish, casual
- `A7`: Latin, formal
- `A8`: English, factual/newsy

Lich gio duoc dieu khien bang:

- `PROFILE_HOURLY_MAP`
- `PROFILE_TIMEZONE`

## Cach test thu cong tung buoc

### 1. Kiem tra bot

Gui tren Telegram:

```text
/start
/help
/profiles
/autopost off
```

Neu bot tra loi dung, phan Telegram da on.

### 2. Tao job moi

Gui:

```text
/add <link_facebook_tiktok_instagram>
```

Ky vong:

- bot bao `Job X created`
- worker nhan job

Neu la link Instagram ma bi bao login required hoac requested content is not available, nguyen nhan thuong la:

- reel/private post can session dang nhap
- Instagram rate-limit IP

Khi do hay nap cookie vao `yt-dlp` bang `YTDLP_COOKIE_FILE` hoac `YTDLP_COOKIES_FROM_BROWSER`.

### 3. Theo doi job

Gui:

```text
/status <job_id>
```

Trang thai thong thuong:

```text
queued
validating
downloading
downloaded
extracting_audio
transcribing
translating
generating_subtitle
burning_subtitle
generating_caption
awaiting_review
approved
publishing
posted
```

### 4. Doi profile thu cong

Gui:

```text
/profile <job_id> A3
/caption <job_id>
```

Ky vong:

- profile cua job doi thanh `A3`
- language doi thanh `ja`
- caption regenerate theo profile moi

### 5. Duyet tay

Neu dang o che do semi-auto:

```text
/approve <job_id>
```

Ky vong:

- job chuyen sang `publishing`
- bot tra ve `Post URL`

### 6. Tu dong dang

Bat auto-post:

```text
/autopost on
```

Sau do tao job moi:

```text
/add <url>
```

Ky vong:

- job caption xong se tu dang len X
- khong can `/approve`

## Cach debug khi job bi dung

### Job dung o `queued`

Kiem tra:

```bash
docker compose logs worker --tail=100
docker compose logs redis --tail=100
```

### Bot tra loi nhung khong publish

Kiem tra:

```bash
docker compose logs worker --tail=200
docker compose logs bot --tail=100
```

### API co song khong

```bash
curl http://127.0.0.1:8000/health
```

## Ghi chu van hanh

- `TELEGRAM_ALLOWED_USER_IDS` gioi han nguoi duoc dung bot
- `ENABLE_AUTO_POST=true` va `REQUIRE_APPROVAL_BEFORE_POST=false` se bat full auto-post
- `/autopost on|off` uu tien hon gia tri mac dinh trong `.env`
- `/profile <job_id> <A1-A8>` uu tien hon profile theo khung gio
- Whisper chay local, de thay the sau nay
- Neu DeepSeek loi mang, he thong se fallback caption de khong lam ket job

## Test tu dong

```bash
cd /root/video-x-bot/project
.venv/bin/python -m unittest discover -s tests -q
```
