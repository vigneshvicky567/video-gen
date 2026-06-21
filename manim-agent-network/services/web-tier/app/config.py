"""Web-tier configuration. All values come from env; defaults are safe for
local/test (sqlite, auth/dispatch disabled). No secrets are baked in."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Database (Neon in prod, sqlite for local/test) ---
    DATABASE_URL: str = "sqlite:///./webtier.db"

    # --- Clerk auth (JWKS verification, networkless) ---
    CLERK_JWKS_URL: str = ""          # https://<instance>.clerk.accounts.dev/.well-known/jwks.json
    CLERK_ISSUER: str = ""            # https://<instance>.clerk.accounts.dev
    CLERK_AUDIENCE: str = ""          # optional

    # --- GitHub Actions dispatch (render runners) ---
    GITHUB_TOKEN: str = ""            # scoped PAT / app token with actions:write
    GITHUB_REPO: str = ""             # "owner/repo"
    GITHUB_WORKFLOW: str = "render-job.yml"
    GITHUB_REF: str = "main"
    GITHUB_API: str = "https://api.github.com"

    # --- Cloudflare R2 (video delivery via presigned GET) ---
    R2_ACCOUNT_ID: str = ""
    R2_BUCKET: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_ENDPOINT: str = ""             # optional override; else derived from account id
    R2_PRESIGN_TTL_SECONDS: int = 900

    # --- NVIDIA NIM (only for synchronous /analyze) ---
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    ANALYZE_MODEL: str = "moonshotai/kimi-k2-instruct"

    # --- Quotas / budget guards ---
    DAILY_JOB_QUOTA_DEFAULT: int = 20
    GLOBAL_CONCURRENCY_CAP: int = 3        # max simultaneously active (queued+running) jobs
    QUEUE_STALENESS_MINUTES: int = 15      # queued with no runner check-in -> failed
    MONTHLY_MINUTE_BUDGET: int = 2800      # under the 3000 Actions min/mo cap
    VARIANT_B_THRESHOLD_S: int = 540       # >~9min routes to long-video path (later)

    # --- Frontend ---
    FRONTEND_DIR: str = "/frontend"        # served same-origin (no CORS)


settings = Settings()
