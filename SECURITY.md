# Security policy

## Supported versions

Security fixes are applied to the latest version on the `main` branch.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting feature in the repository's **Security** tab. Do not open a public issue for a vulnerability and do not include API keys, credentials, private evaluation data, or exploit details in public discussions.

Please include a concise reproduction, impact assessment, affected version, and any suggested mitigation. You should receive an initial acknowledgement within seven days.

## Deployment boundary

Gaugix is a local, single-user application. It binds to `127.0.0.1` by default and does not provide authentication or tenant isolation. Do not expose it through port forwarding, a public reverse proxy, or an untrusted network.

## Untrusted code

Python scorers and explicit artifact execution can execute local code. Only run scorers and artifacts you trust, use an isolated operating-system account or sandbox for unknown code, and inspect imported benchmark logic before enabling code execution.

HTML artifacts are rendered in sandboxed iframes, but that does not make arbitrary native or Python execution safe.
