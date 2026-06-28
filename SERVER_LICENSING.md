# Server-Side Activation — Design (closes audit #1 and #2)

_Status: **design only, not implemented.** Produced from a judge-panel design pass
with adversarial review. Read the "Honest residual risk" section before committing
to a build._

## Why

Two audit findings cannot be fixed by any purely-offline scheme, because the trust
boundary runs on the attacker's machine:

- **#1 — enforcement is one patchable boolean.** `app.py` does
  `if not verify_license_gui(): sys.exit(1)`; an attacker NOPs the call.
- **#2 — the embedded `PUBLIC_KEY_PEM` is swappable.** Replace it, re-sign with
  your own key, and you can forge a license for any machine/expiry.

Moving the trust root to a small backend closes #2 outright and lets us close #1
*honestly* — but only by gating the model weights, not a flag. The hard constraint
stays: **the app must keep working offline for normal use** (no always-online).

## Architecture — three layers

### 1. Trust re-rooting → closes #2
The Ed25519 **private** key moves off the dev box / out of git history into the
backend (KMS or a Workers secret). The customer build ships only a **pinned
`{kid → public_key}` map**. Activation is a one-time online exchange; the server
mints a short-lived **server-signed JWS** token the app then verifies *offline*
every launch. Swapping the embedded pubkey now only makes the attacker's own
client accept a token *they* signed — it cannot mint a token the **server** would
have issued, and (layer 3) it yields no key to actually run the product.

### 2. Bounded-offline lifecycle → preserves "works offline"
- Token TTL **14 days**; server-set hard grace **+7 days** carried in the token
  (`grace_days` claim) → a fully-offline laptop runs **~21 days** from last check-in.
- **Silent, opportunistic heartbeat**: when online and token age > TTL/2, a
  background refresh rotates the token, so an online user never sees expiry.
- Transcription itself **never touches the network**.
- Grace is measured against the **existing** anti-rollback HMAC high-water mark
  (`_read_last_seen`/`_write_last_seen`/`_is_rollback`) **and** NTP
  (`get_network_time`) — a rolled-back clock can't buy grace.
- Past `exp + grace`: the UI still **opens** (chip shows "Revalidation required"),
  an in-flight job finishes, but new jobs are refused until one heartbeat succeeds.
  Never a silent mid-session hard-lock.

### 3. Asset-gating → the honest closure of #1
**Do not** fold the secret into `resolve_quality()` scalars — the adversarial
review proved this degenerates to "guess one of ~12 settings tuples," a
mass-redistributable crack in minutes. Instead, gate the one genuinely
high-entropy asset the vendor owns: **the model weights.**

- Ship the bundled Whisper model **AES-256-GCM-encrypted** (`model.bin.enc`).
- The per-device content-encryption key (CEK) is wrapped under
  `HKDF-SHA256(feature_seed, info="fwgui-model-cek|"+kid)` and delivered **only**
  inside a valid token's `wk` claim.
- On launch, after offline token verification, the obfuscated loader unwraps the
  CEK and decrypts the weights into a locked temp/in-memory buffer for CTranslate2.
- **NOP the boolean → no valid token → no correct CEK → the weights never decrypt
  → no working product.** The check becomes load-bearing structure, not a fence.

## Honest residual risk (read this)

1. **Asset scope.** Gating only protects the *vendor-distributed encrypted* model.
   The app currently accepts an arbitrary local model path; a user who brings a
   stock faster-whisper model + a patched binary can still transcribe with *their*
   model — but that's them rebuilding free open-source software, not pirating the
   vendor's product. Mitigation: ship the encrypted model as the default and
   token-gate the custom-path escape hatch too.
2. **Single-seat extraction.** Someone who *buys one seat* gets a genuine token,
   can decrypt the weights once, dump the plaintext model, and redistribute that
   (~GB, version-pinned). This is the real residual. Mitigations: per-release model
   **re-key** (a leaked plaintext goes stale next release); decrypt to memory /
   locked temp; ship a smaller bundled model whose leak is low-value; server
   revokes the device (kills future tokens, not an already-dumped model).
