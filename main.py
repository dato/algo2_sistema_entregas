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
from typing import List, Optional

import requests

from flask import Flask, render_template, request
from flask_caching import Cache
from google.auth.transport.requests import Request
from google.oauth2 import credentials
from werkzeug.exceptions import FailedDependency, HTTPException
from werkzeug.utils import secure_filename

from algorw.app.queue import task_queue
from algorw.app.tasks import EntregaTask, reload_fetchmail
from algorw.models import Alumne, Docente
from config import Modalidad, Settings, load_config
from planilla import fetch_planilla, timer_planilla


app = Flask("entregas")
app.logger.setLevel(logging.INFO)

cfg: Settings = load_config()
cache: Cache = Cache(config={"CACHE_TYPE": "simple"})

cache.init_app(app)
timer_planilla.start()

File = collections.namedtuple("File", ["content", "filename"])
EXTENSIONES_ACEPTADAS = {"zip", "tar", "gz", "pdf"}


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
    return "." in nombre and nombre.rsplit(".", 1)[1].lower() in EXTENSIONES_ACEPTADAS


def get_files():
    files = request.files.getlist("files")
    return [
        File(content=f.read(), filename=secure_filename(f.filename))
        for f in files
        if f and archivo_es_permitido(f.filename)
    ]


def sendmail(
    tp: str,
    alulist: List[Alumne],
    docente: Optional[Docente],
    files: List[File],
    body: str,
) -> MIMEMultipart:
    emails = sorted(x.correo for x in alulist)
    nombres = sorted(x.nombre.split(",")[0].title() for x in alulist)
    padrones = sorted(x.legajo for x in alulist)
    correo = MIMEMultipart()
    correo["From"] = str(cfg.sender)
    correo["To"] = ", ".join(emails)
    if docente:
        correo["Cc"] = docente.correo
    correo["Bcc"] = cfg.sender.email
    correo["Reply-To"] = correo["To"]  # Responder a los alumnos
    subject_text = "{tp} - {padrones} - {nombres}".format(
        tp=tp, padrones=", ".join(padrones), nombres=", ".join(nombres)
    )

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
    correo.attach(
        MIMEText(
            "\n".join(
                [
                    tp,
                    "\n".join(emails),
                    f"\n{body}\n" if body else "",
                    f"-- \n{cfg.title} - {request.url}",
                ]
            ),
            "plain",
        )
    )

    for f in files:
        # Tomado de: https://docs.python.org/3.5/library/email-examples.html#id2
        # Adivinamos el Content-Type de acuerdo a la extensión del fichero.
        ctype, encoding = mimetypes.guess_type(f.filename)
        if ctype is None or encoding is not None:
            # No pudimos adivinar, así que usamos un Content-Type genérico.
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        if maintype == "text":
            msg = MIMEText(f.content, _subtype=subtype)
        else:
            msg = MIMEBase(maintype, subtype)
            msg.set_payload(f.content)
            # Codificamos el payload en base 64.
            encoders.encode_base64(msg)
        # Set the filename parameter
        msg.add_header("Content-Disposition", "attachment", filename=f.filename)
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
        token_uri="https://accounts.google.com/o/oauth2/token",
    )

    creds.refresh(Request())  # FIXME: catch UserAccessTokenError.
    cache.set(key, creds)
    return creds


@app.route("/", methods=["POST"])
def post():
    # Leer valores del formulario.
    try:
        validate_captcha()
        tp = request.form["tp"]
        files = get_files()
        body = request.form["body"] or ""
        tipo = request.form["tipo"]
        identificador = request.form["identificador"]
    except KeyError as ex:
        raise InvalidForm(f"Formulario inválido sin campo {ex.args[0]!r}") from ex

    # Obtener alumnes que realizan la entrega.
    planilla = fetch_planilla()
    try:
        alulist = planilla.get_alulist(identificador)
    except KeyError as ex:
        raise InvalidForm(f"No se encuentra grupo o legajo {identificador!r}") from ex

    # Validar varios aspectos de la entrega.
    if tp not in cfg.entregas:
        raise InvalidForm(f"La entrega {tp!r} es inválida")
    elif len(alulist) > 1 and cfg.entregas[tp] != Modalidad.GRUPAL:
        raise ValueError(f"La entrega {tp} debe ser individual")
    elif tipo == "entrega" and not files:
        raise InvalidForm("No se ha adjuntado ningún archivo con extensión válida.")
    elif tipo == "ausencia" and not body:
        raise InvalidForm("No se ha adjuntado una justificación para la ausencia.")

    # Encontrar a le docente correspondiente.
    if cfg.entregas[tp] == Modalidad.INDIVIDUAL:
        docente = alulist[0].ayudante_indiv
    elif cfg.entregas[tp] == Modalidad.GRUPAL:
        docente = alulist[0].ayudante_grupal
    else:
        docente = None

    if not docente and cfg.entregas[tp] != Modalidad.PARCIALITO:
        legajos = ", ".join(x.legajo for x in alulist)
        raise FailedDependency(f"No hay corrector para la entrega {tp} de {legajos}")

    email = sendmail(tp.upper(), alulist, docente, files, body)

    return render_template("result.html",
                           tp=tp,
                           email="\n".join(f"{k}: {v}"
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
