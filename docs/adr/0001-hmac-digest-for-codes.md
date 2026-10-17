# 0001. Store an HMAC of each code, bound to its challenge

Status: accepted
Date: 2026-10-17

## Context
A one-time code is short (6 to 10 digits), so its whole space is small. Whatever is
stored for verification must stay useless if the store leaks, and a stored value for
one challenge must not verify another. Verification runs on every login attempt, so
it has to be cheap.

## Options
1. Store the code in plain text: trivial, and a Redis dump is a list of valid codes.
2. A password hash (bcrypt, argon2): slow by design, but a 10^6 space is still
   cracked offline in minutes, and every verify pays the cost.
3. `HMAC-SHA256(server_secret, challenge_id:code)`: cheap, needs the server secret to
   brute-force offline, and the challenge id in the message binds the digest to one challenge.

## Decision
Option 3. With a small code space, the protection comes from the secret key, not from
hash cost. Binding to the challenge id closes replay across challenges.

## Consequences
- Codes exist only in memory, long enough to be sent by the bot.
- Comparison uses `hmac.compare_digest` on fixed-length digests.
- `SECRET_KEY` becomes the critical secret. Rotating it invalidates codes in flight,
  which live at most two minutes by default.
- Online guessing is handled separately: 5 attempts per challenge and a per-account lockout.
