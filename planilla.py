import collections
import threading
import time

import gspread
import cachetools.func
from oauth2client.service_account import ServiceAccountCredentials

from config import load_config

SCOPE = ['https://spreadsheets.google.com/feeds']
SHEET_NOTAS = 'Notas'
SHEET_DATOS_ALUMNOS = 'DatosAlumnos'
SHEET_DATOS_DOCENTES = 'DatosDocentes'

__all__ = [
    "fetch_planilla",
]

cfg = load_config()

def fetch_sheet(ranges):
    credentials = ServiceAccountCredentials.from_json_keyfile_name(
        cfg.service_account_jsonfile, SCOPE
    )
    gc = gspread.authorize(credentials)
    sheet = gc.open_by_key(cfg.spreadsheet_id)
    return [sheet.worksheet(worksheet) for worksheet in ranges]


def parse_datos_alumnos(datos_alumnos):
    # emails_alumnos = { <padron> => <email> }
    emails_alumnos, nombres_alumnos = {}, {}
    celdas = datos_alumnos.get_all_values()
    PADRON = celdas[0].index('Padrón')
    EMAIL = celdas[0].index('Email')
    NOMBRE = celdas[0].index('Alumno')
    for row in celdas[1:]:
        padron = safely_get_column(row, PADRON)
        if not padron:
            continue

        email_alumno = safely_get_column(row, EMAIL)
        if email_alumno and '@' in email_alumno:
            emails_alumnos[padron] = email_alumno

        nombre_alumno = safely_get_column(row, NOMBRE)
        if nombre_alumno:
            nombres_alumnos[padron] = nombre_alumno

    return emails_alumnos, nombres_alumnos


def safely_get_column(row, col_number):
    return row[col_number] if col_number < len(row) else ""


def parse_notas(notas):
    celdas = notas.get_all_values()
    headers = celdas[0]

    PADRON = headers.index('Padrón')
    DOCENTE_INDIV = headers.index('Ayudante')
    DOCENTE_GRUP = headers.index('Ayudante grupo')
    NRO_GRUPO = headers.index('Nro Grupo')

    # correctores = { <padron o grupo> => <nombre ayudante> }
    correctores = {}
    # grupos = { <grupo> => set(<padron>, ...) }
    grupos = collections.defaultdict(set)

    for row in celdas[1:]:
        # Información de las entregas individuales.
        padron = row[PADRON]
        if not padron:
            continue

        correctores[padron] = safely_get_column(row, DOCENTE_INDIV)

        # Información de las entregas grupales.
        grupo = safely_get_column(row, NRO_GRUPO)
        if grupo:
            correctores[grupo] = safely_get_column(row, DOCENTE_GRUP)
            grupos[grupo].add(padron)

        # Información de las entregas grupales como alumnos individualmente.
        # Usado solo por Javascript en las validaciones en el navegador.
        padron = f"g{padron}"
        correctores[padron] = safely_get_column(row, DOCENTE_GRUP)

    return correctores, grupos


def parse_datos_docentes(docentes):
    celdas = docentes.get_all_values()
    headers = celdas[0]

    DOCENTE = headers.index('Nombre')
    MAIL = headers.index('Mail')

    # emails_docentes = { <nombre docente> => <email> }
    emails_docentes = {}

    for row in celdas[1:]:
        docente = safely_get_column(row, DOCENTE)
        email_docente = safely_get_column(row, MAIL)
        emails_docentes[docente] = email_docente

    return emails_docentes


Planilla = collections.namedtuple('Planilla', [
    'correctores',
    'grupos',
    'emails_alumnos',
    'nombres_alumnos',
    'emails_docentes',
])


@cachetools.func.ttl_cache(maxsize=1, ttl=cfg.planilla_ttl.seconds)
def fetch_planilla():
    notas, datos_alumnos, datos_docentes = fetch_sheet([SHEET_NOTAS, SHEET_DATOS_ALUMNOS, SHEET_DATOS_DOCENTES])
    emails_alumnos,nombres_alumnos = parse_datos_alumnos(datos_alumnos)
    emails_docentes = parse_datos_docentes(datos_docentes)
    correctores, grupos = parse_notas(notas)
    return Planilla(
        correctores,
        grupos,
        emails_alumnos,
        nombres_alumnos,
        emails_docentes,
    )

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
# con peores trade-offs.
fetch_timer = threading.Thread(target=background_fetch, daemon=True)
fetch_timer.start()
