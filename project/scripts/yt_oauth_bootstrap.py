"""One-time OAuth bootstrap for YouTube Data API v3.

Chạy trên máy có browser (KHÔNG phải VPS headless):
    pip install google-auth-oauthlib google-api-python-client
    python scripts/yt_oauth_bootstrap.py \
        --credentials /path/to/yt_credentials.json \
        --token /path/to/yt_token.json

Sau khi hoàn tất, copy cả 2 file lên VPS (ví dụ /app/secrets/).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True, help="Đường dẫn yt_credentials.json tải từ Google Cloud Console")
    parser.add_argument("--token", required=True, help="Đường dẫn lưu yt_token.json output")
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Cài trước: pip install google-auth-oauthlib google-api-python-client", file=sys.stderr)
        return 1

    credentials_path = Path(args.credentials)
    token_path = Path(args.token)
    if not credentials_path.exists():
        print(f"Không thấy: {credentials_path}", file=sys.stderr)
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")

    data = json.loads(creds.to_json())
    print(f"\n✅ Token đã lưu: {token_path}")
    print(f"   refresh_token: {'có' if data.get('refresh_token') else 'THIẾU (chạy lại với prompt=consent)'}")
    print(f"   scopes: {data.get('scopes')}")
    print("\nCopy cả credentials.json + token.json vào /app/secrets/ trên VPS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
