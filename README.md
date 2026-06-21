# Omoda 9 / Jaecoo → Home Assistant

Custom integration **HACS** che collega un'auto **Omoda 9 / Jaecoo** (piattaforma
telematica Chery) a **Home Assistant**. Progetto di reverse-engineering.

- **Telemetria** — connessione mutual-TLS al broker MQTT cloud dell'auto; gli
  eventi diventano entità HA (porte, serrature, baule, cofano, finestrini, tetto,
  clima, riscaldamento/ventilazione sedili…).
- **Posizione/GPS** — comando di localizzazione → `device_tracker` + sensori
  posizione (on-demand, anche ad auto parcheggiata).
- **Batteria / velocità / odometro** — disponibili ad auto **in marcia**.
- **Comandi** — pulsanti (clima on/off, localizza, sveglia, ecc.) che agiscono
  sull'auto coniando un `taskId` proprio.
- **Sessione/OTP** — config flow per-utente + entità di recupero sessione.

> ⚠️ **Software NON ufficiale**, reverse-engineered. Nessuna affiliazione con
> Omoda / Jaecoo / Chery. Fornito "as is", usalo a tuo rischio e solo sul tuo
> veicolo. Vedi [`LICENSE`](LICENSE).

## Installazione (HACS)

1. HACS → menu ⋮ → **Custom repositories** → aggiungi l'URL di questo repo,
   categoria **Integration**.
2. Cerca **Omoda 9 / Jaecoo** → **Download** → **riavvia Home Assistant**.
3. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Omoda 9** e
   segui il config flow (bastano **email + PIN**).

### Login (OTP) — interamente in Home Assistant, solo email + PIN

Il login avviene **dal config flow**, senza strumenti esterni né un token
pre-esistente, e chiede **solo l'email e il PIN** dell'account: VIN e tUserId
vengono **rilevati automaticamente** dal backend.

1. **Primo step:** inserisci `email` e `PIN` (gli endpoint regionali sono
   opzionali, default Europa). Alla conferma HA risolve **da solo** il captcha
   del gateway e invia un **codice OTP alla tua email**.
2. **Secondo step:** inserisci il codice ricevuto → HA conia il token e
   **scopre** il tUserId e i veicoli dell'account.
3. **Se l'account ha più auto**, scegli il VIN; se è una sola, viene aggiunta
   direttamente. Il dispositivo è creato con tutte le entità.

Quando in futuro la sessione scade (tipicamente perché è stata aperta l'app
ufficiale), usa i pulsanti **«Richiedi codice OTP»** / **«Conferma OTP»** (con
l'entità *testo* «Codice OTP») per rifare il login senza riconfigurare.

## Aggiornamento

Quando esce una nuova release: **HACS → Omoda 9 → Update → riavvia Home Assistant**.

## Requisiti

- Home Assistant 2024.1.0+ con HACS.
- Un account Omoda/Jaecoo con il veicolo associato (proprietario).
- Un broker MQTT raggiungibile da Home Assistant (es. add-on Mosquitto).

## Configurazione per-utente

I dati per-account (token, certificati mutual-TLS) sono generati/raccolti dal
config flow e **non** sono inclusi nel repository. Endpoint regionali con default
EU, override disponibili in fase di setup.

## Note d'uso

- **Non aprire l'app ufficiale Omoda/Jaecoo** mentre l'integrazione è attiva:
  stesso clientId → si scollegano (e può invalidare il token → nuovo OTP).
- Molte entità sono `unknown` ad **auto in standby** (atteso).
- Batteria/velocità/odometro arrivano **solo ad auto in marcia**.

## Stato / roadmap

- ✅ Telemetria, posizione/GPS, batteria/velocità, comandi, sessione/OTP.
- ✅ **OTP da zero su Home Assistant OS** (v0.2.1): il captcha è risolto
  interamente in HA con `numpy`+`Pillow` (niente più `opencv`/`cv2`), quindi il
  login dal config flow funziona su qualsiasi installazione, anche senza un token
  preesistente. Con un token valido la sessione si auto-rinnova senza captcha.
- ⬜ Persistenza posizione/realtime al riavvio di HA (`RestoreEntity`).
- ⬜ Provisioning certificati e continuità entity_id dentro il config flow.

## Licenza

[MIT](LICENSE). Progetto indipendente, non ufficiale.