3. **No client scheme is unbreakable.** This converts *"minutes with a hex editor +
   a keygen that resells to anyone"* into *"buy one seat, dump one model version
   that goes stale next release, on a single revocable device."* That is the
   strongest practical outcome for an offline-capable closed-source desktop app —
   materially stronger and more durable than gating a flag.

**#2 is closed decisively. #1 is raised from trivial to "buy-one-and-dump," whose
strength depends entirely on the model-encryption decision below.**

## API (all HTTPS, TLS cert/SPKI-pinned; `/activate` rate-limited)

```
POST /v1/activate    { activation_code, hwid, hwid_alg:"wmi-v1", app_version, os, client_nonce }
                  →  { token, device_id, refresh_token, token_exp, server_time }
                     409 seat_limit | 404 invalid_code | 410 code_consumed
POST /v1/heartbeat   { device_id, refresh_token, hwid, token_jti, app_version }
                  →  { token, token_exp, server_time, refresh_token? } | { revoked:true } | 409 seat_conflict
POST /v1/deactivate  { device_id, refresh_token } → { ok:true }          # free a seat to move machines
GET  /v1/keys        → { keys:[ {kid, public_key_pem, status} ] }        # advisory only; clients still pin
ADMIN (separate auth): POST /admin/licenses, /admin/revoke, /admin/reassign-seat,
                       /admin/emergency-token (long-TTL for outages), /admin/rekey-model, GET /admin/devices
```

### Token = compact JWS (EdDSA), reusing the existing `cryptography` Ed25519 stack
```
header:  { "alg":"EdDSA", "typ":"FWT", "kid":"2026-06-r1" }   # kid selects the pinned pubkey → rotation lever
payload: { v, device_id, license_id, hwid, hwid_alg, customer, plan_exp,
           iat, nbf, exp,           # exp = iat + 14d
           jti,                     # 128-bit replay id, rotated each issue
           grace_days, feat,
           wk }                     # base64url AES-256-GCM-wrapped model CEK — the load-bearing field
```
Offline verify each launch (no network): split JWS → look up `kid` in the embedded
pinned map (reject unknown) → EdDSA-verify → check `typ/v/nbf/exp(+grace)` against
the high-water mark (reuse `_is_rollback`) → `hwid == get_machine_id()` → `jti` not
burned/downgraded → unwrap CEK from `wk`.

## Data model

**Server** (SQLite/D1 or Postgres): `licenses`, `activation_codes` (store only the
sha256 of the `FWA-` code), `devices` (holds the once-generated 256-bit
`feature_seed`), `model_keys` (per-`kid` CEK for re-keying), `signing_keys`
(`public_key_pem` + KMS handle, never the raw key), `token_log` (replay/downgrade),
`events` (abuse analytics — many HWIDs per license = sharing).

**Client store** (`%LOCALAPPDATA%\FasterWhisperGUI`, owner-only, replaces
`license.key`): `token.jwt`, `device.json`, `refresh.bin` (0600), the existing
`.state` high-water mark (unchanged), `seen_jti.json`. The raw `feature_seed` is
**never** stored client-side; only the wrapped CEK lives in the token and is
unwrapped per-run in memory.

## Backend recommendation
**Cloudflare Workers (Hono) + D1 + KMS** — lowest ops for a solo vendor; activations
are one-time and heartbeats ~weekly, so QPS is trivial and it sits on free/near-free
tiers ($0–$20/mo). Signing key **and** model master key live in KMS with access
logging — never in git. **Alternative:** FastAPI + managed Postgres (Neon/Supabase)
if you'd rather reuse the existing Python Ed25519 code 1:1. Either way, moving
signing off the dev machine also closes the latent "keygen toolchain in git history"
concern.

