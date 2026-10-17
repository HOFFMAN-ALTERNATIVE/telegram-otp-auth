# Security

## Reporting

Use GitHub's private "Report a vulnerability" button on this repository. I aim to reply within 72 hours. Please do not open public issues for exploitable bugs.

## Threat model

The full STRIDE table, with each threat and its mitigation, is in [docs/threat-model.md](docs/threat-model.md). In short:

- **Assets:** user accounts on the integrating site, session tokens, the bot token, the HMAC secret.
- **Actors:** online brute-forcers, phishers forwarding challenge links, anyone able to spoof `X-Forwarded-For`.
- **Entry points:** the start, verify and logout endpoints, the bot's message handler.
- **Mitigations:** codes stored only as HMAC-SHA256, CSPRNG codes, short TTLs, single use via an atomic Lua compare-and-delete, per-challenge attempt cap, per-account lockout, per-IP and per-user rate limits, constant-time compare, first-claimer challenge binding.
- **Runtime:** non-root image, read-only filesystem, all capabilities dropped and `no-new-privileges` in compose, Redis not published to the host.

## Supported versions

Only the latest release on `main` gets fixes.
