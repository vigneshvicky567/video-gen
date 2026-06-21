"""Cloudflare R2 presigned GET URLs (S3 SigV4). Videos are served ONLY via
short-TTL presigned URLs minted after a Clerk + owner check — never a public
bucket — so storage can't become an auth bypass. Minimal SigV4 (no boto3 dep);
`now` is injectable for deterministic tests."""
import datetime as dt
import hashlib
import hmac
from urllib.parse import quote
from .config import settings


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _host() -> str:
    h = settings.R2_ENDPOINT or f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return h.replace("https://", "").replace("http://", "").rstrip("/")


def presign_get(key: str, expires: int | None = None, now: dt.datetime | None = None) -> str:
    expires = expires or settings.R2_PRESIGN_TTL_SECONDS
    now = now or dt.datetime.now(dt.timezone.utc)
    host = _host()
    region, service = "auto", "s3"
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    canonical_uri = "/" + settings.R2_BUCKET + "/" + quote(key, safe="/")

    qp = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{settings.R2_ACCESS_KEY_ID}/{scope}",
        "X-Amz-Date": amzdate,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(qp.items())
    )
    canonical_request = "\n".join([
        "GET", canonical_uri, canonical_qs, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD",
    ])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amzdate, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])
    k_date = _sign(("AWS4" + settings.R2_SECRET_ACCESS_KEY).encode(), datestamp)
    k_signing = _sign(_sign(_sign(k_date, region), service), "aws4_request")
    sig = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return f"https://{host}{canonical_uri}?{canonical_qs}&X-Amz-Signature={sig}"


def final_video_key(job_id: str) -> str:
    return f"jobs/{job_id}/final.mp4"
