"""Cuore di protocollo Omoda/Chery — sotto-pacchetto di `custom_components.omoda9`.

Contiene la logica verificata sul campo: autenticazione BFF, firma delle richieste,
catalogo e invio comandi, sonda realtime, sveglia. Le entità di Home Assistant non
parlano mai direttamente col cloud: passano tutte da qui.

**P2-2 — perché questi moduli ora si importano con `from .core import …`**

Fino alla v1.5.29 i moduli di questa cartella si importavano fra loro per NOME NUDO
(`import wake`, `import codes`) e il component doveva aggiungere `core/` a `sys.path`,
ripulire il bytecode e ri-fissarli in `sys.modules` a ogni avvio. Tre difetti concreti:

* **collisioni di nomi** — `commands`, `session`, `wake`, `codes` sono nomi generici: un
  altro componente installato in Home Assistant con un `commands.py` proprio poteva
  vincere l'import e servire il catalogo sbagliato;
* **stato che sopravvive** — i moduli restavano in `sys.modules` anche dopo l'unload, e
  a ogni setup venivano ricaricati creandone una seconda copia (con lo stato globale
  della prima ancora in giro);
* **log non governabili** — i logger risultavano attribuiti a `commands` invece che
  all'integrazione.

Da qui in avanti sono normali moduli di pacchetto, con import relativi.

**Eccezione voluta:** `login_omoda.py` e `prova_token.py` vengono eseguiti anche come
SOTTOPROCESSI (`session.request_otp` / `confirm_otp`), dove non esiste un pacchetto
padre. Quei due — e le loro dipendenze `captcha_solver`/`omoda` — tentano l'import
relativo e ripiegano su quello nudo: funzionano in entrambi i modi.
"""
