"""Settings, read from environment (optionally a .env file in the project root)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

TEMPLATES = ROOT / "templates"
FONTS = TEMPLATES / "fonts"
ASSETS = ROOT / "assets"
# Files that override assets/ (the signature, pulled from Nextcloud; never in git)
ASSET_OVERRIDES = Path(os.environ.get("GCMV_DATA", ROOT / "data")) / "assets"
WEB = ROOT / "web"
DATA = Path(os.environ.get("GCMV_DATA", ROOT / "data"))
JOBS = DATA / "jobs"
DEVICES = DATA / "devices.json"

MODEL = os.environ.get("GCMV_MODEL", "claude-sonnet-5-5")
CLAUDE_CLI = os.environ.get("GCMV_CLAUDE_CLI") or None  # None → SDK's bundled CLI

# Device guard: "auto" (only for requests arriving via Cloudflare / https / public host),
# "always", or "off".
GUARD_MODE = os.environ.get("GCMV_GUARD", "auto").lower()
PUBLIC_HOSTS = {h.strip().lower() for h in os.environ.get("GCMV_PUBLIC_HOSTS", "").split(",") if h.strip()}

TYPST = os.environ.get("GCMV_TYPST", "typst")
SOFFICE = os.environ.get("GCMV_SOFFICE", "soffice")
# Optional Collabora for docx→pdf previews when soffice is absent, e.g. http://localhost:9980
COLLABORA_URL = os.environ.get("GCMV_COLLABORA_URL", "")

NEXTCLOUD_URL = os.environ.get("NEXTCLOUD_URL", "")
NEXTCLOUD_USER = os.environ.get("NEXTCLOUD_USER", "asish")
NEXTCLOUD_APP_PASSWORD = os.environ.get("NEXTCLOUD_APP_PASSWORD", "")
NEXTCLOUD_FOLDER = os.environ.get("NEXTCLOUD_FOLDER", "School Documents").strip("/")
# The headmaster's signature lives in his Nextcloud (not in git); the server keeps a cached copy.
# Stored base64-encoded as a .txt file: his Nextcloud blocks images for his user group.
NEXTCLOUD_SIGNATURE_PATH = os.environ.get("NEXTCLOUD_SIGNATURE_PATH", "School Documents/Signature/signature.b64.txt")
# Address his browser uses to open Nextcloud (the server may talk to it on a LAN/localhost URL).
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", "")

for d in (DATA, JOBS, ASSET_OVERRIDES):
    d.mkdir(parents=True, exist_ok=True)
