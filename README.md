<!-- logo:inizio -->
<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Caslinovich/omoda9-ha/master/custom_components/omoda9/brand/dark_logo.png">
    <img src="https://raw.githubusercontent.com/Caslinovich/omoda9-ha/master/custom_components/omoda9/brand/logo.png" alt="OMODA | JAECOO" height="96">
  </picture>
</p>
<!-- logo:fine -->

# Omoda 9 / Jaecoo → Home Assistant

🌐 **English** · [Italiano](README.it.md)

Bring your **Omoda 9 / Jaecoo** car into **Home Assistant**: vehicle status,
location and commands — just like the official app, but integrated into HA.

> ✅ **Ready to use.** All you need to get started is the **email (or phone
> number)** of your Omoda/Jaecoo account, **the account's 4-digit PIN** (the one
> the app asks for to confirm remote commands — *not* your login password), plus a
> **one-time OTP code** received by email or **SMS** on first login. VIN and
> certificates are detected and installed **automatically**. The package contains
> **no personal data**: tokens and credentials stay only in *your* Home
> Assistant.

> ⚠️ **UNOFFICIAL software**, reverse-engineered. Not affiliated with Omoda /
> Jaecoo / Chery. Provided "as is", use at your own risk and only on your own
> vehicle. See [`LICENSE`](LICENSE).

## What you can do

Around **105 entities**, in short:

- **Car status** — doors, locks, trunk, hood, windows, sunroof, climate, seat
  heating/ventilation, alarm and more, as HA entities.
- **Location / GPS** — a button locates the car (`device_tracker` + location
  sensors), even while parked.
- **Battery, speed, range, mileage, tyre pressure and temperature, HV battery
  voltage/current** — read from the car's own telemetry.
- **Commands** — climate, "cool/heat everything", locate, find car, alarm,
  wake-up, window venting: buttons and switches that actually act on the car.
- **Charging** — start/stop, scheduled charging with start time and duration,
  charge status and remaining time.
- **Notifications** — optional blueprint for an alert when a command fails.

## Installation

1. **HACS → ⋮ menu → Custom repositories** → add this repo's URL, category
   **Integration**.
2. Search for **Omoda 9 / Jaecoo** → **Download** → **restart Home Assistant**.
3. **Settings → Devices & Services → Add Integration → Omoda 9**.

## First login

Everything happens **inside Home Assistant**, no external tools:

1. Choose **how to sign in**: with your **email** or with your **phone number
   (SMS)**. If your Omoda/Jaecoo account is registered with a phone number and
   has no email address, pick the second one: the first cannot work for you.
2. Enter your credentials and the **vehicle control PIN** (the 4-digit one from
   the note above; regional endpoints are optional, Europe by default):
   - **email** → HA sends an **OTP code** to your mailbox;
   - **phone** → the number **without the country code**, and the country code
     as digits only (Italy = `39`, no `+`) → HA sends an **SMS** with the code.
3. Enter the **code** you received → HA creates the session and discovers your
   vehicles.
4. If you have multiple cars, pick the **VIN**; if there's only one it is added
   directly, with all its entities.

If the session later expires (usually because you opened the official app), Home
Assistant raises a **`<your car>: session expired`** notification and flags the
integration as needing re-authentication: go to **Settings → Devices & Services →
Omoda 9 / Jaecoo → Re-authenticate** and pick **"Send me a new code"** — nothing
has to be reconfigured. No code is ever sent unless you ask for one. The same can
be done from a dashboard with the **"Request OTP code" / "Confirm OTP"** buttons
and the "OTP code" text entity.

If you sign in by SMS you may also see a third option, **"Install the fallback
TLS client"** (~12 MB download). It is only needed if the server's anti-bot
filter refuses the built-in clients — try the other options first.

## Automatic updates (off by default)

A parked car says nothing on its own, so keeping it reachable means **waking it
up** every so often — which costs a little 12 V battery and kicks the official
app off the account. That is your call, so it starts **off**:

- Turn on the **"Automatic updates"** switch (device page, *Configuration*
  section) to have HA refresh the **position** on its own. It then also follows a
  **trip** while you drive and a **charge** while the car is plugged in — that is
  when battery, mileage and the HV values actually move.
- **⋮ → Configure** sets how often: **parked** (60 min by default) and **plugged
  in** (30 min); `0` disables that interval. Same page: the vehicle's name.
  Separately, a small **read-only** check runs every few minutes to notice when
  you start driving; it never wakes the car.
- With the switch off, entities only change when the car pushes something by
  itself (for example while you use it) or when you press a button.

## Daily use

- **Don't open the official app** while the integration is active: same account →
  they disconnect each other (and a new OTP may be required).
- Many entities are `unknown` while the car is in **standby** (this is normal);
  after an HA restart they show the last known value.
- Battery, speed and mileage only refresh when the car is **driving or charging**:
  the car reports them truthfully only with the high-voltage system on. An
  automatic update on a parked car refreshes the **position**, not the odometer or
  the battery. For an immediate reading there's the **"Refresh full status"**
  button, which turns on the climate for up to ~2 minutes (usually less) to wake
  the car, then turns it off again.
- If the **PIN is wrong**, commands come back as failed and HA raises a repair
  notice that opens straight onto the PIN field. The integration stops asking the
  server after a couple of refusals, which greatly reduces — but does not remove —
  the risk of the Chery account being locked: **correct the PIN, don't retry**.

## Changing settings later

