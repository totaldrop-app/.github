## Summary

Closes #

## Definition of Done

- [ ] Behavioral unit/integration tests cover both happy paths and explicit error variants (no fixed-sleep timing guesses).
- [ ] All code, comments, commit messages, and documentation are in **English** (`ADR 0019`).
- [ ] Formatting, lints (`cargo clippy -- -D warnings`), `cargo-deny`, `REUSE 3.3` (`./tools/check-spdx.sh`), and `gitleaks` pass cleanly.
- [ ] Any new wire, manifest, or IPC parser has a corresponding `cargo-fuzz` harness in `totaldrop-formal-fuzz`.
- [ ] Untrusted strings (filenames, device names, peer errors) are sanitized against control and Bidi characters before rendering.
- [ ] Protocol changes update `docs/protocol-v0.1-notes.md`; architectural changes add/update an ADR in `docs/decisions/`.
- [ ] User-facing text changes update `totaldrop-core/l10n/` (`en` source first, respecting `l10n/status.json` critical security string gates).
- [ ] Co-maintainer review requested (`@sadikkuzu` / `@ozdil`) and explicitly `APPROVED` prior to rebase merge (no direct pushes or self-merges to `main`).
