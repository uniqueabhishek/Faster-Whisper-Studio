# Security & Quality Audit — Faster-Whisper GUI

_Last updated: 2026-06-28_

A full-codebase audit was run across 9 dimensions (licensing/crypto, application
security, correctness, concurrency, resource management, architecture/quality,
dependencies, build/packaging, error-handling) with adversarial verification of
the high-severity findings. This document tracks what was found and what has been
remediated.

## Status

| Bucket | Count |
|---|---|
| ✅ Done | 83 |
| 🟡 Partial | 0 |
| ⚪ Non-essential (accepted) | 1 |
| 🔴 Pending | 2 |
| **Total findings** | **86** |

A second full 9-dimension re-audit (2026-06-28) of the current code found **0
regressions** and **29 new** second-order issues (0 Critical · 4 High · 10 Medium
· 13 Low · 2 Info) — all now fixed (see "Re-audit round 2" below). The 2 pending
items are unchanged.

**Remaining (2):** both Critical client-side-enforcement issues (a patchable
boolean and a swappable embedded key) that no purely-offline scheme can close —
a server-side activation design is in progress to address them.

> Commit hashes below predate a June 2026 history rewrite (which purged a stale
> `license.dat` blob); older hashes may not resolve, but every commit is still
> identifiable by its message. Post-rewrite work references current hashes.

Every test passes (`pytest`, 67 tests) and the GUI constructs headlessly
(offscreen smoke test) after each change.

---

## ✅ Fixed (48)

### Licensing & Cryptography
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| High | PyQt5 is GPLv3 — illegal to ship in a closed-source product without a Riverbank license | Migrated to **PySide6 (LGPLv3)** and merged to `main`; README license claim corrected | `c676f5b`, `4f75afa` |
| High | NTP-only time silently falls back to the local clock → offline clock-rollback defeats expiry | Prefer NTP (authoritative); offline, reject a clock moved backwards below a tamper-resistant, machine-bound HMAC high-water mark; 1-day skew grace | `87df3b1` |
| **High** | `get_machine_id()` silently degraded to a spoofable hostname+MAC hash — defeats node-locking and can lock out legit users | Removed the fallback; returns `HWID_UNAVAILABLE` and verification **fails closed**; `get_hwid.py` guides to support | `0718f2a` |
| **Critical** | A signed `license.dat` blob lived in public git history | Purged from all of `main` (history rewrite) and force-pushed; the app no longer reads `license.dat` (key-only flow). No private key was ever committed | history rewrite |
| Low | License signers (`admin_keygen.py` / `generate_test_license.py`) emit divergent schemas | Unified to one canonical schema; verifier validates required fields before indexing | `f750848` |
| Info | PyArmor/PyInstaller hardening claims overstated protection | Security doc now states the honest threat model (only `license_guard.py` obfuscated; bypassable enforcement) | `f750848` |

### License activation & hardening (post-audit)
The license delivery moved to a **key-only** flow (paste an `FWL-` key; no
customer-facing `.dat`) with an in-app activation screen, a Registered/Unregistered
status chip, and a vendor License Manager. A focused security sweep of the new
modules surfaced and fixed:

| Sev | Finding | Fix | Commit |
|---|---|---|---|
| Critical | `generate_keypair_and_embed()` wrote the admin **private key** with default (potentially world-readable) permissions | `chmod 0o600` on the key and `0o700` on `admin_keys/` (best-effort; no-op where unsupported) | `0718f2a` |
| High | The saved customer `license.key` was written world-readable | `chmod 0o600` on the key and `0o700` on the per-user app-data dir | `0718f2a` |
| Med | Unbounded customer name could bloat the registry/keys | Bounded to 200 chars in `build_license_data` | `0718f2a` |
| Med | `OSError` text (full filesystem path) shown in the activation UI | Generic message to the user; real error logged at warning | `0718f2a` |

### Build, Packaging & Distribution
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| High | `setup_security.py` read a missing template and wrote a key before failing | Embeds the key into `license_guard.py` in place; validates before generating keys | `77c8633` |
| High | Customer build omitted assets (missing `silero_vad.onnx`) | Builds from a single committed `FasterWhisperGUI.spec` that bundles `assets`/`Resource` | `77c8633` |
| Med | Fragile in-place obfuscation swap could leave artifacts on a crash | `build_for_customer.py` obfuscates the real signed module and restores via `try/finally` | `77c8633` |
| Med | `*.spec` gitignored while build scripts disagreed on config | One canonical, committed spec invoked by both build paths | `77c8633` |
| Med | 25 MB `vc_redist.x64.exe` committed | `git rm --cached` + gitignored (fetched at build) | `edbff2d` |
| Low | README merge-conflict markers; `.gitignore` gaps | Markers removed; `license*.dat`/`*.bak`/`pyarmor_runtime*` added | `edbff2d` |
| Low | `pyinstaller`/`pyarmor` listed as runtime deps | Moved to a `[build]` optional-dependency group | `49c932c` |

