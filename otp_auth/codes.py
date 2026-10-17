import hashlib
import hmac
import secrets


def generate_code(length: int) -> str:
    """Uniformly random numeric code from a CSPRNG (no modulo bias)."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def digest_code(secret: bytes, challenge_id: str, code: str) -> str:
    """HMAC-SHA256 bound to the challenge: a leaked digest can't be replayed on another challenge,
    and an offline brute-force of the 10^6 space requires the server secret."""
    msg = f"{challenge_id}:{code}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def codes_match(expected_digest: str, secret: bytes, challenge_id: str, code: str) -> bool:
    """Constant-time comparison of digests."""
    return hmac.compare_digest(expected_digest, digest_code(secret, challenge_id, code))


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_digest(token: str) -> str:
    """SHA-256 of a session token, used as its storage key. The token carries 256 random
    bits, so a fast unkeyed hash is enough: a Redis dump no longer contains usable sessions."""
    return hashlib.sha256(token.encode()).hexdigest()
