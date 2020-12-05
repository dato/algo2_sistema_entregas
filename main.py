import collections
import io
import logging
import pathlib
import zipfile

from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import List, Optional

import github
import requests

from flask import Flask, render_template, request
from flask_caching import Cache  # type: ignore
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from algorw import utils
from algorw.app.queue import task_queue
from algorw.common.tasks import CorrectorTask, RepoSync
from algorw.corrector import corregir_entrega
from algorw.models import Alumne, Docente
from config import Modalidad, Settings, load_config
from planilla import fetch_planilla, timer_planilla


app = Flask("entregas")
app.logger.setLevel(logging.INFO)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MiB

cfg: Settings = load_config()
gh: github.GithubIntegration = github.GithubIntegration(
    cfg.github_app_id, open(cfg.github_app_keyfile).read()
)
cache: Cache = Cache(config={"CACHE_TYPE": "simple"})

cache.init_app(app)
timer_planilla.start()

File = collections.namedtuple("File", ["content", "filename"])
EXTENSIONES_ACEPTADAS = {"zip"}  # TODO: volver a aceptar archivos sueltos.


class InvalidForm(Exception):
    """Excepción para cualquier error en el form.
    """


@app.context_processor
def inject_cfg():
    return {"cfg": cfg}


@app.route("/", methods=["GET"])
def get():
    planilla = fetch_planilla()
    return render_template(
        "index.html", entregas=cfg.entregas, correctores=planilla.correctores
    )


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


def make_email(
    tp: str, alulist: List[Alumne], docente: Optional[Docente], body: str,
) -> MIMEMultipart:
    """Prepara el correo a enviar, con cabeceras y cuerpo, sin adjunto.
    """
    body_n = f"\n{body}\n" if body else ""
    emails = sorted(x.correo for x in alulist)
    nombres = sorted(x.nombre.split(",")[0].title() for x in alulist)
    padrones = utils.sorted_strnum([x.legajo for x in alulist])
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
    correo["Date"] = formatdate()
    correo["Subject"] = subject_text
    correo["Message-ID"] = make_msgid("entregas", "algorw.turing.pink")
    direcciones = "\n".join(emails)
    correo.attach(
        MIMEText(
            f"{tp}\n{direcciones}\n{body_n}\n-- \n{cfg.title} – {request.url}", "plain",
        )
    )
    return correo


def oauth_credentials():
    """Caché de las credenciales OAuth.
    """
    key = "oauth2_credentials"
    creds = cache.get(key)

    if creds is None:
        app.logger.info("Loading OAuth2 credentials")
    elif not creds.valid:
        app.logger.info("Refreshing OAuth2 credentials")
    else:
        return creds

    creds = utils.get_oauth_credentials(cfg)
    cache.set(key, creds)
    return creds


