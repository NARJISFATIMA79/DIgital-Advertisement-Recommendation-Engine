"""Configuration. Secrets come from environment variables (optionally a local .env file)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def is_placeholder(value):
    v = (value or "").strip().lower()
    return (not v) or v.startswith(("your_", "paste", "changeme", "xxx", "<"))


def load_env_file(path=ROOT / ".env"):
    """Tiny .env reader so no extra dependency is needed. Existing environment variables win."""
    if not Path(path).exists():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k not in os.environ or (not os.environ[k].strip()) or (is_placeholder(os.environ[k]) and not is_placeholder(v)):
            if v:
                os.environ[k] = v  # a real value in .env is never masked by an empty or placeholder one already in the environment


load_env_file()


class Config:
    INSTANCE_DIR = Path(os.environ.get("ADPILOT_INSTANCE_DIR", ROOT / "instance"))
    DATA_DIR = Path(os.environ.get("ADPILOT_DATA_DIR", ROOT / "data" / "generated"))
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB CSV uploads
    CACHE_TTL_SECONDS = int(os.environ.get("ADPILOT_CACHE_TTL_SECONDS", 6 * 3600))
    TRANSPARENCY_TTL_SECONDS = int(os.environ.get("ADPILOT_TRANSPARENCY_TTL_SECONDS", 7 * 24 * 3600))
    DEMO_PATH = ROOT / "data" / "sample" / "demo_input.json"
