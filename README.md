# telegram-otp-auth

[![ci](https://github.com/HOFFMAN-ALTERNATIVE/telegram-otp-auth/actions/workflows/ci.yml/badge.svg)](https://github.com/HOFFMAN-ALTERNATIVE/telegram-otp-auth/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?logo=telegram&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

**Passwordless website login with one-time codes delivered by your Telegram bot.**
A small FastAPI module + aiogram 3 bot, built security-first and documented with a full [threat model](docs/threat-model.md).

## Why

Telegram is already on your users' phones and is a great second channel — but home-made OTP flows are
routinely broken: codes stored in plain text, no attempt limits, reusable codes, race conditions, spoofable IP limits.
This project is a reference implementation that gets those details right and **proves it with tests**.

## Security properties

| Property | How |
|---|---|
| Codes never stored | only `HMAC-SHA256(secret, challenge_id:code)` is kept in Redis |
| CSPRNG codes | `secrets.randbelow`, no modulo bias, configurable length (6–10) |
| Short-lived | challenge TTL 5 min, delivered code TTL 2 min |
| Single use | atomic compare-and-delete Lua script — concurrent verifies: exactly one wins |
| Attempt limit | 5 wrong codes per challenge → challenge burned |
| Brute-force lockout | 10 failures/hour per Telegram account → 15 min lock |
| Rate limits | per IP (start, verify) and per Telegram user (codes/hour), resend cap per challenge |
| Constant-time compare | `hmac.compare_digest` |
| Challenge binding | first Telegram account to claim a challenge owns it — links can't be hijacked |
| Session | random 256-bit token, HttpOnly + Secure + SameSite=Strict cookie, server-side revocation |
| Web hardening | strict CSP (no inline JS), `no-store`, `nosniff`, `frame-ancestors 'none'`, XFF trusted only for configured hops |
| Privacy-friendly logs | events only (`login.success`, `account.locked`…), never codes, tokens or IPs |

All values are tunable in [`.env.example`](.env.example).

## How it works

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant B as Browser
  participant W as Web API
  participant R as Redis
  participant T as Telegram bot
  B->>W: POST /auth/telegram/start
  W->>R: create challenge (TTL)
  W-->>B: deep link t.me/<bot>?start=<challenge>
  U->>T: Start
  T->>R: bind challenge → Telegram user, store HMAC(code)
  T-->>U: 🔐 123 456
  U->>B: enters code
  B->>W: POST /auth/telegram/verify
  W->>R: constant-time check · atomic consume
  W-->>B: Set-Cookie session (HttpOnly, SameSite=Strict)
```

## Quick start

```bash
git clone https://github.com/HOFFMAN-ALTERNATIVE/telegram-otp-auth.git && cd telegram-otp-auth
cp .env.example .env     # SECRET_KEY, BOT_TOKEN, BOT_USERNAME
docker compose --profile bot up -d --build
open http://127.0.0.1:8000     # demo login page
```

## Integrating into your app

```python
from otp_auth.web.app import create_app       # mount as a sub-app…
app.mount("/login", create_app())

from otp_auth.service import OTPService        # …or use the service directly
svc = OTPService(redis, settings)
challenge = await svc.start(client_ip)
outcome, code, _ = await svc.issue_code(challenge.id, telegram_user_id)   # in your bot
result = await svc.verify(challenge.id, user_input, client_ip)            # in your API
```

| Endpoint | Result |
|---|---|
| `POST /auth/telegram/start` | `200` challenge + deep link · `429` |
| `POST /auth/telegram/verify` | `200` + cookie · `400` wrong (attempts_left) · `409` code not sent yet · `410` expired/used · `423` locked · `429` |
| `GET /auth/me` | `200 {telegram_user_id}` · `401` |
| `POST /auth/logout` | `204` |

## Examples

- [`examples/llm-web-search`](examples/llm-web-search) — a local Ollama model with web-search tool calling via self-hosted SearXNG.

## Development

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
pytest              # 28 tests, fakeredis with Lua, coverage gate 85%
ruff check . && mypy otp_auth tests
```

CI additionally runs the full HTTP flow against a real Redis in Docker.

## License

MIT — see [LICENSE](LICENSE).
