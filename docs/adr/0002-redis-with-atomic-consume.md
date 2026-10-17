# 0002. Keep all state in Redis and consume codes with one Lua script

Status: accepted
Date: 2026-10-17

## Context
Every piece of state here is short-lived: challenges (5 min), codes (2 min), rate-limit
windows, lockouts, sessions. The web API and the bot are separate processes and both
read and write it. A code must be accepted exactly once, even when two verify requests
for the same challenge arrive at the same time.

## Options
1. A SQL database: durable and familiar, but needs a schema, migrations and a cleanup
   job for expired rows, and single use needs row locking or a careful `DELETE ... RETURNING`.
2. Redis with read, compare, then delete from Python: simple, but two concurrent
   requests can both pass the compare before either deletes.
3. Redis with TTLs on every key and a Lua script that checks the digest and deletes
   the challenge in one step.

## Decision
Option 3. TTLs do the cleanup, and the script runs atomically inside Redis, so of
concurrent verifies exactly one wins. A test covers that race.

## Consequences
- No migrations and no cleanup jobs. Redis runs with `maxmemory 128mb` and
  `volatile-ttl` in the compose example, so the oldest-expiring keys go first under pressure.
- Redis is a hard dependency. If it is down, logins fail and `/healthz` reports it.
  There is no fallback path, by choice.
- Counters use fixed windows, which allow a burst at a window edge. Fine for login
  limits, not for billing.
- Revisit if limits must be shared across regions. One Redis does not coordinate that.
