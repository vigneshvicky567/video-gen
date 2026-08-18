"""Launch the script-writer service standalone for manual council testing.

Loads .env (real NVIDIA_API_KEY), wires sys.path so `app` (script-writer) and
`shared` both resolve, then serves on 127.0.0.1:8001. Not a pytest target.
"""
import os
import sys

from dotenv import load_dotenv

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(REPO, ".env"))

SW = os.path.join(REPO, "services", "script-writer")
sys.path.insert(0, REPO)   # shared.*
sys.path.insert(0, SW)     # app.* (script-writer)
os.chdir(SW)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, log_level="warning")
