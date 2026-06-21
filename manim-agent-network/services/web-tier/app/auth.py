"""Clerk JWT auth. Verifies the session token's RS256 signature against Clerk's
JWKS (cached, networkless after first fetch). Role comes from Clerk
public_metadata.role; mirrored into the local users table on first sight."""
from dataclasses import dataclass
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request
from .config import settings
from . import db


@dataclass
class Principal:
    clerk_id: str
    role: str = "user"
    email: str = ""


_jwk_client = None


def _jwks():
    global _jwk_client
    if _jwk_client is None and settings.CLERK_JWKS_URL:
        _jwk_client = PyJWKClient(settings.CLERK_JWKS_URL)
    return _jwk_client


def verify_token(token: str) -> Principal:
    client = _jwks()
    if client is None:
        raise HTTPException(503, "auth not configured")
    try:
        signing_key = client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, signing_key, algorithms=["RS256"],
            issuer=settings.CLERK_ISSUER or None,
            audience=settings.CLERK_AUDIENCE or None,
            options={"verify_aud": bool(settings.CLERK_AUDIENCE),
                     "verify_iss": bool(settings.CLERK_ISSUER)},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}")
    meta = claims.get("public_metadata") or claims.get("metadata") or {}
    role = meta.get("role", "user")
    return Principal(clerk_id=claims["sub"], role=role, email=claims.get("email", ""))


async def get_principal(request: Request) -> Principal:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    p = verify_token(auth[7:])
    user = db.get_or_create_user(p.clerk_id, p.email, p.role)
    if user and user.get("banned"):
        raise HTTPException(403, "account suspended")
    return p


async def require_user(p: Principal = Depends(get_principal)) -> Principal:
    return p


async def require_admin(p: Principal = Depends(get_principal)) -> Principal:
    if p.role != "admin":
        raise HTTPException(403, "admin only")
    return p
