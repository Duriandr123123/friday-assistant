"""Non-secret paths and port for Windows launcher scripts."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.core.config import Settings

s = Settings()
print(json.dumps({"data": str(s.data_directory), "port": s.port}))