**Settings → Devices & Services → Omoda 9 / Jaecoo → ⋮ → Reconfigure** ("Change
settings"), three options, each asking only for what it changes:

- **Vehicle control PIN** — for when commands report success but the car does
  nothing. No verification code needed.
- **Receive the code by email** — switch to email, or fix a typo in the address.
- **Receive the code by SMS** — switch to SMS, or fix the number.

In both cases your current session stays valid: only the next code changes route.

## Updating the integration

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
   Jaecoo → ⋮ → Download diagnostics**. It is **already anonymized** (email,
   phone number, PIN, VIN, tUserId and GPS redacted; tokens/certificates show
   only "present: yes/no") → safe to share in an
   [issue](https://github.com/Caslinovich/omoda9-ha/issues).
2. **Detailed logs:** same page → **⋮ → Enable debug logging** → reproduce the
   problem → **Disable debug logging**: HA downloads the log. PIN, OTP and tokens
   are **never written to the logs**, the phone number appears only masked
   (`***1234`) and GPS coordinates are not logged; the value to check before
   posting is the **VIN** (the diagnostics from step 1 already hide it).

## Requirements

- Home Assistant 2024.1.0+ with HACS (the **Reconfigure** menu needs 2024.4+).
- An Omoda/Jaecoo account with the vehicle associated (**owner**). Delegate
  accounts (`authorizeType` 0) are untested.
- A local MQTT broker is **not** needed: the integration connects to the car's
  cloud **on its own**.

---

# Under the hood (technical)

Everything below is **automatic**: it's here only to understand the flow, for
debugging, or to bring the integration to a region not yet covered. In a normal
install **nothing needs to be run by hand**.

### 1. Login and token (OTP)

The first login mints a per-account **session token** from the identity (email or
phone) + OTP. Chain orchestrated by the config flow (code in
`custom_components/omoda9/core/`):

| Step | Module | What it does |
|---|---|---|
| send OTP (email) | `login_omoda.py invia <email>` | solves the gateway captcha (§2) and triggers the code by **email** |
| send OTP (SMS) | `login_omoda.py invia-sms <number-without-country-code> <country-code>` | same, via `sendSmsCode` — the one endpoint behind an Aliyun WAF that filters on the **TLS fingerprint**, handled by `tls_client.py` |
| mint token | `prova_token.py <email> <code>` | calls `/auth/oauth2/token` replicating the app (SM4 encryption) and saves the token. For phone accounts the identity is the composite `APP-LOGIN@<number>_<area>` |
| orchestration | `session.py` | exposes `request_otp()` / `confirm_otp(code)` / `check()` / `refresh()` |

The **PIN plays no part in signing in**: the OTP mints the token, the PIN only
signs commands (§4).

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

### 4. Command authorization (taskId)

Every command must carry a **taskId** minted by `checkPassword` with the PIN.
Chain replicated from the app, handled by `commands.py`:

```
bff_login (= userToken) → queryList → setVecDefault(vin)
        → checkPassword(PIN, scene=0) → taskId → command  (Authorization = userToken)
```

Note the commands are signed with the BFF **`userToken`**, not with a per-vehicle
car_token: the car_token chain (`getTuserId → loginTSP`) exists only in the
experimental `core/provision.py` and is not used at runtime.

The **PIN** is the account's 4-digit command PIN. ⚠️ A **wrong** PIN risks
**locking out** the account: it must not be guessed — every refusal increments a
counter on Chery's side. `core/pin_lockout.py` stops after 2 consecutive
rejections, but the window is a **sliding 10 minutes**: leave a wrong PIN in place
and attempts resume. The VIN must be among the authorized vehicles
(`authorizeType` 2 = owner, 0 = delegate). `provision.py` provides a
**read-only diagnostic** (`diagnose()`) that checks vehicle membership and
`authorizeType` **without touching the car**.

### Generated files (in your HA, never in the repo)

- `<config>/omoda9_<VIN>_token.json` — per-account session token.
- `<config>/omoda9_<VIN>_certs/` — mutual-TLS certificates for the MQTT broker.

Covered by `.gitignore`, they never leave your installation.

### Manual provisioning / login (advanced, outside HA)

For debugging you can use the CLI scripts in `custom_components/omoda9/core/`
with a Python that has the manifest `requirements`. Configuration comes from
environment variables — the full list is `ctx_da_environ()` in
[`core/context.py`](custom_components/omoda9/core/context.py) (`OMODA_BFF`,
`TSP_HOST`, `OMODA_TOKEN_PATH`, `OMODA_PHONE`/`OMODA_AREA`, `VIN`, `OMODA_PIN`…).

Run them from the integration folder (`<config>/custom_components/omoda9/`):

```bash
# 1) send the OTP code by email (solves the captcha)
python3 core/login_omoda.py invia <email>

#    …or by SMS, for accounts registered with a phone number
python3 core/login_omoda.py invia-sms <number-without-country-code> <country-code>

# 2) mint the token and save it in $OMODA_TOKEN_PATH (default ./token.json)
python3 core/prova_token.py <email> <code>
#    for phone accounts: OMODA_PHONE / OMODA_AREA / OMODA_OTP in the environment

# 3) (optional) vehicle/authorization diagnostic — READ-ONLY, talks to the cloud
python3 -m core.provision diagnose
```

⚠️ `provision.py` uses package-relative imports: it must be run with `-m` as
above, and the `diagnose` argument is required — with no argument it runs an
**offline mock self-test** instead of contacting anything.

The token minted this way is the **same** file the integration reads: by pointing
`OMODA_TOKEN_PATH` at `<config>/omoda9_<VIN>_token.json` you can unblock a setup
even without redoing the OTP from the config flow.

## License

[MIT](LICENSE).

**DISCLAIMER:** this is an UNOFFICIAL project, the result of reverse-engineering.
It is NOT affiliated with, endorsed by, or supported by Omoda, Jaecoo, Chery, or
any of their subsidiaries. All trademarks belong to their respective owners.
Use at your own risk.