@app.route("/", methods=["POST"])
def post():
    # Leer valores del formulario.
    try:
        if not cfg.test:
            validate_captcha()
        tp = request.form["tp"]
        files = get_files()
        body = request.form["body"] or ""
        tipo = request.form["tipo"]
        legajo = request.form["legajo"]
        modalidad = Modalidad(request.form.get("modalidad", "i"))
    except KeyError as ex:
        raise InvalidForm(f"Formulario inválido sin campo {ex.args[0]!r}") from ex
    except ValueError as ex:
        raise InvalidForm(f"Formulario con campo inválido: {ex.args[0]}") from ex

    # Obtener alumnes que realizan la entrega.
    planilla = fetch_planilla()
    try:
        alumne = planilla.get_alu(legajo)
    except KeyError as ex:
        raise InvalidForm(f"No se encuentra el legajo {legajo!r}") from ex

    # Validar varios aspectos de la entrega.
    if tp not in cfg.entregas:
        raise InvalidForm(f"La entrega {tp!r} es inválida")
    elif modalidad == Modalidad.GRUPAL and cfg.entregas[tp] != Modalidad.GRUPAL:
        raise ValueError(f"La entrega {tp} debe ser individual")
    elif tipo == "entrega" and not files:
        raise InvalidForm("No se ha adjuntado ningún archivo con extensión válida.")
    elif tipo == "ausencia" and not body:
        raise InvalidForm("No se ha adjuntado una justificación para la ausencia.")

    # Encontrar a le docente correspondiente.
    docente = None
    warning = None

    if cfg.entregas[tp] == Modalidad.INDIVIDUAL:
        docente = alumne.ayudante_indiv
    elif cfg.entregas[tp] == Modalidad.GRUPAL:
        docente = alumne.ayudante_grupal

    if not docente and cfg.entregas[tp] != Modalidad.PARCIALITO:
        warning = "aún no se asignó docente para corregir esta entrega"

    # Encontrar la lista de alumnes a quienes pertenece la entrega, y su repo asociado.
    alulist = [alumne]
    alu_repo = None
    if modalidad == Modalidad.GRUPAL and alumne.grupo:
        try:
            alulist = planilla.get_alulist(alumne.grupo)
            alu_repo = planilla.repo_grupal(alumne.grupo)
        except KeyError:
            logging.warn(f"KeyError in get_alulist({alumne.group})")
    else:
        alu_repo = alumne.repo_indiv

    email = make_email(tp.upper(), alulist, docente, body)
    legajos = utils.sorted_strnum([x.legajo for x in alulist])

    if tipo == "ausencia":
        rawzip = io.BytesIO()
        email.replace_header("Subject", email["Subject"] + " (ausencia)")
        with zipfile.ZipFile(rawzip, "w") as zf:
            zf.writestr("ausencia.txt", body + "\n")
        entrega = File(rawzip.getvalue(), f"{tp}_ausencia.zip")
    else:
        entrega = zipfile_for_entrega(files)

    # Incluir el único archivo ZIP.
    part = MIMEBase("application", "zip")
    part.set_payload(entrega.content)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=entrega.filename)
    email.attach(part)

    # Determinar la ruta en algo2_entregas (se hace caso especial para los parcialitos).
    tp_id = tp.lower()

    if cfg.entregas[tp] != Modalidad.PARCIALITO:
        # Ruta tradicional: pila/2020_1/54321
        relpath_base = pathlib.PurePath(tp_id) / cfg.cuatri
    else:
        # Ruta específica para parcialitos: parcialitos/2020_1/parcialito1_r2/54321
        relpath_base = pathlib.PurePath("parcialitos") / cfg.cuatri / tp_id

    if alu_repo is not None:
        auth_token = cfg.github_token
        installation = gh.get_installation(alu_repo.owner, alu_repo.name)
        try:
            auth = gh.get_access_token(installation.id)
            auth_token = auth.token
        except github.UnknownObjectException:
            # Probablemente el repositorio no existe todavía. Usamos el antiguo token
            # hasta que resolvamos
            # https://github.com/PyGithub/PyGithub/issues/1730#issuecomment-739111283.
            pass
        repo_sync = RepoSync(
            alu_repo=alu_repo,
            auth_token=auth_token,
            github_id=alumne.github or "wachenbot",
        )
    else:
        repo_sync = None
    task = CorrectorTask(
        tp_id=tp_id,
        legajos=legajos,
        zipfile=entrega.content,
        repo_sync=repo_sync,
        orig_headers=dict(email.items()),
        repo_relpath=relpath_base / "_".join(legajos),
    )

    task_queue.enqueue(corregir_entrega, task)

    if not cfg.test:
        # TODO: en lugar de enviar un mail, que es lento, hacer un commit en la
        # copia local de algo2_entregas.
        utils.sendmail(email, oauth_credentials())

    return render_template(
        "result.html",
        tp=tp,
        warning=warning,
        email="\n".join(f"{k}: {v}" for k, v in email.items()) if cfg.test else None,
    )


def validate_captcha():
    resp = requests.post(
        "https://www.google.com/recaptcha/api/siteverify",
        data={
            "secret": cfg.recaptcha_secret.get_secret_value(),
            "remoteip": request.remote_addr,
            "response": request.form["g-recaptcha-response"],
        },
    )

    if resp.ok:
        json = resp.json()
    else:
        resp.raise_for_status()  # Lanza excepción descriptiva para 4xx y 5xx.

    if not json["success"]:
        msg = ", ".join(json.get("error-codes", ["unknown error"]))
        raise InvalidForm(f"Falló la validación del captcha ({msg})")


def zipfile_for_entrega(files: List[File]) -> File:
    """Genera un archivo ZIP para enviar al corrector.

    Por el momento, se reenvía tal cual el archivo recibido (debe haber solo uno).
    """
    # TODO: realizar toda la validación aquí, y no en zip_walk().
    # TODO: si el archivo tiene subdirectorios o archivos no permitidos, crear un
    # nuevo ZIP, y enviar ese al corrector.
    assert EXTENSIONES_ACEPTADAS == {"zip"}

    if len(files) != 1:
        nombres = ", ".join(f.filename for f in files)
        raise InvalidForm(
            f"Se esperaba un único archivo ZIP en la entrega (se encontró: {nombres})"
        )

    return files[0]