### Correctness
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| High | Smart-chunk slice failure silently truncated the transcript but marked the file "completed" | Raises on a failed slice → the file is recorded "failed" | `9cdbd84` |
| Med | `format_timestamp` truncated and dropped milliseconds | Emits rounded `HH:MM:SS.mmm` | `9cdbd84` |
| Med | Resume dropped previously-completed files from the `finished()` payload | Seeds results from `completed_files` | `191de3c` |
| Med | `update_file_status` clobbered `output_path`/`error`; `started_at` not reset on resume | Only overwrites when supplied; clears error on success; re-stamps `started_at` on processing | `4afb159` |
| Med | VAD trim ran at the wrong sample rate when librosa was unavailable | Falls back to ffmpeg silence removal | `4afb159` |
| Med | `transcribe_file` was a ~270-line god method | Decomposed into focused helpers; `TranscriptionInfo` defined once | `9cdbd84` |

### Concurrency
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| High | Torn concurrent session-JSON write broke resume | `save_session` is atomic (`mkstemp`+`os.replace`) and lock-guarded | `77c8633` |
| Med | Blocking model load froze the GUI thread | Loaded off-thread in `ModelLoaderWorker` | `9cdbd84` |
| Med | A long single file was uninterruptible mid-transcription | Real cancel token threaded through the segment/chunk/ffmpeg paths | `9cdbd84` |
| Low | Job exceptions masked — batch claimed success on failures | Emits real succeeded/failed summary with the reason per file | `191de3c`, `f750848` |
| Low | No graceful shutdown on exit | `MainWindow.closeEvent` cancels + joins workers | `49c932c` |
| Low | Module-global `EXECUTOR` shared across runs | Per-batch executor that shuts down with the batch | `49c932c` |

### Resource Management
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| High | Long-file OOM guard disabled for non-WAV input when ffmpeg was absent | ffmpeg bundled with the build (resolver + `download_ffmpeg.py` + in-app updater); conversion always runs | `2d559ff` |
| Med | Dead `clear_model_cache` / `estimate_memory_needed`; ineffective `empty_cache` | Removed | `9cdbd84` |
| Med | VAD trimmer held 2-3 full audio copies | Reads float32 and frees the full buffer + segment views before writing | `551b0f5` |
| Med | Preprocessing leaked the `mkdtemp` dir + output WAV | `atexit` cleanup of session temp dirs (stale-dir reaper covers crashes) | `49c932c` |

### Application & Data Security
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| Med | Session JSON trusted on load → path traversal / overwrite on resume | `_is_session_safe()` validates id + output containment | `f510fe4` |
| Med | `cleanup_orphaned_files` deleted any `tmp*.wav` regardless of owner | Scoped to a `fwgui_` prefix | `f510fe4` |
| Med | `download_vad.py` disabled TLS verification, no hash | Verifying TLS + pinned SHA-256 | `f510fe4` |
| Med | `download_vc_redist.py` had no integrity check | Pinned SHA-256 (verify-before-write) | `f510fe4` |
| Low | Logs recorded full media paths (PII) | Redacted to basenames | `49c932c` |

### Architecture & Quality
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| Med | Duplicated GUI widgets across 3 view files | Consolidated into `ui_common.py` | `9cdbd84` |
| Med | No real test suite (fake `test_resume_memory.py`) | Real pytest suite + offscreen GUI smoke test; fake test deleted | `9cdbd84`, `edbff2d` |
| Med | Business logic entangled with the UI | `detect_device()` / `resolve_quality()` extracted to `transcriber.py` | `551b0f5` |
| Med | Leftover dev scripts/dumps committed | Removed (`inspect_vad.py`, `debug_vad_source.py`, etc.) | `9cdbd84` |
| Low | Dead `SingleFileWorker`; VAD magic numbers; hardcoded `D:/` test paths | Removed; VAD defaults named; test deleted | `9cdbd84`, `49c932c` |
| Low | Broad `except: pass` cleanup blocks | Narrowed to `except OSError` | `f750848` |
| Low | `print()` used instead of logging | Converted in `license_guard.py` / `app.py` | `49c932c` |

### Dependencies & Logging
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| Med | `torch`/`torchaudio` CVE-era pins; `deepfilternet` collected but unused | Dropped; GPU detection via CTranslate2 | `9cdbd84` |
| Med | Security-critical deps unpinned | Pinned (`pyarmor==9.2.3`, `cryptography<47`, floors for wmi/pywin32/ntplib) | `49c932c` |
| Med | `pyqt5-qt5` pinned to a 2020 runtime under a floating binding | Eliminated by the PySide6 migration | `c676f5b` |
| Med | Logging wrote to cwd with `mode='w'` (wiped each launch, often unwritable) | Rotating log in `%LOCALAPPDATA%` | `9cdbd84` |

