# Security Policy

## Reporting a vulnerability
Please report security issues **privately** — do not open a public issue.

- Use GitHub's **"Report a vulnerability"** (Security → Advisories) on this repository, or
- email the maintainer listed on the GitHub profile.

Include reproduction steps and impact. We aim to acknowledge reports within a few days.

## Scope & hardening notes
- **Secure-by-default:** authentication is required unless `TOME_OPEN=true` (intended for
  localhost / trusted networks only).
- **Secrets:** never commit real keys; `.env` is gitignored. Set a strong `TOME_SECRET`
  in production; change default Postgres/MinIO credentials.
- **Network surface:** only the gateway, MCP, and Library UI are meant to be exposed;
  Postgres/MinIO/Tika stay on the internal network. Terminate TLS at a reverse proxy.
- **Assets** are served via short-lived signed URLs; tokens are never placed in URLs for
  authenticated calls.

Supported version: the latest `main` / most recent release.
