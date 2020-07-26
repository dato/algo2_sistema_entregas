import base64
import collections
import io
import logging
import mimetypes
import smtplib
import zipfile

from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from flask import Flask, render_template, request
from flask_caching import Cache
from google.auth.transport.requests import Request
from google.oauth2 import credentials
from werkzeug.exceptions import FailedDependency, HTTPException
from werkzeug.utils import secure_filename

from algorw.app.queue import task_queue
from algorw.app.tasks import EntregaTask, reload_fetchmail
from config import Modalidad, Settings, load_config
from planilla import fetch_planilla, timer_planilla


app = Flask("entregas")
app.logger.setLevel(logging.INFO)

cfg: Settings = load_config()
cache: Cache = Cache(config={"CACHE_TYPE": "simple"})

cache.init_app(app)
timer_planilla.start()

File = collections.namedtuple('File', ['content', 'filename'])
EXTENSIONES_ACEPTADAS = {'zip', 'tar', 'gz', 'pdf'}


class InvalidForm(Exception):
    """Excepción para cualquier error en el form.
    """


@app.context_processor
def inject_cfg():
    return {"cfg": cfg}


@app.route("/", methods=["GET"])
def get():
    planilla = fetch_planilla()
    return render_template("index.html",
                           entregas=cfg.entregas,
                           correctores=planilla.correctores)


@app.errorhandler(Exception)
def err(error):
    if isinstance(error, HTTPException):
        code = error.code
        message = error.description
    else:
        code = 500
        message = f"{error.__class__.__name__}: {error}"
    logging.exception(error)
    return render_template("result.html", error=message), code


@app.errorhandler(InvalidForm)
def warn_and_render(ex):
    """Error menos verboso que err(), apropiado para excepciones de usuario.
    """
    logging.warn(f"InvalidForm: {ex}")
    return render_template("result.html", error=ex), 422  # Unprocessable Entity


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


def sendmail(emails_alumno, nombres_alumnos, email_docente, tp, padrones, files, body):
    correo = MIMEMultipart()
    correo["From"] = str(cfg.sender)
    correo["To"] = ", ".join(emails_alumno)
    correo["Cc"] = email_docente
    correo["Bcc"] = cfg.sender.email
    correo["Reply-To"] = correo["To"]  # Responder a los alumnos
    subject_text = "{tp} - {padrones} - {nombres}".format(
        tp=tp, padrones=", ".join(padrones), nombres=", ".join(nombres_alumnos))

    if not files:
        # Se asume que es una ausencia, se escribe la justificación dentro
        # de un archivo ZIP para que el corrector automático acepte el mail
        # como una entrega, y registre la justificación en el repositorio.
        rawzip = io.BytesIO()
        with zipfile.ZipFile(rawzip, "w") as zf:
            zf.writestr("ausencia.txt", body + "\n")
        files = [File(rawzip.getvalue(), f"{tp.lower()}_ausencia.zip")]
        subject_text += " (ausencia)"  # Permite al corrector omitir las pruebas.

    correo["Subject"] = subject_text
    correo.attach(MIMEText('\n'.join([tp,
                                      '\n'.join(emails_alumno),
                                      f'\n{body}\n' if body else '',
                                      f'-- \n{cfg.title} - {request.url}']),
                           'plain'))

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

    if not cfg.test:
        creds = get_oauth_credentials()
        xoauth2_tok = f"user={cfg.sender.email}\1" f"auth=Bearer {creds.token}\1\1"
        xoauth2_b64 = base64.b64encode(xoauth2_tok.encode("ascii")).decode("ascii")

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.ehlo()  # Se necesita EHLO de nuevo tras STARTTLS.
        server.docmd("AUTH", "XOAUTH2 " + xoauth2_b64)
        server.send_message(correo)
        server.close()

    task_queue.enqueue(reload_fetchmail, EntregaTask(subject=subject_text))
    return correo


def get_oauth_credentials():
    """Devuelve nuestras credenciales OAuth.
    """
    key = "oauth2_credentials"
    creds = cache.get(key)

    if creds is None:
        app.logger.info("Loading OAuth2 credentials")
    elif not creds.valid:
        app.logger.info("Refreshing OAuth2 credentials")
    else:
        return creds

    # Siempre creamos un nuevo objeto Credentials() para
    # asegurarnos que no llamamos refresh() en uno que se
    # pueda estar usando en otro thread.
    creds = credentials.Credentials(
        token=None,
        client_id=cfg.oauth_client_id,
        client_secret=cfg.oauth_client_secret.get_secret_value(),
        refresh_token=cfg.oauth_refresh_token.get_secret_value(),
        token_uri="https://accounts.google.com/o/oauth2/token")

    creds.refresh(Request())  # FIXME: catch UserAccessTokenError.
    cache.set(key, creds)
    return creds


