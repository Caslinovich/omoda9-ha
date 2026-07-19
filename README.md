# Omoda 9 / Jaecoo → Home Assistant

🌐 **English** · [Italiano](README.it.md)

Bring your **Omoda 9 / Jaecoo** car into **Home Assistant**: vehicle status,
location and commands — just like the official app, but integrated into HA.

> ✅ **Ready to use.** All you need to get started is the **email + PIN** of your
> Omoda/Jaecoo account (plus a **one-time OTP code** received by email on first
> login). VIN and certificates are detected and installed **automatically**. The
> package contains **no personal data**: tokens and credentials stay only in
> *your* Home Assistant.

> ⚠️ **UNOFFICIAL software**, reverse-engineered. Not affiliated with Omoda /
> Jaecoo / Chery. Provided "as is", use at your own risk and only on your own
> vehicle. See [`LICENSE`](LICENSE).

## What you can do

- **Car status** — doors, locks, trunk, hood, windows, roof, climate, seat
  heating/ventilation and more, as HA entities.
- **Location / GPS** — a button locates the car (`device_tracker` + location
  sensors), even while parked.
- **Battery, speed, range, mileage** — update automatically when the car is
  **driving or charging**; during charging the monitor follows the progress.
- **Commands** — buttons for climate, locate, wake-up and more, that actually act
  on the car.
- **Notifications** — optional blueprint for an alert when a command fails.

## Installation

1. **HACS → ⋮ menu → Custom repositories** → add this repo's URL, category
   **Integration**.
2. Search for **Omoda 9 / Jaecoo** → **Download** → **restart Home Assistant**.
3. **Settings → Devices & Services → Add Integration → Omoda 9**.

## First login

Everything happens **inside Home Assistant**, no external tools:

1. Enter your account **email** and **PIN** (regional endpoints are optional,
   Europe by default). HA sends an **OTP code** to your email.
2. Enter the **OTP code** → HA creates the session and discovers your vehicles.
3. If you have multiple cars, pick the **VIN**; if there's only one it is added
   directly, with all its entities.

If the session later expires (usually because you opened the official app), use
the **"Request OTP code" / "Confirm OTP"** buttons (with the "OTP code" text
entity) to log back in without reconfiguring anything.

## Daily use

- **Don't open the official app** while the integration is active: same account →
  they disconnect each other (and a new OTP may be required).
- Many entities are `unknown` while the car is in **standby** (this is normal);
  after an HA restart they show the last known value.
- Battery, speed and mileage only update when the car is **driving or charging**.
  For an immediate reading while parked there's the **"Refresh full status"**
  button, which turns on the climate for ~1 minute to wake the car, then turns it
  off again.

## Updating

When a new version is released: **HACS → Omoda 9 → Update → restart Home
Assistant**. The change history is in the [CHANGELOG](CHANGELOG.md).

## Notifications when a command fails (optional)

The integration only provides the entities: it **doesn't send notifications on
its own**. If you want a **popup when a command to the car fails** (vehicle busy,
unreachable, expired session…), import the included blueprint:

