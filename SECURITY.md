# Security policy

## Supported versions

radar-sec is a small project; only the latest release on `main` receives fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

Report them privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability** (private vulnerability reporting). Include what you found, how
to reproduce it and what an attacker could do with it. You should get an answer within a
week.

## What is in scope

- The API and WebSocket server (`radar serve`), which binds to `127.0.0.1` by default and
  has **no authentication**. Do not expose it to a network you do not trust.
- Handling of local secrets: `.env` (`SEC_USER_AGENT`, optional Telegram token) is never
  logged, committed or sent anywhere except to the service it belongs to.
- Parsing of untrusted documents downloaded from SEC EDGAR, FINRA and other sources
  (XML is parsed with `defusedxml`).
- The AI summaries run through the Claude Agent SDK with **no tools enabled**; filing text
  is treated as data. Reports of prompt injection that leads to actions are in scope.

## Out of scope

- The accuracy of market data or signals (see the disclaimer in the README).
- Issues in third-party services (SEC, FINRA, Yahoo Finance, logo providers, Anthropic).
