# Video X Bot MVP

Bot Telegram -> X de xu ly video tu Facebook, TikTok va Instagram theo flow ban tu dong hoa mot phan.

## Mo ta ngan

Khi gui mot link video vao Telegram bot, he thong se:

1. Kiem tra link co hop le hay khong.
2. Tao job xu ly.
3. Tai video.
4. Tach audio.
5. Transcribe noi dung.
6. Tao subtitle tieng Anh `.srt`.
7. Burn subtitle vao video neu bat tinh nang nay.
8. Rewrite caption bang AI theo profile `A1-A8`.
9. Gui preview ve Telegram.
10. Dang len X sau khi duyet hoac tu dong dang neu bat auto-post.

## Nen tang ho tro

- Facebook
- TikTok
- Instagram

Luu y:
- Instagram la nguon `best effort`
- mot so link Instagram co the fail do can dang nhap, cookie, hoac bi rate-limit

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

## Cau truc du an

```text
/root/video-x-bot
  README.md
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
    Dockerfile
    docker-compose.yml
    requirements.txt
    .env.example
```

## 1. Cai dat

### Yeu cau

Can co san:

- Docker
- Docker Compose
- Telegram bot token
- DeepSeek API key
- X API credentials

### Buoc 1: vao thu muc project

```bash
cd /root/video-x-bot/project
```

### Buoc 2: tao file `.env`

```bash
cp .env.example .env
```

### Buoc 3: dien thong tin vao `.env`

Mo file [`.env`](/root/video-x-bot/project/.env) va dien cac bien toi thieu:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_IDS`
- `DEEPSEEK_API_KEY`
- `X_API_KEY`
- `X_API_KEY_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `X_BEARER_TOKEN`

### Buoc 4: chon che do dang bai

Neu muon duyet tay truoc khi dang:

```env
ENABLE_AUTO_POST=false
REQUIRE_APPROVAL_BEFORE_POST=true
```

Neu muon tu dong dang sau khi caption xong:

```env
ENABLE_AUTO_POST=true
REQUIRE_APPROVAL_BEFORE_POST=false
```

### Buoc 5: chay he thong

```bash
docker compose up -d --build
```

### Buoc 6: kiem tra container

```bash
docker compose ps
```

## 2. Xem logs

Xem toan bo logs realtime:

```bash
docker compose logs -f
```

Xem logs tung service:

```bash
docker compose logs -f bot
docker compose logs -f worker
docker compose logs -f api
docker compose logs -f redis
```

Xem 100 dong cuoi:

```bash
docker compose logs bot --tail=100
docker compose logs worker --tail=100
docker compose logs api --tail=100
docker compose logs redis --tail=100
```

## 3. Cach su dung bot

Mo Telegram va chat voi bot cua ban.

### Cac lenh co san

- `/start`
- `/help`
- `/platforms`
- `/mode`
- `/profiles`
- `/autopost on`
- `/autopost off`
- `/add <url>`
- `/status <job_id>`
- `/profile <job_id> <A1-A8>`
- `/caption <job_id>`
- `/sub <job_id>`
- `/retry <job_id>`
- `/approve <job_id>`
- `/reject <job_id>`

## 4. Y nghia tung lenh

### `/start`

Kiem tra bot dang online.

```text
/start
```

### `/help`

Hien huong dan su dung bang tieng Viet.

```text
/help
```

### `/platforms`

Liet ke cac nguon video dang duoc ho tro.

```text
/platforms
```

### `/mode`

Xem nhanh bot dang o:

- `review mode`
- hay `auto-post mode`

```text
/mode
```

### `/profiles`

Liet ke danh sach `A1-A8`, bao gom:

- ngon ngu
- style
- tone

```text
/profiles
```

### `/autopost on|off`

Bat hoac tat che do tu dong dang ngay trong Telegram.

```text
/autopost on
/autopost off
```

### `/add <url>`

Gui link video de tao job moi.

```text
/add https://www.tiktok.com/...
/add https://www.facebook.com/...
/add https://www.instagram.com/...
```

### `/status <job_id>`

Xem tien do xu ly cua job.

```text
/status 12
```

### `/profile <job_id> <A1-A8>`

Ep job dung profile cu the thay vi profile theo gio.

```text
/profile 12 A5
```

### `/caption <job_id>`

Xem caption da tao.

```text
/caption 12
```

### `/sub <job_id>`

Tai subtitle `.srt` cua job.

```text
/sub 12
```

### `/retry <job_id>`

Chay lai job neu bi loi hoac muon xu ly lai.

```text
/retry 12
```

### `/approve <job_id>`

Duyet dang bai len X khi dang o review mode.

```text
/approve 12
```

### `/reject <job_id>`

Tu choi job, khong dang bai.

```text
/reject 12
```

## 5. Quy trinh su dung de xuat

### Cach 1: review thu cong

1. Tat auto-post:

```text
/autopost off
```

2. Gui link:

```text
/add <url>
```

3. Theo doi job:

```text
/status <job_id>
```

4. Xem caption:

```text
/caption <job_id>
```

5. Duyet dang:

```text
/approve <job_id>
```

### Cach 2: tu dong dang

1. Bat auto-post:

```text
/autopost on
```

2. Gui link:

```text
/add <url>
```

3. Bot se tu xu ly va tu dang len X sau khi caption xong.

## 6. Profile A1 - A8

Mac dinh he thong co 8 profile:

- `A1`: English, clean, safe
- `A2`: English, engaging
- `A3`: Japanese
- `A4`: Korean
- `A5`: Arabic
- `A6`: Spanish
- `A7`: Latin
- `A8`: English, factual

Profile theo gio duoc dieu khien boi:

- `PROFILE_HOURLY_MAP`
- `PROFILE_TIMEZONE`

Neu muon, ban co the ep profile thu cong bang:

```text
/profile <job_id> A3
```

## 7. Trang thai job

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
failed
failed_publish
```

## 8. Instagram luu y

Instagram duoc ho tro theo kieu `best effort`.

Co the xay ra cac truong hop:

- link can dang nhap
- reel bi gioi han
- Instagram rate-limit IP

Neu Instagram fail, bot se bao loi ngan gon. Luc do ban co the:

- bo qua nguon nay
- thu link khac
- hoac cau hinh cookie cho `yt-dlp`

Neu can cookie, co the cau hinh trong `.env`:

```env
YTDLP_COOKIE_FILE=/app/storage/instagram_cookies.txt
```

hoac:

```env
YTDLP_COOKIES_FROM_BROWSER=firefox
YTDLP_BROWSER_PROFILE=default-release
```

## 9. Xu ly loi nhanh

### Job dung o `queued`

```bash
docker compose logs worker --tail=100
docker compose logs redis --tail=100
```

### Bot khong tra loi

```bash
docker compose logs bot --tail=100
```

### API loi

```bash
docker compose logs api --tail=100
```

### Publish len X bi loi

```bash
docker compose logs worker --tail=200
```

## 10. Test nhanh

```text
/start
/help
/platforms
/mode
/profiles
/autopost off
/add <url>
/status <job_id>
/caption <job_id>
/approve <job_id>
```

Hoac test auto-post:

```text
/autopost on
/add <url>
```

## 11. Test tu dong

```bash
cd /root/video-x-bot/project
.venv/bin/python -m unittest discover -s tests -q
```

## 12. Ghi chu khi push GitHub

Repo da co `.gitignore` de chan:

- `.env`
- `.venv`
- `storage/`
- cache local

Khi push len GitHub, chi nen push:

- source code
- `.env.example`
- README
- Dockerfile
- docker-compose.yml
- tests
