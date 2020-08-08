import collections
import io
import logging
import zipfile

from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import PurePath
from typing import List, Optional, Tuple

import requests

from flask import Flask, render_template, request
from flask_caching import Cache  # type: ignore
from werkzeug.exceptions import FailedDependency, HTTPException
from werkzeug.utils import secure_filename

from algorw import utils
from algorw.app.queue import task_queue
from algorw.app.tasks import corregir_entrega  # TODO: importar from corrector.
from algorw.common.tasks import CorrectorTask
from algorw.models import Alumne, Docente
from config import Modalidad, Settings, load_config
from planilla import fetch_planilla, timer_planilla


app = Flask("entregas")
app.logger.setLevel(logging.INFO)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MiB

cfg: Settings = load_config()
cache: Cache = Cache(config={"CACHE_TYPE": "simple"})

cache.init_app(app)
timer_planilla.start()

File = collections.namedtuple("File", ["content", "filename"])
EXTENSIONES_ACEPTADAS = {"zip"}  # TODO: volver a aceptar archivos sueltos.

# Archivos que no aceptamos en las entregas.
FORBIDDEN_EXTENSIONS = {
    ".o",
    ".class",
    ".jar",
    ".pyc",
}


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


def make_headers(
    tp: str, alulist: List[Alumne], docente: Optional[Docente]
) -> MIMEMultipart:
    """Prepara el correo a enviar, con las cabeceras solamente.
    """
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
        form_body = request.form["body"] or ""
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
    elif tipo == "ausencia" and not form_body:
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

    # Una vez validado todo, empezar a componer el mensaje, y preparar el ZIP para
    # el corrector automático.
    email = make_headers(tp.upper(), alulist, docente)
    legajos = utils.sorted_strnum([x.legajo for x in alulist])
    direcciones = "\n".join(sorted(x.correo for x in alulist))

    if tipo == "ausencia":
        rawzip = io.BytesIO()
        email.replace_header("Subject", email["Subject"] + " (ausencia)")
        with zipfile.ZipFile(rawzip, "w") as zf:
            zf.writestr("ausencia.txt", form_body + "\n")
        entrega = File(rawzip.getvalue(), f"{tp}_ausencia.zip")
        omitidos = []
    else:
        entrega, omitidos = zipfile_for_entrega(files)

    # Componer elcuerpo del mensaje
    # TODO: Usar un template de Jinja.
    body_lines = [tp.upper(), direcciones, f"\n{form_body}" if form_body else ""]

    if omitidos:
        body_lines.extend(
            [
                "",
                "AVISO: Los siguientes archivos fueron omitidos\n\n  • "
                + "\n  • ".join(omitidos),
            ]
        )

    body_lines.append(f"\n-- \n{cfg.title} – {request.url}")
    email.attach(MIMEText("\n".join(body_lines)))

    # Incluir el único archivo ZIP (quizás modificado).
    part = MIMEBase("application", "zip")
    part.set_payload(entrega.content)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=entrega.filename)
    email.attach(part)

    # Enviar la tarea a la cola de trabajos.
    task = CorrectorTask(
        tp_id=tp.lower(),
        legajos=legajos,
        zipfile=entrega.content,
        orig_headers=dict(email.items()),
    )

    task_queue.enqueue(corregir_entrega, task)

    if not cfg.test:
        # TODO: en lugar de enviar un mail, que es lento, hacer un commit en la
        # copia local de algo2_entregas.
        utils.sendmail(email, oauth_credentials())

    return render_template(
        "result.html",
        tp=tp,
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


def zipfile_for_entrega(files: List[File]) -> Tuple[File, List[str]]:
    """Genera un archivo ZIP para enviar al corrector.

    Por el momento, se asume que todas las entregas son un único ZIP, y esta
    función simplemente lo valida, creando uno nuevo (filtrado) si es necesario.
    Más adelante, si el sistema de entregas vuelve a aceptar archivos individuales,
    la función simplemente los empacará en un ZIP para el corrector.

    El corrector espera recibir archivos validados. En particular, espera que todos
    los archivos se encuentren en el top-level del ZIP. Por tanto, esta función
    generará un nuevo archivo si ocurre que:

      - el contenido está en un directorio top-level en el zip (‘Abb/abb.c’)
      - existen archivos con extensiones no permitidas (se filtran)
      - existen archivos ocultos, por ejemplo ‘.git’ o ‘.vscode’

    Devuelve una tupla con el ZIP a enviar al corrector, y la lista de archivos
    omitidos, si los hubo.
    """
    assert EXTENSIONES_ACEPTADAS == {"zip"}

    if len(files) != 1:
        nombres = ", ".join(f.filename for f in files)
        raise InvalidForm(
            f"Se esperaba un único archivo ZIP en la entrega (se encontró: {nombres})"
        )

    i = 0
    zipbytes = io.BytesIO(files[0].content)
    zipbytes.name = files[0].filename  # To please the exquisitely delicate zipfile.Path
    zip_root = PurePath(zipbytes.name)
    toplevel = PurePath(".")
    orig_zip = zipfile.ZipFile(zipbytes)

    pending = list(zipfile.Path(orig_zip).iterdir())
    keep_paths = []
    rejections = []

    # Strip toplevel.
    while len(pending) == 1 and (root := pending[0]).is_dir():
        pending = list(root.iterdir())
        toplevel = PurePath(str(root)).relative_to(zip_root)

    if not pending:
        raise InvalidForm("¿Archivo ZIP vacío?")

    while i < len(pending):
        zip_path = pending[i]
        rel_path = PurePath(str(zip_path)).relative_to(zip_root)
        if rel_path.name.startswith("."):
            rejections.append(rel_path.as_posix())
        elif rel_path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            rejections.append(rel_path.as_posix())
        elif zip_path.is_file():
            keep_paths.append((rel_path, zip_path.read_bytes()))
        else:
            pending.extend(zip_path.iterdir())
        i += 1

    if toplevel != PurePath(".") or rejections:
        zipbytes = io.BytesIO()

        with zipfile.ZipFile(zipbytes, "w") as zf:
            for path, contents in keep_paths:
                # Preserve original ZipInfo, but with updated path.
                zip_info = orig_zip.getinfo(path.as_posix())
                zip_info.filename = path.relative_to(toplevel).as_posix()
                zf.writestr(zip_info, contents)

    return File(zipbytes.getvalue(), files[0].filename), rejections
