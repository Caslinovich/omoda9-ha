"""P2-9/E4 — guard-rail sul confine fra tooling interno e package pubblicabile.

Il repo è **pubblico**. Nella stessa cartella di lavoro convivono due mondi:

  * il **package pubblicabile** (`custom_components/omoda9/`, README, LICENSE, hacs.json,
    CHANGELOG) — ciò che finisce su GitHub e da lì in HACS;
  * il **tooling interno** (script di release, handoff, il ponte legacy, questa suite) e
    i **dati per-account** (certificati, token, `.env`, file del monitor diagnostico) —
    che devono restare su disco ma fuori dal set tracciato.

`check_secrets.sh` è il gate bloccante prima di ogni release e scandaglia tutta la
history. Questi test sono la rete a maglie più larghe che gira però a OGNI esecuzione
della suite: costano millisecondi e intercettano l'errore banale — un `git add -A`
distratto — molto prima del gate.
"""
from __future__ import annotations

import os
import subprocess

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(_HERE, ".."))


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def tracciati() -> list[str]:
    """I file che git considera parte del repo (quindi pubblici)."""
    if not os.path.isdir(os.path.join(REPO, ".git")):
        pytest.skip("non è una checkout git")
    return [r for r in _git("ls-files").splitlines() if r.strip()]


# nomi/estensioni che NON devono mai comparire fra i file tracciati
VIETATI_ESATTI = {
    "omoda9.env", "token.json", ".mqtt_cred", ".gh_token",
    "check_secrets.sh", "deploy.sh", "release.sh", "ha_bridge.py",
    "hacs_refresh.py",
}
VIETATI_SUFFISSI = (
    ".key", ".pem", ".cer", ".p12", ".pfx",      # materiale crittografico
    "_diag.jsonl", "_diag.jsonl.1",              # uscite del monitor diagnostico
    "_token.json", ".env",
)
VIETATE_CARTELLE = ("certs_eu/", "data/", "venv/", ".venv-test/")


def test_nessun_segreto_fra_i_file_tracciati(tracciati):
    """Il controllo che conta: nulla di per-account nel set pubblicato."""
    colpevoli = [
        r for r in tracciati
        if os.path.basename(r) in VIETATI_ESATTI
        or r.endswith(VIETATI_SUFFISSI)
        or any(r.startswith(c) or f"/{c}" in r for c in VIETATE_CARTELLE)
    ]
    assert not colpevoli, (
        "file che NON devono stare nel repo pubblico sono tracciati: "
        f"{colpevoli}. Rimuovili con `git rm --cached` e aggiungili a "
        ".gitignore o .git/info/exclude."
    )


def test_la_suite_resta_fuori_dal_package(tracciati):
    """La suite NON deve viaggiare verso gli utenti HACS.

    NB (2026-07-20): la regola era «`tests/` non sta nel repo». È cambiata: ora la
    suite è tracciata di proposito, perché è l'unico modo di farla girare in CI
    (GitHub Actions fa il checkout del repo, e l'host di sviluppo è fermo a Python
    3.11 → non può installare un HA recente).

    Il requisito originale resta però intatto, perché «tracciato» ≠ «spedito»: lo zip
    che HACS scarica è costruito da `release.sh` a partire dalla SOLA
    `custom_components/omoda9/`. Quindi l'invariante da difendere è questo — nessun
    file di test dentro il package pubblicabile — non l'assenza dal repo.
    """
    intrusi = [
        r for r in tracciati
        if r.startswith("custom_components/omoda9/")
        and (os.path.basename(r).startswith("test_")
             or "/tests/" in r
             or os.path.basename(r) in {"conftest.py", "fixtures.py", "fake_cloud.py"})
    ]
    assert not intrusi, (
        "file di test dentro il package pubblicabile: finirebbero nello zip HACS "
        f"e quindi su ogni installazione utente: {intrusi}"
    )


def test_il_package_pubblicabile_e_completo(tracciati):
    """Lo specchio del test precedente: ciò che DEVE esserci, c'è.

    Un file dimenticato qui si nota solo quando un utente aggiorna e l'integrazione
    non parte — cioè troppo tardi."""
    richiesti = [
        "custom_components/omoda9/__init__.py",
        "custom_components/omoda9/manifest.json",
        "custom_components/omoda9/const.py",
        "custom_components/omoda9/coordinator.py",
        "custom_components/omoda9/config_flow.py",
        "custom_components/omoda9/strings.json",
        "custom_components/omoda9/translations/it.json",
        "custom_components/omoda9/translations/en.json",
        "hacs.json", "README.md", "LICENSE", "CHANGELOG.md",
    ]
    mancanti = [r for r in richiesti if r not in tracciati]
    assert not mancanti, f"file del package non tracciati: {mancanti}"


