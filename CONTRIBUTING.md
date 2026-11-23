# Contributing to TotalDrop

Thank you for helping build **TotalDrop** — free, open-source, post-quantum end-to-end encrypted file transfer across all platforms in **35 languages**.

## 1. Language Policy (`ADR 0019`)

To keep our expanding international engineering team aligned on a single source of truth, **all GitHub collaboration runs 100% in English**:
- Issues, pull requests, code reviews, discussions, commit messages, branch names, and documentation (`docs/`) are written in English.
- Community users may open bug reports in their native language if needed; maintainers triage and reply in English.
- User-facing application, CLI, and website strings are localized across **35 languages** from the single source in `totaldrop-core/l10n/` (`ADR 0008`).

## 2. Finding the Right Repository (`ADR 0020`)

- **Protocol, Cryptography, Ghost Ring, 35-Language Source & Docs:** [`totaldrop-core`](https://github.com/totaldrop-app/totaldrop-core)
- **Tamarin Formal Proofs & Fuzz Harnesses:** [`totaldrop-formal-fuzz`](https://github.com/totaldrop-app/totaldrop-formal-fuzz)
- **Cloudflare Workers & Self-Hosted Rust Servers:** [`totaldrop-servers`](https://github.com/totaldrop-app/totaldrop-servers)
- **Website (`totaldrop.app`) & Privacy Policy:** [`totaldrop-site`](https://github.com/totaldrop-app/totaldrop-site)
- **Desktop, Mobile, TV & CLI/BSD Clients:** [`totaldrop-linux`](https://github.com/totaldrop-app/totaldrop-linux), [`totaldrop-android`](https://github.com/totaldrop-app/totaldrop-android), [`totaldrop-windows`](https://github.com/totaldrop-app/totaldrop-windows), [`totaldrop-macos`](https://github.com/totaldrop-app/totaldrop-macos), [`totaldrop-ios-tvos`](https://github.com/totaldrop-app/totaldrop-ios-tvos), [`totaldrop-cli-bsd`](https://github.com/totaldrop-app/totaldrop-cli-bsd) (`totaldrop-web-wasm` is reserved/shelved — browser receiver is not planned per [totaldrop-app/totaldrop#30](https://github.com/totaldrop-app/totaldrop/issues/30), [totaldrop-app/totaldrop#450](https://github.com/totaldrop-app/totaldrop/issues/450), [totaldrop-app/totaldrop#453](https://github.com/totaldrop-app/totaldrop/pull/453), and threat model [T9](https://github.com/totaldrop-app/totaldrop/blob/3d43e09279dc80b532beb0efe1c522233ad84ca1/docs/tehdit-modeli.md?plain=1#L73)).

## 3. Workflow, Co-Maintainer Review & Security Bar

1. Open or claim an issue before starting non-trivial work.
2. Create a focused short-lived branch (`feat/...`, `fix/...`, `pkg/...`, `gov/...`); direct pushes to `main` are disabled across all repositories.
3. Never implement cryptography in UI layers; all cryptographic and wire logic lives in `totaldrop-crypto`, `totaldrop-proto`, and `totaldrop-core` (`unsafe_code = "forbid"`).
4. Include SPDX headers (`SPDX-FileCopyrightText` and `SPDX-License-Identifier`) in the top 6 lines of every new source or script file so `./tools/check-spdx.sh` and `reuse lint` pass.
5. Every pull request requires `100%` passing `CI` checks and an explicit approving review from a Core Maintainer ([`GOVERNANCE.md`](GOVERNANCE.md): `@sadikkuzu` and `@ozdil`; maintainers never self-merge without co-maintainer approval) before rebase-merging onto `main`.
