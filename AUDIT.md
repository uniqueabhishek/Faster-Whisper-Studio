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
| ✅ Done | 48 |
| 🟡 Partial | 0 |
| ⚪ Non-essential (accepted) | 1 |
| 🔴 Pending | 4 |
| **Total findings** | **53** |

**Critical + High (12):** 7 done · 5 pending — every remaining high-severity item
is in the licensing/secrets tier (architecture/business decisions).

Every test passes (`pytest`, 30 tests) and the GUI constructs headlessly
(offscreen smoke test) after each change.

---

## ✅ Fixed (48)

### Licensing & Cryptography
| Sev | Finding | Fix | Commit |
|---|---|---|---|
| High | PyQt5 is GPLv3 — illegal to ship in a closed-source product without a Riverbank license | Migrated to **PySide6 (LGPLv3)** and merged to `main`; README license claim corrected | `c676f5b`, `4f75afa` |
| High | NTP-only time silently falls back to the local clock → offline clock-rollback defeats expiry | Prefer NTP (authoritative); offline, reject a clock moved backwards below a tamper-resistant, machine-bound HMAC high-water mark; 1-day skew grace | `87df3b1` |
| Low | License signers (`admin_keygen.py` / `generate_test_license.py`) emit divergent schemas | Unified to one canonical schema; verifier validates required fields before indexing | `f750848` |
| Info | PyArmor/PyInstaller hardening claims overstated protection | Security doc now states the honest threat model (only `license_guard.py` obfuscated; bypassable enforcement) | `f750848` |

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

## 🔴 Pending (4) — the licensing/secrets tier

These are architecture/business decisions, not code cleanups. The Ed25519
signature still prevents forgery without the (never-committed) private key, but
the enforcement around it is bypassable on the client.

| Sev | Finding | Why it matters |
|---|---|---|
| **Critical** | Enforcement is one patchable boolean (`verify_license_gui()` then exit) | `app.py` is not obfuscated; an attacker NOPs the one call or stubs the module |
| **Critical** | Plaintext embedded `PUBLIC_KEY_PEM` | Swap it to sign and resell forged licenses for any machine/expiry |
| **Critical** | Full keygen toolchain + a signed `license.dat` are in git history | Untracked at HEAD; the history blob is low-value (no private key was ever committed) but unpurged |
| **High** | `get_machine_id()` silently degrades to a spoofable hostname+MAC hash | Defeats node-locking where the fallback is reachable; can also lock out legit users |

**The only change that meaningfully raises the bar** against all of these at once
is moving verification **server-side** (online activation/heartbeat issuing
short-lived tokens, with real functionality gated on server-validated state). Any
purely-offline, client-side scheme is bypassable because the trust boundary runs
on the attacker's machine.

---

## Notes

- The audit excluded `.venv/`, `build/`, `dist/` (third-party / build artifacts).
- Verification at each step: `pytest` (30 tests) + an offscreen GUI construction
  smoke test; the GUI's interactive paths were validated manually.
