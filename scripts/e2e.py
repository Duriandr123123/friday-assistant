"""Exercise real local HTTP server with a WAV recording. No paid APIs invoked by this script."""
import argparse
import json
import sys
import time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.core.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    settings = Settings()
    recording_id = str(uuid4())
    with httpx.Client(base_url=f"http://127.0.0.1:{settings.port}",
                      headers={"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}, timeout=60) as client:
        assert client.get("/health").status_code == 200
        with args.audio.open("rb") as audio:
            response = client.post("/recordings", files={"file": ("sample.wav", audio, "audio/wav")},
                data={"recording_id": recording_id, "captured_at": datetime.now(timezone.utc).isoformat(),
                      "source": "e2e-test", "device": "test-client"})
        response.raise_for_status()
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            result = client.get(f"/recordings/{recording_id}").json()
            if result["status"] in ("saved", "awaiting_ai", "failed"):
                break
            time.sleep(2)
        else:
            raise RuntimeError(f"Processing timeout; recording retained: {recording_id}")
        if result["status"] == "failed":
            raise RuntimeError(f"Processing failed: {result['error']}; recording retained: {recording_id}")
        markdown = client.get(f"/notes/{recording_id}/markdown")
        markdown.raise_for_status()
        report = {"recording_id": recording_id, "status": result["status"], "processing_mode": result["processing_mode"],
                  "raw_transcript": result["raw_transcript"], "markdown_bytes": len(markdown.content),
                  "audio_verified": client.get(f"/recordings/{recording_id}/audio").content == args.audio.read_bytes()}
        (settings.data_directory / "e2e-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
