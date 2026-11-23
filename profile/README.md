<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/totaldrop-app/totaldrop/main/docs/assets/lockup-dark.svg">
  <img src="https://raw.githubusercontent.com/totaldrop-app/totaldrop/main/docs/assets/lockup-light.svg" alt="TotalDrop" width="260">
</picture>

**Send any file, from any platform to any platform, in 35 languages.**<br>
Free and open source · Post-quantum end-to-end encrypted · Accountless by default, serverless **Ghost Ring** for familiar devices.

**[totaldrop.app](https://totaldrop.app)** · [Download](https://totaldrop.app/download/) · [Architecture & ADRs](https://github.com/totaldrop-app/totaldrop-core/tree/main/docs) · [Roadmap](https://totaldrop.app/roadmap/) · [Donate](https://totaldrop.app/donate/)

</div>

---

## Modular Ecosystem (11 Repositories · 53 Active Sub-Platform × CPU Targets)

All engineering, issues, pull requests, code reviews, and documentation across `totaldrop-app` run **100% in English** ([ADR 0019](https://github.com/totaldrop-app/totaldrop-core/blob/main/docs/decisions/0019-english-by-default.md), [ADR 0020](https://github.com/totaldrop-app/totaldrop-core/blob/main/docs/decisions/0020-modular-subplatform-matrix.md)). The `53` active target count covers client repositories only (`linux` 16 + `android` 10 + `windows` 6 + `macos` 6 + `ios-tvos` 6 + `cli-bsd` 9), excluding `totaldrop-core` and `totaldrop-servers`.

| Repository | Scope | Sub-Platform Formats & CPU Architectures |
| :--- | :--- | :--- |
| **[totaldrop-core](https://github.com/totaldrop-app/totaldrop-core)** | Shared Rust protocol (`CPace`, `Noise XXpsk3`, `ML-KEM-768`), Ghost Ring primitives, 35-language `l10n/` single source of truth, and canonical `docs/` | `x86_64`, `arm64`, `riscv64gc`, `armv7`, `wasm32-simd128` _(pure-Rust `wasm32-unknown-unknown` library check only; browser target shelved)_ |
| **[totaldrop-formal-fuzz](https://github.com/totaldrop-app/totaldrop-formal-fuzz)** | Tamarin Prover symbolic security proofs & `cargo-fuzz` harnesses | Formal models (`formal/*.spthy`) & continuous fuzzing |
| **[totaldrop-servers](https://github.com/totaldrop-app/totaldrop-servers)** | Cloudflare Rendezvous & Relay Workers + self-hosted Rust servers | Cloudflare Edge + Linux (`x86_64`, `arm64`) |
| **[totaldrop-site](https://github.com/totaldrop-app/totaldrop-site)** | `totaldrop.app` static site, 35-language URLs & privacy policy | Cloudflare Pages (`totaldrop.app`) |
| **[totaldrop-linux](https://github.com/totaldrop-app/totaldrop-linux)** | Native Qt 6 / Wayland desktop client & file-manager menus | `deb`, `rpm`, `tar.gz`, `arch` (`x86_64`, `arm64`, `riscv64`) · `flatpak`, `appimage` (`x86_64`, `arm64`) |
| **[totaldrop-android](https://github.com/totaldrop-app/totaldrop-android)** | Android (Material 3 Expressive) & Android TV client | `play-aab` · `fdroid-apk`, `split-apk`, `tv-apk` (`arm64-v8a`, `armeabi-v7a`, `x86_64`) |
| **[totaldrop-windows](https://github.com/totaldrop-app/totaldrop-windows)** | Native WinUI 3 client over Rust IPC/FFI bridge | `msix`, `winget`, `portable-zip` (`x86_64`, `arm64`) |
| **[totaldrop-macos](https://github.com/totaldrop-app/totaldrop-macos)** | Native SwiftUI 6 / AppKit macOS client | `dmg`, `pkg`, `homebrew` (`arm64`, `x86_64`) |
| **[totaldrop-ios-tvos](https://github.com/totaldrop-app/totaldrop-ios-tvos)** | Native SwiftUI 6 iOS, iPadOS & tvOS client + Share Extension | `ios-ipa`, `tvos-ipa` (`arm64`, `sim-arm64`, `sim-x86_64`) |
| **[totaldrop-cli-bsd](https://github.com/totaldrop-app/totaldrop-cli-bsd)** | Standalone terminal CLI & BSD packages | `static-tar.gz`, `freebsd-pkg`, `openbsd-pkg` (`x86_64`, `arm64`, `riscv64`) |
| **[totaldrop-web-wasm](https://github.com/totaldrop-app/totaldrop-web-wasm)** | _Reserved / shelved_[^web-wasm] | None (`wasm32-simd128`, `wasm32-baseline` shelved) |

[^web-wasm]: Browser receiver is marked `Not planned` in [totaldrop-app/totaldrop#30](https://github.com/totaldrop-app/totaldrop/issues/30); Rendezvous and Relay servers reject WebSocket requests carrying a browser `Origin` header with HTTP `403` per [totaldrop-app/totaldrop#450](https://github.com/totaldrop-app/totaldrop/issues/450), [totaldrop-app/totaldrop#453](https://github.com/totaldrop-app/totaldrop/pull/453), and threat model [T9](https://github.com/totaldrop-app/totaldrop/blob/3d43e09279dc80b532beb0efe1c522233ad84ca1/docs/tehdit-modeli.md?plain=1#L73).

## Contributing

Read [CONTRIBUTING.md](https://github.com/totaldrop-app/.github/blob/main/CONTRIBUTING.md) and [GOVERNANCE.md](https://github.com/totaldrop-app/.github/blob/main/GOVERNANCE.md) to get started. Security vulnerabilities should be reported privately per [SECURITY.md](https://github.com/totaldrop-app/.github/blob/main/SECURITY.md).
