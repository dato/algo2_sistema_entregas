import gspread
from oauth2client.service_account import ServiceAccountCredentials
from collections import namedtuple, defaultdict
from config import SPREADSHEET_ID, ENTREGAS, SERVICE_ACCOUNT_CREDENTIALS, GRUPAL, INDIVIDUAL

SCOPE = ['https://spreadsheets.google.com/feeds']
SHEET_NOTAS = 'Notas'
SHEET_DATOS_ALUMNOS = 'DatosAlumnos'
SHEET_DATOS_DOCENTES = 'DatosDocentes'


def fetch_sheet(ranges):
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(SERVICE_ACCOUNT_CREDENTIALS, SCOPE)
    gc = gspread.authorize(credentials)
    sheet = gc.open_by_key(SPREADSHEET_ID)
    return [sheet.worksheet(worksheet) for worksheet in ranges]


def parse_datos_alumnos(datos_alumnos):
    # emails_alumnos = { <padron> => <email> }
    emails_alumnos,nombres_alumnos = {},{}
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

    return emails_alumnos,nombres_alumnos


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
    grupos = defaultdict(set)

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

    return correctores, grupos


def parse_datos_docentes(docentes):
    celdas = docentes.get_all_values()

    # El header de los docentes está en la fila 3
    headers = celdas[2]

    DOCENTE = headers.index('Nombre')
    MAIL = headers.index('Mail')

    # emails_docentes = { <nombre docente> => <email> }
    emails_docentes = {}

    for row in celdas[1:]:
        docente = safely_get_column(row, DOCENTE)
        email_docente = safely_get_column(row, MAIL)
        emails_docentes[docente] = email_docente

    return emails_docentes


Planilla = namedtuple('Planilla', [
    'correctores',
    'grupos',
    'emails_alumnos',
    'nombres_alumnos',
    'emails_docentes',
    'entregas'
])


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
        ENTREGAS,
    )