def test_ogni_piattaforma_dichiarata_e_tracciata(tracciati):
    """Una piattaforma in `PLATFORMS` il cui file non è tracciato = integrazione che
    fallisce il setup dopo l'aggiornamento HACS, ma funziona sul PC di chi sviluppa."""
    from custom_components.omoda9.const import PLATFORMS

    mancanti = [p for p in PLATFORMS
                if f"custom_components/omoda9/{p}.py" not in tracciati]
    assert not mancanti, f"piattaforme non tracciate: {mancanti}"


def test_i_moduli_core_sono_tracciati(tracciati):
    """`core/` è il cuore di protocollo: se un modulo non è tracciato, i comandi
    smettono di funzionare per gli utenti ma continuano a funzionare in locale."""
    import core_loader

    attesi = [f for f in os.listdir(os.path.abspath(core_loader.CORE_DIR))
              if f.endswith(".py")]
    mancanti = [f for f in attesi
                if f"custom_components/omoda9/core/{f}" not in tracciati]
    assert not mancanti, f"moduli core/ non tracciati: {mancanti}"


def test_gitignore_copre_i_segreti():
    """`.gitignore` deve nominare esplicitamente le famiglie sensibili: è la prima
    difesa, prima ancora del gate di release."""
    with open(os.path.join(REPO, ".gitignore"), encoding="utf-8") as fh:
        contenuto = fh.read()
    for regola in ("certs_eu/", "token.json", ".mqtt_cred", "*_diag.jsonl", "data/"):
        assert regola in contenuto, f"regola mancante in .gitignore: {regola}"


def test_versione_manifest_e_changelog_allineati():
    """La versione nel manifest deve comparire nel CHANGELOG.

    È ciò che HACS mostra all'utente al momento dell'aggiornamento: una versione
    pubblicata senza la sua voce di changelog arriva all'utente muta."""
    import json

    with open(os.path.join(REPO, "custom_components/omoda9/manifest.json"),
              encoding="utf-8") as fh:
        versione = json.load(fh)["version"]
    with open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8") as fh:
        changelog = fh.read()
    # formato scritto da release.sh: «## v1.5.29 — 2026-07-19»
    assert f"## v{versione}" in changelog, (
        f"la versione {versione} del manifest non ha una voce nel CHANGELOG"
    )


def test_changelog_pronto_per_il_prossimo_rilascio():
    """`release.sh` data la sezione `## [Non rilasciato]` e la usa come corpo della
    GitHub Release — cioè il testo che HACS mostra all'utente. Se la sezione manca,
    lo script non ha da dove prendere le note e l'aggiornamento arriva senza spiegazioni."""
    with open(os.path.join(REPO, "CHANGELOG.md"), encoding="utf-8") as fh:
        changelog = fh.read()
    assert "## [Non rilasciato]" in changelog, (
        "manca la sezione '## [Non rilasciato]': release.sh non avrebbe note da pubblicare"
    )


def test_manifest_non_rivendica_logger_generici():
    """Il rovescio di P1-7, dopo P2-2.

    Quando i moduli core/ si importavano per nome nudo, i loro logger si chiamavano
    `commands`, `wake`, `session`, `probe` e andavano dichiarati in `manifest.loggers`
    per essere governabili. Ora vivono sotto `custom_components.omoda9.core.*`, dove Home
    Assistant li mappa da sé. Continuare a rivendicare quei nomi generici sarebbe peggio
    che inutile: se un'ALTRA integrazione scrivesse su un logger `commands`, HA
    attribuirebbe i suoi messaggi a noi."""
    import json

    with open(os.path.join(REPO, "custom_components/omoda9/manifest.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)

    generici = {"commands", "wake", "session", "probe", "codes", "omoda"}
    rivendicati = set(manifest.get("loggers", []))
    assert not (rivendicati & generici), (
        f"il manifest rivendica logger dal nome generico: {rivendicati & generici}"
    )


def test_i_logger_di_core_sono_nel_namespace_dell_integrazione():
    """Conferma il presupposto del test precedente: i logger dei moduli core/ sono
    ottenuti da `__name__`, quindi ereditano il namespace del pacchetto."""
    from custom_components.omoda9.core import commands

    assert commands._LOGGER.name.startswith("custom_components.omoda9.core"), (
        f"logger fuori dal namespace dell'integrazione: {commands._LOGGER.name}"
    )
