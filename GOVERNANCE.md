# Governance

TotalDrop is an independent open-source project governed openly on GitHub in **English** ([ADR 0019](https://github.com/totaldrop-app/totaldrop-core/blob/main/docs/decisions/0019-english-by-default.md)). This document defines how decisions are made across all `totaldrop-app` repositories, who holds each role, and how continuity is maintained.

## 1. Decision Model & Mandatory Co-Maintainer Approval

TotalDrop is stewarded jointly by two Core Maintainers — **[@ozdil](https://github.com/ozdil)** and **[@sadikkuzu](https://github.com/sadikkuzu)**. Decisions are made in public and recorded in English:

- **Everyday changes & Mandatory Mutual Review:** Every change starts as an English GitHub issue describing scope and completion criteria, is developed on a short-lived branch (`feat/...`, `fix/...`, `pkg/...`, `gov/...`), and reaches `main` **exclusively through a pull request** that passes the required `CI` check and **receives an approving review (`APPROVED`) from the other Core Maintainer**. Direct pushes, force-pushes, and self-merges without co-maintainer approval are strictly prohibited (`bypass_actors: []` on `main` and `main review` repository rulesets). In particular, every PR authored under `@ozdil` (including AI coding sessions operating on `@ozdil`'s behalf) requires `@sadikkuzu`'s approval before rebase-merging, and every PR authored under `@sadikkuzu` requires `@ozdil`'s approval.
- **Architecture Decision Records (`ADRs`):** Architectural, cryptographic, or cross-repository changes are recorded in [`totaldrop-core/docs/decisions/`](https://github.com/totaldrop-app/totaldrop-core/tree/main/docs/decisions). Records are never deleted; superseded decisions link forward to their replacement.
- **Protocol specification:** Wire-format and handshake decisions are recorded in [`totaldrop-core/docs/protocol-v0.1-notes.md`](https://github.com/totaldrop-app/totaldrop-core/blob/main/docs/protocol-v0.1-notes.md).
- **Security reports:** Handled privately under [SECURITY.md](SECURITY.md) until a verified fix ships across affected platforms.
- **Financial independence ([ADR 0005](https://github.com/totaldrop-app/totaldrop-core/blob/main/docs/decisions/0005-donation-model.md)):** TotalDrop accepts no venture capital, ads, telemetry, or paid tiers. Donations never grant governance authority or roadmap priority.

## 2. Roles

| Role | Responsibilities | Who |
| :--- | :--- | :--- |
| **Project Lead & Co-Maintainer** | Co-stewards roadmap, architecture, and code reviews; approves production deployments and release environments (`cloudflare`, `linux-release`, `play-release`, `windows-release`, `apple-release`); owns GitHub organization, Cloudflare, and Google Play accounts; coordinates security advisories | [@ozdil](https://github.com/ozdil) |
| **Co-Maintainer** | Co-stewards architecture, security, packaging, and code quality across all `totaldrop-app` repositories; code owner (`* @sadikkuzu @ozdil` in `.github/CODEOWNERS`); **approves pull requests before rebase-merge onto `main`**; co-owner of the `totaldrop-app` GitHub organization | [@sadikkuzu](https://github.com/sadikkuzu) |
| **Developer** | Opens branches and pull requests across repositories; all pull requests require `CI` green and Core Maintainer approval | [@zaforcan](https://github.com/zaforcan) |
| **Sub-Platform & Area Contributors** | Maintain or contribute to specific client platforms (`Linux`, `Android`, `Windows`, `macOS`, `iOS/tvOS`, `CLI/BSD`), sub-platform × CPU units (`x86_64`, `arm64`, `riscv64`), formal verification (`Tamarin` / `cargo-fuzz`), or 35-language localization (`l10n`) | Open to contributors following [CONTRIBUTING.md](CONTRIBUTING.md) |
| **Tester** | Validates pre-release builds across desktop, mobile, and TV hardware and reports regressions | Invited beta testers and community testers |
| **Security Contact** | Monitors `security@totaldrop.app` and GitHub Private Vulnerability Reporting; responds within 72 hours | [@ozdil](https://github.com/ozdil) |

AI coding assistants help author code, tests, packaging recipes, and independent diff audits, but hold **no governance authority**: every merge onto `main` requires passing `CI` and explicit human Co-Maintainer approval (`@sadikkuzu` / `@ozdil`).

## 3. Continuity

- All source code, sub-platform × CPU build recipes, formal Tamarin security models, 35-language catalogs, and GitHub Actions release workflows are public and reproducible; releases build exclusively in GitHub Actions, never on personal machines.
- Both [@ozdil](https://github.com/ozdil) and [@sadikkuzu](https://github.com/sadikkuzu) are owners of the `totaldrop-app` GitHub organization, ensuring repository governance continuity.
- Production deployment secrets (`CLOUDFLARE_API_TOKEN`, `ANDROID_UPLOAD_KEYSTORE`) reside strictly inside protected GitHub environments; Linux and CLI build provenance uses keyless OIDC Sigstore attestations. Expanding shared operational custody of external cloud/store accounts to both Co-Maintainers remains an active continuity milestone prior to `1.0`.