---

## ⚪ Non-essential (accepted, 1)

| Sev | Finding | Rationale |
|---|---|---|
| Low | Hard-raise cancel discards the partial transcript | Working feature; saving a partial `.txt` carries a UX/design question not worth the regression risk. Accepted as won't-do. |

---

## Re-audit round 2 (2026-06-28) — 29 fixed

A fresh 9-dimension re-audit with adversarial verification (38 of 53 raw findings
confirmed → 29 distinct). All fixed in `77e114b` (High + concurrency/resource/
correctness) and `9ef9e40` (cleanups).

### High (4)
| Finding | Fix |
|---|---|
| License expiry off-by-one — rejected at 00:00 on the expiry day, dropping the user's last day | Compare whole dates (valid through end of the expiry day) + boundary tests |
| `decode_key` had no input bound (activation-path DoS on a huge pasted key) | Reject input over 8 KB before any base64/JSON work |
| Build could silently ship without bundled ffmpeg | `build_exe.py`/`build_for_customer.py` assert `assets/ffmpeg/ffmpeg.exe`; README documents the download step |
| Unlocked mutation of `temp_files` in the worker `finally` (races cleanup/other workers) | Route delete + untrack through a lock-held `SessionManager.remove_temp_file` |

### Medium (10)
| Finding | Fix |
|---|---|
| `processed` progress counter read across threads unlocked | Guarded with a lock |
| `_cancel` bare bool (no cross-thread visibility guarantee) | `threading.Event` |
| Session state shared without snapshot | Covered by routing all `temp_files` access through the lock |
| Subprocess handle leak across 7 ffmpeg `Popen`+poll loops | One `_run_ffmpeg_op` helper (audio) + `try/finally` (transcriber) always reaps the child |
| Resume trusted input paths from JSON | Session file signed with a machine-independent HMAC; a tampered/planted file is refused |
| `cleanup_temp_files` could delete an arbitrary/symlinked path | Only deletes our own `fwgui_` temp WAVs; never follows symlinks |
| VAD ffmpeg fallback ignored the user's params | Honors `min_silence_ms` (threshold has no ffmpeg-dB equivalent — documented) |
| Raw exception text in the global crash dialog | Generic message; traceback to log + Details |
| Raw exception text on activation-screen import failure | Generic message; detail logged |
| Chunked-transcription error context / progress loss | Logs chunk range + type; documents that earlier chunks are discarded |

### Low / Info (15)
Generic license-manager dialog messages · classify slice-failure cause · NaN/inf
guard on the duration metric · validate/clamp loudnorm + filter params · dep
ceilings (`PySide6<7`, `faster-whisper<2`, `librosa<1`) · screenshots excluded from
the exe · dedup the file-status updater and the slider-row helper · centralize NR
presets and the cancel-button style · module-level `QTimer` import · duplicate
comment removed · `get_values` contract documented · slider lambda discards its
value explicitly.

---

## 🔴 Pending (2) — client-side enforcement

Both are architectural, not code cleanups. The Ed25519 signature still prevents
forgery without the (never-committed) private key, but the *enforcement* around it
runs on the attacker's machine and is therefore bypassable.

| Sev | Finding | Why it matters |
|---|---|---|
| **Critical** | Enforcement is one patchable boolean (`verify_license_gui()` then exit) | `app.py` is not obfuscated; an attacker NOPs the one call or stubs the module |
| **Critical** | Plaintext embedded `PUBLIC_KEY_PEM` | Swap it to sign and resell forged licenses for any machine/expiry |

**The only change that meaningfully raises the bar** against both at once is moving
verification **server-side** (online activation/heartbeat issuing short-lived
tokens, with functionality gated on server-validated state). Any purely-offline,
client-side scheme is bypassable because the trust boundary runs on the attacker's
machine.

A full server-side activation design now exists in **[`SERVER_LICENSING.md`](SERVER_LICENSING.md)**
(design only, not yet implemented). It closes **#2 decisively** (private key moves
to the backend; clients hold only pinned public keys) and closes **#1 honestly** by
gating the **encrypted model weights** on a server-issued token rather than a
patchable flag — with the residual risk stated plainly. Implementation is a phased
project gated on one product decision (whether to ship the encrypted bundled model
as the only supported model).

---

## Notes

- The audit excluded `.venv/`, `build/`, `dist/` (third-party / build artifacts).
- Verification at each step: `pytest` (64 tests) + an offscreen GUI construction
  smoke test; the GUI's interactive paths were validated manually.