def get_padrones(planilla, padron_o_grupo):
    if padron_o_grupo not in planilla.correctores:
        raise InvalidForm(f"No se encuentra el alumno o grupo {padron_o_grupo}")

    # Es un grupo.
    if padron_o_grupo in planilla.grupos:
        return list(planilla.grupos[padron_o_grupo])

    # Es un padrón.
    return [padron_o_grupo]


def validate_grupo(planilla, padron_o_grupo, tp):
    if padron_o_grupo in planilla.grupos and cfg.entregas[tp] == Modalidad.INDIVIDUAL:
        raise InvalidForm(f"La entrega {tp} debe ser entregada de forma individual")


def get_emails_alumno(planilla, padrones):
    return [planilla.emails_alumnos[p] for p in padrones]


def get_nombres_alumnos(planilla, padrones):
    return [planilla.nombres_alumnos[p].split(',')[0].title() for p in padrones]


@app.route('/', methods=['POST'])
def post():
    planilla = fetch_planilla()
    try:
        validate_captcha()
        tp = request.form['tp']
        if tp not in cfg.entregas:
            raise InvalidForm(f"La entrega {tp!r} es inválida")

        files = get_files()
        body = request.form['body'] or ''
        tipo = request.form['tipo']

        if tipo == 'entrega' and not files:
            raise InvalidForm('No se ha adjuntado ningún archivo con extensión válida.')
        elif tipo == 'ausencia' and not body:
            raise InvalidForm('No se ha adjuntado una justificación para la ausencia.')

        padron_o_grupo = request.form['identificador']
    except KeyError as ex:
        raise InvalidForm(f"Formulario inválido sin campo {ex.args[0]!r}") from ex

    # Valida si la entrega es individual o grupal de acuerdo a lo ingresado.
    validate_grupo(planilla, padron_o_grupo, tp)

    docente = get_docente(planilla.correctores, padron_o_grupo, planilla, tp)
    email_docente = planilla.emails_docentes[docente] if docente is not None else ""
    padrones = get_padrones(planilla, padron_o_grupo)
    emails_alumno = get_emails_alumno(planilla, padrones)
    nombres_alumnos = get_nombres_alumnos(planilla, padrones)

    email = sendmail(emails_alumno, nombres_alumnos, email_docente,
                     tp.upper(), padrones, files, body)

    return render_template("result.html",
                           tp=tp,
                           email='\n'.join(f"{k}: {v}"
                                           for k, v in email.items())
                                 if cfg.test else None)


def validate_captcha():
    resp = requests.post("https://www.google.com/recaptcha/api/siteverify",
                         data={"secret": cfg.recaptcha_secret.get_secret_value(),
                               "remoteip": request.remote_addr,
                               "response": request.form["g-recaptcha-response"]})

    if resp.ok:
        json = resp.json()
    else:
        resp.raise_for_status()  # Lanza excepción descriptiva para 4xx y 5xx.

    if not json["success"]:
        msg = ", ".join(json.get("error-codes", ["unknown error"]))
        raise InvalidForm(f"Falló la validación del captcha ({msg})")


def get_docente(correctores, padron_o_grupo, planilla, tp):
    if cfg.entregas[tp] == Modalidad.PARCIALITO:
        # XXX "Funciona" porque parse_datos_docentes() suele encontrar celdas vacías.
        return None
    if padron_o_grupo not in correctores:
        raise FailedDependency(
            f"No hay un corrector asignado para el padrón o grupo {padron_o_grupo}")

    if padron_o_grupo in planilla.grupos or cfg.entregas[tp] != Modalidad.GRUPAL:
        return correctores[padron_o_grupo]

    # Es un alumno entregando de forma individual una entrega grupal,
    # por el motivo que fuere.
    # Buscamos su corrector de trabajos grupales.
    padron = padron_o_grupo
    for grupo in planilla.grupos:
        if padron in planilla.grupos[grupo]:
            return correctores[grupo]
