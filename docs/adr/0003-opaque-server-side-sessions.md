# 0003. Opaque session cookies stored server-side, not JWTs

Status: accepted
Date: 2026-10-17

## Context
After a successful code check the browser needs a session. The module is meant to be
mounted into someone else's app, which already has Redis available for the OTP flow.
Logout must actually end the session.

## Options
1. A signed JWT in a cookie: no lookup per request, but revocation needs a deny-list,
   which brings back the server-side lookup it was meant to avoid.
2. A signed cookie with the user id (itsdangerous style): same revocation problem.
3. A random 256-bit token in an HttpOnly, Secure, SameSite=Strict cookie, mapped to the
   Telegram user id in Redis with a TTL.

## Decision
Option 3. Revocation is one `DEL`, the cookie carries nothing readable, and the lookup
goes to a Redis that is already there.

## Consequences
- Logout and server-side expiry work immediately. Default TTL is 7 days.
- `SameSite=Strict` plus JSON bodies cover CSRF on verify and logout.
- Every authenticated request costs one Redis read.
- Redis keys hold the SHA-256 of the token, not the token, so a Redis dump does not
  contain usable sessions. (Resolved 2026-10-17. The first version of this ADR stored
  the raw token and listed hashing as an open step. Sessions created before the change
  stop resolving and users log in again once.)
- No "log out everywhere" yet. That needs a per-user index of sessions.