[![Import the blueprint into Home Assistant](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FCaslinovich%2Fomoda9-ha%2Fblob%2Fmaster%2Fblueprints%2Fautomation%2Fomoda9%2Fcomando_fallito.yaml)

Then **Settings → Automations → Create automation → From blueprint → _Omoda 9 /
Jaecoo — Failed command alert_**. It recognizes only real failures (it ignores ✅
and ⏳), so no false alarms.

## If something doesn't work

1. **Diagnostics (recommended):** **Settings → Devices & Services → Omoda 9 /
   Jaecoo → ⋮ → Download diagnostics**. It is **already anonymized** (email, PIN,
   VIN, tUserId and GPS redacted; tokens/certificates show only "present:
   yes/no") → safe to share in an
   [issue](https://github.com/Caslinovich/omoda9-ha/issues).
2. **Detailed logs:** same page → **⋮ → Enable debug logging** → reproduce the
   problem → **Disable debug logging**: HA downloads the log. PIN, OTP and tokens
   are **never written to the logs**; the only possibly sensitive value is the
   **VIN** (the diagnostics from step 1 already hide it).

## Requirements

- Home Assistant 2024.1.0+ with HACS.
- An Omoda/Jaecoo account with the vehicle associated (owner).
- A local MQTT broker is **not** needed: the integration connects to the car's
  cloud **on its own**.

---

# Under the hood (technical)

Everything below is **automatic**: it's here only to understand the flow, for
debugging, or to bring the integration to a region not yet covered. In a normal
install **nothing needs to be run by hand**.

### 1. Login and token (OTP)

The first login mints a per-account **session token** from email + PIN + OTP.
Chain orchestrated by the config flow (code in
`custom_components/omoda9/core/`):

| Step | Module | What it does |
|---|---|---|
| send OTP | `login_omoda.py invia <email>` | solves the gateway captcha (§2) and triggers the code by **email** |
| mint token | `prova_token.py <email> <code>` | calls `/auth/oauth2/token` replicating the app (SM4 encryption) and saves the token |
| orchestration | `session.py` | exposes `request_otp()` / `confirm_otp(code)` / `check()` / `refresh()` |

The token ends up in **`<config>/omoda9_<VIN>_token.json`** (never in the repo).
As long as the **refresh_token** is valid, `session.refresh()` renews the session
**without** a new OTP. A new OTP is needed only if both token and refresh die —
typical case: **opening the official app** (single session on the cloud side).

### 2. Captcha (slider) — solved inside Home Assistant

Sending the OTP is protected by a **slider captcha**. `captcha_solver.py` solves
it **in-process** with **only `numpy` + `Pillow`** (cross-correlation and
morphology reimplemented from scratch, **no OpenCV**): so it works even on **Home
Assistant OS** (musllinux, where `opencv-python-headless` has no wheel). No user
interaction, no heavy dependencies.

### 3. Mutual-TLS MQTT certificates — auto-provisioning

Telemetry connects to the car's **EMQX** broker over **mutual-TLS**. The client
certificates (`ca.pem`, `client.pem`, `client.key`) are **universal per-region
constants** — **identical for all users**, taken from the APK's **public**
assets — **not** per-account data: account isolation comes from the MQTT
username/password and the topic ACLs, exactly like the official app.

On first start `coordinator.async_provision_certs()` deobfuscates the certs from
the bundle (`custom_components/omoda9/certs/store.json`) and writes them to
**`<config>/omoda9_<VIN>_certs/`**. Manual override: the **`certs_src`** field in
the config flow. For a region **not** present in the bundle, startup fails with a
message indicating where to put the certs.

### 4. Command provisioning (car_token)

Sending commands requires a per-vehicle **car_token** (not the BFF `userToken`).
Chain replicated from the app, handled by `commands.py`:

```
getTuserId → loginTSP (= car_token) → queryList → setVecDefault(vin)
           → checkPassword(PIN, scene) → command   (Authorization = car_token)
```

The **PIN** is the account's. ⚠️ A **wrong** PIN risks **locking out** the
account: it must not be guessed. The VIN must be among the authorized vehicles
(`authorizeType` 2 = owner, 0 = delegate). `provision.py` provides a
**read-only diagnostic** (`diagnose()`) that checks vehicle membership and
`authorizeType` **without touching the car**.

### Generated files (in your HA, never in the repo)

- `<config>/omoda9_<VIN>_token.json` — per-account session token.
- `<config>/omoda9_<VIN>_certs/` — mutual-TLS certificates for the MQTT broker.

Covered by `.gitignore`, they never leave your installation.

### Manual provisioning / login (advanced, outside HA)

For debugging you can use the CLI scripts in `custom_components/omoda9/core/`
with a Python that has the manifest `requirements`, configuring the environment
via variables (see [`omoda9.env.example`](omoda9.env.example)):

```bash
# 1) send the OTP code by email (solves the captcha)
python3 login_omoda.py invia <email>

# 2) mint the token and save it in $OMODA_TOKEN_PATH (default ./token.json)
python3 prova_token.py <email> <code>

# 3) (optional) vehicle/authorization diagnostic — READ-ONLY
python3 provision.py
```

The token minted this way is the **same** file the integration reads: by pointing
`OMODA_TOKEN_PATH` at `<config>/omoda9_<VIN>_token.json` you can unblock a setup
even without redoing the OTP from the config flow.

## License

[MIT](LICENSE).

**DISCLAIMER:** this is an UNOFFICIAL project, the result of reverse-engineering.
It is NOT affiliated with, endorsed by, or supported by Omoda, Jaecoo, Chery, or
any of their subsidiaries. All trademarks belong to their respective owners.
Use at your own risk.