## Client integration plan (this repo)
- **`license_client.py`** (new, PyArmor-obfuscated): `activate()`, `heartbeat()`,
  token cache; TLS/SPKI-pinned `requests`; fail closed on pin mismatch.
- **`license_guard.py`**: replace `PUBLIC_KEY_PEM` with `PINNED_KEYS = {kid: pem}`
  (ship the next key ahead of rotation); add `verify_token(jws, hwid) → (ok,
  claims, reason)` (reuse `_read_last_seen`/`_is_rollback`); add
  `unwrap_model_cek(wk, kid)`; rework `verify_license_gui()` → `verify_and_unlock()`
  returning an `UnlockContext` (carrying the CEK), **not** just `True`;
  `license_status()` reads the token so the existing chip keeps working offline.
- **`app.py`**: replace the boolean gate with obtaining the `UnlockContext` and
  passing it into `MainWindow → Transcriber`.
- **`transcriber.py`**: thread an opaque `unlock` (CEK) through `TranscriptionConfig`
  / `ModelLoaderWorker`; in `_build_model`, AES-256-GCM-decrypt `model.bin.enc` with
  the CEK. Do **not** touch `resolve_quality()` (scalars are too low-entropy to gate).
- **`activation_dialog.py`**: ask for the `FWA-` activation code (not a pasted blob);
  add a "Reconnect / Revalidate" path used past grace.
- **`FasterWhisperGUI.spec`**: bundle `license_client.py` + the encrypted model + the
  pinned TLS cert; keep `licensing_core` out of the build (unchanged boundary).

## Migration (no re-purchase)
1. Seed the server from `license_registry.json` (same sha256 HWID → `devices.hwid`,
   no recompute); mint a fresh `FWA-` code per license.
2. Encrypt the bundled model once; pre-wrap each imported device's CEK.
3. **Dual-accept window (~30 days):** the new build tries the token path; if only a
   legacy `FWL-` key is present and still verifies, it works in grace mode and
   silently calls `POST /v1/activate-legacy` to claim a token — invisible to online
   users. (Ship the model unencrypted/dual during this window.)
4. Email offline/changed-HWID users their `FWA-` code.
5. Sunset: drop `FWL-`/`decode_key` acceptance and ship encrypted-only; retire the
   old offline private key (its git-history exposure becomes moot).

## Phased rollout
0. **Server** up (Workers + D1 + KMS), `/v1/activate` + `/v1/heartbeat` + `/admin`,
   seed from registry. Verify with a throwaway device.
1. **Client online path behind a flag** — `license_client.py` + `verify_token`,
   dual-accept legacy keys, model still plaintext (CEK plumbed, not yet required).
2. **Make the gate load-bearing** — ship the encrypted model + obfuscated decrypt;
   the CEK becomes required. #1 now closed at the asset layer.
3. **Sunset legacy** — encrypted-only, drop `FWL-`, retire the old key.
4. **Hardening loop** — per-release re-key, tune TTL/grace from telemetry, document
   TLS-pin/`kid` rotation runbooks.

## Open decisions (vendor must choose — start with #1)
1. **Bundled-model scope:** ship the encrypted model as the *only* supported model
   (strongest #1 closure) vs keep the arbitrary-path escape hatch (merely
   token-gated). This is the single biggest lever on how well #1 is closed.
2. Model size to bundle/encrypt (small/quantized limits single-seat dump value).
3. Decrypt target: in-memory vs locked temp dir.
4. Re-key cadence (per release? quarter?).
5. Backend host: Cloudflare Workers+D1 vs FastAPI+Postgres.
6. Key custody: external KMS vs Workers secrets.
7. TTL/grace numbers (14d/7d is a starting point).
8. Privacy/EULA: activation + heartbeat send HWID + app_version + IP — disclose it.
9. Seat-conflict policy: auto-deactivate older device vs manual reassignment.
10. Who owns the TLS-pin + `kid` rotation runbook (ship next pin/key ahead of cutover).
