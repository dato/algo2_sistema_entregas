# -*- coding: utf8 -*-

from apiclient import discovery
from oauth2client.service_account import ServiceAccountCredentials
from google.appengine.api import memcache
from collections import namedtuple, defaultdict
from config import SPREADSHEET_ID, ENTREGAS, SERVICE_ACCOUNT_CREDENTIALS, GRUPAL, INDIVIDUAL

SCOPE = ['https://spreadsheets.google.com/feeds']
SHEET_NOTAS = 'Notas'
SHEET_DATOS_ALUMNOS = 'DatosAlumnos'

def fetch_sheet(ranges):
    credentials = ServiceAccountCredentials.from_json_keyfile_dict(SERVICE_ACCOUNT_CREDENTIALS, SCOPE)
    service = discovery.build('sheets', 'v4', credentials=credentials)
    r = service.spreadsheets().values().batchGet(spreadsheetId=SPREADSHEET_ID, ranges=ranges).execute()
    return [_[u'values'] for _ in r[u'valueRanges']]

def parse_datos_alumnos(datos_alumnos):
    # emails_alumnos = { <padron> => <email> }
    emails_alumnos = {}
    NOMBRE = 0
    PADRON = datos_alumnos[0].index(u'Padrón')
    EMAIL = datos_alumnos[0].index(u'Email')
    for row in datos_alumnos[1:]:
        if EMAIL < len(row) and row[PADRON] and '@' in row[EMAIL]:
            emails_alumnos[row[PADRON]] = u'{} <{}>'.format(row[NOMBRE], row[EMAIL])
    return emails_alumnos

def parse_notas(notas):
    headers = notas[0]
    PADRON = headers.index(u'Padrón')

    # correctores = { <padron o grupo> => { <tp> => <nombre docente> } }
    correctores = defaultdict(dict)
    # grupos = { <grupo> => set(<padron>, ...) }
    grupos = defaultdict(set)
    # emails_docentes = { <nombre docente> => <email> }
    emails_docentes = {}

    for row in notas[1:]:
        if PADRON >= len(row) or not row[PADRON]:
            break
        padron = row[PADRON]
        for tp, tipo in ENTREGAS.iteritems():
            # si es individual: ..., docente, email, TPn, ...
            # si es grupal: ..., grupo, padron compañero, email, docente, email, TPn, ...
            col = headers.index(tp)
            email_docente = row[col - 1]
            docente = row[col - 2]
            if not '@' in email_docente:
                continue
            emails_docentes[docente] = u'{} <{}>'.format(docente, email_docente)
            if tipo == INDIVIDUAL:
                correctores[padron][tp] = docente
            else:
                grupo = row[col - 5]
                padron_compa = row[col - 4]
                email_compa = row[col - 4]
                correctores[grupo][tp] = docente
                grupos[grupo].add(padron)
                if email_compa and '@' in email_compa:
                    grupos[grupo].add(padron_compa)
    return correctores, grupos, emails_docentes

Planilla = namedtuple('Planilla', [
    'correctores',
    'grupos',
    'emails_alumnos',
    'emails_docentes',
    'entregas',
])

def _fetch_planilla():
    notas, datos_alumnos = fetch_sheet([SHEET_NOTAS, SHEET_DATOS_ALUMNOS])
    emails_alumnos = parse_datos_alumnos(datos_alumnos)
    correctores, grupos, emails_docentes = parse_notas(notas)
    return Planilla(
        correctores,
        grupos,
        emails_alumnos,
        emails_docentes,
        ENTREGAS,
    )

def fetch_planilla():
    key = 'planilla'
    planilla = memcache.get(key)
    if planilla is None:
        planilla = _fetch_planilla()
        memcache.set(key, planilla, 600) # 10 minutes
    return planilla