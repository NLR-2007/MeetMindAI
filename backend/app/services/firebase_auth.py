"""Verifying Firebase ID tokens, for Google sign-in.

The browser signs in with Google through Firebase and gets an ID token. That
token proves who the user is — but only if it is verified properly, so this
checks the signature against Google's published keys, the issuer, the
audience (which must be this Firebase project) and the expiry.

Deliberately no shortcuts: decoding a JWT without verifying it would let
anyone mint a token claiming to be anybody, and the whole product rests on
knowing whose promises are whose.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

# Google's public keys for Firebase ID tokens.
CERTS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)
ISSUER_PREFIX = "https://securetoken.google.com/"


class FirebaseAuthError(RuntimeError):
    """The token is not one we can trust."""


# PyJWKClient caches keys and refreshes them when it sees an unknown key id,
# so this is built once rather than per request.
_jwk_client: PyJWKClient | None = None


def _client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(CERTS_URL, cache_keys=True)
    return _jwk_client


def verify_id_token(token: str, project_id: str) -> dict[str, Any]:
    """Return the token's claims, or raise FirebaseAuthError.

    `project_id` must be the Firebase project this app belongs to. Without
    that check a valid token from somebody else's Firebase project would be
    accepted here.
    """
    if not project_id:
        raise FirebaseAuthError(
            "FIREBASE_PROJECT_ID is not configured, so Google sign-in cannot "
            "be verified."
        )
    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=f"{ISSUER_PREFIX}{project_id}",
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise FirebaseAuthError("That sign-in has expired. Sign in again.") from exc
    except (jwt.InvalidTokenError, httpx.HTTPError, Exception) as exc:
        logger.warning("Rejected a Firebase ID token: %s", exc)
        raise FirebaseAuthError("Could not verify that Google sign-in.") from exc

    # Firebase sets auth_time when the user actually authenticated. A token
    # whose auth_time is in the future is not something to trust.
    auth_time = claims.get("auth_time")
    if isinstance(auth_time, int | float) and auth_time > time.time() + 60:
        raise FirebaseAuthError("Could not verify that Google sign-in.")

    if not claims.get("email"):
        raise FirebaseAuthError(
            "That Google account did not share an email address, which "
            "MeetMind needs to identify you."
        )
    return claims
