import base64
import datetime
import json
import logging
import mimetypes
import smtplib
import traceback
from collections import namedtuple
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

import httplib2
import oauth2client.client
import urlfetch
from flask import Flask
from flask import render_template
from flask import request
from werkzeug.utils import secure_filename

from config import SENDER_NAME, EMAIL_TO, APP_TITLE, GRUPAL, RECAPTCHA_SECRET, RECAPTCHA_SITE_ID, TEST, CLIENT_ID, \
    CLIENT_SECRET, OAUTH_REFRESH_TOKEN
from planilla import fetch_planilla

app = Flask(__name__)
File = namedtuple('File', ['content', 'filename'])


EXTENSIONES_ACEPTADAS = {'zip', 'tar', 'gz', 'pdf'}


@app.route('/', methods=['GET'])
def get():
    planilla = fetch_planilla()
    return render('index.html', {
        'alumnos': json.dumps(planilla.emails_alumnos),
    })


@app.errorhandler(Exception)
def err(error):
    logging.exception(error)
    return render('result.html', {'error': error})


def render(name, params={}):
    return render_template(name, **dict(params, **{
        'title': APP_TITLE,
        'recaptcha_site_id': RECAPTCHA_SITE_ID,
        'test': TEST,
    }))


def get_padrones_grupo_docente(padron_o_grupo, tp, planilla):
    if padron_o_grupo not in planilla.correctores:
        raise Exception(u'No se encuentra el alumno o grupo {}'.format(padron_o_grupo))
    if planilla.entregas[tp] == GRUPAL:
        if padron_o_grupo in planilla.grupos:
            grupo = padron_o_grupo
        else:
            grupo = buscar_grupo(planilla.grupos, padron_o_grupo)
        padrones = planilla.grupos[grupo]
        docente = get_docente(planilla.correctores, grupo, tp)
    else:
        grupo = None
        padrones = {padron_o_grupo}
        docente = get_docente(planilla.correctores, padron_o_grupo, tp)
    return padrones, grupo, docente


def archivo_es_permitido(nombre):
    return '.' in nombre and \
           nombre.rsplit('.', 1)[1].lower() in EXTENSIONES_ACEPTADAS


def get_files():
    files = request.files.getlist('files')
    return [
        File(content=f.read(), filename=secure_filename(f.filename))
        for f in files
        if f and archivo_es_permitido(f.filename)
    ]


def sendmail(email_alumno, email_docente, tp, grupo, padrones, files, body):
    correo = MIMEMultipart()
    correo["From"] = SENDER_NAME
    correo["To"] = EMAIL_TO
    correo["Cc"] = email_alumno
    correo["Subject"] = '{} - {}'.format(tp, ' - '.join(padrones))

    correo.attach(MIMEText('\n'.join([
            tp,
            'GRUPO {}:'.format(grupo) if grupo else 'Entrega individual:',
            '\n'.join([email_alumno]),
            '\n{}\n'.format(body) if body else '',
            '-- ',
            '{} - {}'.format(APP_TITLE, request.url),
        ]), 'plain'))

    for f in files:
        # Tomado de: https://docs.python.org/3.5/library/email-examples.html#id2
        # Adivinamos el Content-Type de acuerdo a la extensión del fichero.
        ctype, encoding = mimetypes.guess_type(f.filename)
        if ctype is None or encoding is not None:
            # No pudimos adivinar, así que usamos un Content-Type genérico.
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)
        if maintype == 'text':
            msg = MIMEText(f.content, _subtype=subtype)
        else:
            msg = MIMEBase(maintype, subtype)
            msg.set_payload(f.content)
            # Codificamos el payload en base 64.
            encoders.encode_base64(msg)
        # Set the filename parameter
        msg.add_header('Content-Disposition', 'attachment', filename=f.filename)
        correo.attach(msg)

    if not TEST:
        creds = get_oauth_credentials()
        xoauth2_tok = "user=%s\1" "auth=Bearer %s\1\1" % (EMAIL_TO,
                                                          creds.access_token)
        xoauth2_b64 = base64.b64encode(xoauth2_tok.encode("ascii")).decode("ascii")

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.ehlo()  # Se necesita EHLO de nuevo tras STARTTLS.
        server.docmd("AUTH", "XOAUTH2 " + xoauth2_b64)
        server.send_message(correo)
        server.close()

    return correo


def get_oauth_credentials():
    """Refresca y devuelve nuestras credenciales OAuth.
    """
    # N.B.: siempre re-generamos el token de acceso porque este script es
    # stateless y no guarda las credenciales en ningún sitio. Todo bien con eso
    # mientras no alcancemos el límite de refresh() de Google (pero no publican
    # cuál es).
    creds = oauth2client.client.OAuth2Credentials(
        "", CLIENT_ID, CLIENT_SECRET, OAUTH_REFRESH_TOKEN,
        datetime.datetime(2015, 1, 1),
        "https://accounts.google.com/o/oauth2/token", "corrector/1.0")

    creds.refresh(httplib2.Http())
    return creds


@app.route('/', methods=['POST'])
def post():
    try:
        #validate_captcha()
        planilla = fetch_planilla()
        tp = request.form['tp'].upper()
        if tp not in planilla.entregas:
            raise Exception(u'La entrega {} es inválida'.format(tp))
        files = get_files()
        grupo = ''
        body = request.form['body'] or ''
        padrones = [request.form['padron']]
        email_alumno = planilla.emails_alumnos[padrones[0]]
        email_docente = ''
        email = sendmail(email_alumno, email_docente, tp, grupo, padrones, files, body)

        return render('result.html', {
            'sent': {
                'tp': tp,
                'email': u'\n'.join(u'[[{}]]: {}'.format(k, str(v)) for k, v in email) if TEST else None,
            },
        })
    except Exception as e:
        print(traceback.format_exc())
        err(e.message)


def validate_captcha():
    response = urlfetch.fetch(
        url='https://www.google.com/recaptcha/api/siteverify',
        params=urlencode({
            "secret": RECAPTCHA_SECRET,
            "remoteip": request.remote_addr,
            "response": request.form["g-recaptcha-response"],
        }),
        method="POST",
    )

    if not response.json['success']:
        raise Exception('Falló la validación del captcha')


def buscar_grupo(grupos, padron):
    for grupo, padrones in grupos.iteritems():
        if padron in padrones:
            return grupo
    raise Exception(u'No se encuentra el grupo para el padron {}'.format(padron))


def get_docente(correctores, padron_o_grupo, tp):
    if tp not in correctores[padron_o_grupo]:
        raise Exception(u'No hay un corrector asignado para la entrega {}'.format(tp))
    return correctores[padron_o_grupo][tp]
