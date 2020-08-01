import logging
import threading
import time

import cachetools.func  # type: ignore

from google.oauth2.service_account import Credentials  # type: ignore

from algorw.planilla import Hojas, Planilla
from algorw.sheets import Config
from config import load_config


__all__ = [
    "fetch_planilla",
]

cfg = load_config()


@cachetools.func.ttl_cache(maxsize=1, ttl=cfg.planilla_ttl.seconds)
def fetch_planilla():
    logging.getLogger("entregas").info("Fetching planilla")
    credentials = Credentials.from_service_account_file(
        cfg.service_account_jsonfile,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    config = Config(
        spreadsheet_id=cfg.spreadsheet_id,
        credentials=credentials,
        sheet_list=[hoja.value for hoja in Hojas],
    )
    return Planilla(config, initial_fetch=True)


# cachetools.ttl_cache nos asegura que jamás se use una planilla más
# antigua de lo establecido. Sin embargo, de por sí, con ttl_cache
# la planilla solo tiene oportunidad de refrescarse cuando se invoca
# a la funcion. Por ello, es probable que muchas visitas demoren
# por tener que recargar una planilla que se encontraba expirada.
#
# Para acercarnos al ideal de servir todas las peticiones desde cache,
# lanzamos un hilo en segundo plano que, minuto a minuto, se asegure
# de que se refresca si había expirado.
def background_fetch():
    while True:
        fetch_planilla()  # Thread-safe gracias a cachetools.ttl_cache.
        time.sleep(55)


# Nota: para que esto funcione bien en uWSGI y su modelo de preforking,
# se debe usar "lazy-apps=true" en la configuración. Las alternativas
# "master=false" y @uwsgidecorators.{postfork,thread} mencionadas en
# https://stackoverflow.com/a/32070594/848301 también funcionan, pero
# con peores trade-offs. Además, se debe llamar a start() en main.py
# para que no haya race condition con la configuración de logging que
# hace Flask.
timer_planilla = threading.Thread(target=background_fetch, daemon=True)
