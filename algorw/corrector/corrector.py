#!/usr/bin/env python3

"""Script principal del corrector automático de Algoritmos II.

Las entradas al script son:

  - CorrectorTask: un objeto en la cola de mensajes con toda la información
    y contenido de la entrega

  - SKEL_DIR: un directorio con los archivos “base” de cada TP, p. ej. las
    pruebas de la cátedra y los archivos .h

  - WORKER_BIN: el binario que compila la entrega y la corre con Valgrind

El workflow es:

  - de la tarea entrante se tiene el identificador del TP (‘tp0’, ‘pila’,
    etc.) y el ZIP con la entrega

  - se ejecuta el worker, quien recibe por entrada estándar un archivo TAR
    que contiene los archivos de la entrega (subdirectorio "orig") y los
    archivos base (subdirectorio "skel")

Salida:

  - un mensaje al alumno con los resultados.

  - se guarda una copia de los archivos en DATA_DIR/<TP_ID>/<YYYY_CX>/<PADRON>.
"""

import datetime
import email
import email.message
import email.policy
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

from typing import Dict

from dotenv import load_dotenv
from github import GithubException

from config import Settings, load_config

from .. import utils
from ..common.tasks import CorrectorTask
from . import ai_corrector
from .alu_repos import AluRepo


load_dotenv()

ROOT_DIR = pathlib.Path(os.environ["CORRECTOR_ROOT"])
SKEL_DIR = ROOT_DIR / os.environ["CORRECTOR_SKEL"]
DATA_DIR = ROOT_DIR / os.environ["CORRECTOR_TPS"]
WORKER_BIN = ROOT_DIR / os.environ["CORRECTOR_WORKER"]
GITHUB_URL = "https://github.com/" + os.environ["CORRECTOR_GH_REPO"]

AUSENCIA_REGEX = re.compile(r" \(ausencia\)$")
TODO_OK_REGEX = re.compile(r"^Todo OK$", re.M)


# Archivos que no aceptamos en las entregas.
FORBIDDEN_EXTENSIONS = {
    ".o",
    ".class",
    ".jar",
    ".pyc",
}

cfg: Settings = load_config()


class ErrorInterno(Exception):
    """Excepción para cualquier error interno en el programa.
    """


# TODO: eliminar esta clase una vez se valide todo en la página de entregas.
class ErrorAlumno(Exception):
    """Excepción para cualquier error en la entrega.
    """


def corregir_entrega(task: CorrectorTask):
    """Función de corrección principal.

    El flujo de la corrección se corta lanzando excepciones ErrorAlumno.
    """
    try:
        procesar_entrega(task)
    except ErrorAlumno as ex:
        send_reply(task.orig_headers, f"ERROR: {ex}.")
    except ErrorInterno as ex:
        print(ex, file=sys.stderr)


def procesar_entrega(task: CorrectorTask):
    """Recibe el mensaje del alumno y lanza el proceso de corrección.
    """
    subj = task.orig_headers["Subject"]
    tp_id = task.tp_id
    padron = "_".join(task.legajos)
    zip_obj = zipfile.ZipFile(io.BytesIO(task.zipfile))
    skel_dir = SKEL_DIR / tp_id
    moss = Moss(DATA_DIR / task.repo_relpath)
    commit_message = f"New {tp_id} upload from {padron}"

    if AUSENCIA_REGEX.search(subj):
        # No es una entrega real, por tanto no se envía al worker.
        for path, zip_info in zip_walk(zip_obj):
            moss.save_data(path, zip_obj.read(zip_info))
        moss.commit_emoji()
        moss.flush(commit_message, task.orig_headers["Date"])
        send_reply(
            task.orig_headers,
            "Justificación registrada\n\n"
            + "-- \nURL de esta entrega (para uso docente):\n"
            + moss.url(),
        )
        return

    # Lanzar ya el proceso worker para poder pasar su stdin a tarfile.open().
    worker = subprocess.Popen(
        [WORKER_BIN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    tar = tarfile.open(fileobj=worker.stdin, mode="w|", dereference=True)

    # Añadir al archivo TAR la base del TP (skel_dir).
    for entry in os.scandir(skel_dir):
        path = pathlib.PurePath(entry.path)
        rel_path = path.relative_to(skel_dir)
        tar.add(path, "skel" / rel_path)

    # A continuación añadir los archivos de la entrega (ZIP).
    for path, zip_info in zip_walk(zip_obj):
        info = tarfile.TarInfo(("orig" / path).as_posix())
        info.size = zip_info.file_size
        info.mtime = zip_datetime(zip_info).timestamp()
        info.type, info.mode = tarfile.REGTYPE, 0o644

        moss.save_data(path, zip_obj.read(zip_info))
        tar.addfile(info, zip_obj.open(zip_info.filename))

    tar.close()

    stdout, _ = worker.communicate()
    output = stdout.decode("utf-8")
    retcode = worker.wait()

    moss.save_output(f"{subj}\n\n{output}")
    moss.commit_emoji(output)
    moss.flush(commit_message, task.orig_headers["Date"])

    if retcode != 0:
        raise ErrorInterno(output)

    if task.repo_sync is not None:
        dest_repo = task.repo_sync.alu_repo
        auth_token = task.repo_sync.auth_token.get_secret_value()
        try:
            # Sincronizar la entrega con los repositorios individuales.
            alu_repo = AluRepo(dest_repo.full_name, auth_token=auth_token)
            alu_repo.ensure_exists(skel_repo="algorw-alu/algo2_tps")
            alu_repo.sync(moss.location(), tp_id, task.repo_sync.github_id)
        except GithubException as ex:
            print(f"error al sincronizar: {ex}", file=sys.stderr)
        else:
            if TODO_OK_REGEX.search(output):
                # Insertar, por el momento, la URL del repositorio.
                # TODO: insertar URL para un pull request si es el primer Todo OK.
                message = "Esta entrega fue importada a:"
                output = TODO_OK_REGEX.sub(
                    rf"\g<0>\n\n{message}\n{alu_repo.url}/tree/{tp_id}", output
                )

    quote = ai_corrector.vida_corrector(tp_id)
    firma = "URL de esta entrega (para uso docente):\n" + moss.url()
    send_reply(task.orig_headers, f"{quote}{output}\n\n-- \n{firma}")


def is_forbidden(path):
    return (
        path.is_absolute() or ".." in path.parts or path.suffix in FORBIDDEN_EXTENSIONS
    )


def zip_walk(zip_obj, strip_toplevel=True):
    """Itera sobre los archivos de un zip.

    Args:
        - zip_obj: un objeto zipfile.ZipFile abierto en modo lectura
        - skip_toplevel: un booleano que indica si a los nombres de archivos se les
            debe quitar el nombre de directorio común (si lo hubiese)

    Yields:
        - tuplas (nombre_archivo, zipinfo_object).
    """
    zip_files = [pathlib.PurePath(f) for f in zip_obj.namelist()]
    forbidden_files = [f for f in zip_files if is_forbidden(f)]
    all_parents = set()
    common_parent = pathlib.PurePath(".")

    if not zip_files:
        raise ErrorAlumno("archivo ZIP vacío")

    if forbidden_files:
        raise ErrorAlumno(
            "no se permiten archivos con estas extensiones:\n\n  • "
            + "\n  • ".join(f.name for f in forbidden_files)
        )

    for path in zip_files:
        all_parents.update(path.parents)

    if strip_toplevel and len(zip_files) > 1:
        parents = {p.parts[0] for p in zip_files}
        if len(parents) == 1:
            common_parent = parents.pop()

    for fname in zip_files:
        if fname not in all_parents:
            try:
                inf = zip_obj.getinfo(fname.as_posix())
            except KeyError:
                pass
            else:
                yield (fname.relative_to(common_parent), inf)


class Moss:
    """Guarda código fuente del alumno.
    """

    def __init__(self, dest: pathlib.Path):
        self._dest = dest
        self._emoji = None
        shutil.rmtree(self._dest, ignore_errors=True)
        self._dest.mkdir(parents=True)

    def location(self):
        """Directorio donde se guardaron los archivos.
        """
        return self._dest

    def url(self):
        short_rev = "git show -s --pretty=tformat:%h"
        relative_dir = "git rev-parse --show-prefix"
        return subprocess.check_output(
            f'echo "{GITHUB_URL}/tree/$({short_rev})/$({relative_dir})"',
            shell=True,
            encoding="utf-8",
            cwd=self._dest,
        )

    def save_data(self, relpath, contents):
        """Guarda un archivo si es código fuente.

        Devuelve True si se guardó, False si se decidió no guardarlo.
        """
        path = self._dest / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return self._git(["add", relpath]) == 0

    def flush(self, message: str, date: str):  # TODO: pass datetime?
        """Termina de guardar los archivos en el repositorio.
        """
        if self._emoji:
            message = f"{self._emoji} {message}"
        self._git(["add", "--no-ignore-removal", "."])
        self._git(["commit", "-m", message, "--date", date])
        self._git(["push", "--force-with-lease", "origin", ":"])

    def _git(self, args):
        subprocess.call(["git"] + args, cwd=self._dest)

    def save_output(self, output):
        filepath = self._dest / "README.md"
        filepath.write_text(f"```\n{output}```")
        return self._git(["add", filepath]) == 0

    def commit_emoji(self, output=None):
        if output is None:
            self._emoji = ":question:"
        elif "Todo OK" in output.split("\n", 1)[0]:
            self._emoji = ":heavy_check_mark:"
        else:
            self._emoji = ":x:"


def zip_datetime(info):
    """Gets a datetime.datetime from a ZipInfo object.
    """
    return datetime.datetime(*info.date_time)


def send_reply(orig_headers: Dict[str, str], reply_text: str):
    """Envía una cadena de texto como respuesta a un correo recibido.

    Args:
        orig_headers: headers del mensaje original enviado por el sistema de entregas.
        reply_text: texto de la respuesta a enviar, como texto.
    """
    if cfg.test:
        print("ENVIARÍA: {}".format(reply_text), file=sys.stderr)
        return

    creds = utils.get_oauth_credentials(cfg)
    reply = email.message.Message(email.policy.default)
    reply.set_payload(reply_text, "utf-8")

    reply["From"] = cfg.sender.email
    reply["To"] = orig_headers["To"]
    reply["Cc"] = orig_headers.get("Cc", "")
    reply["Subject"] = "Re: " + orig_headers["Subject"]
    reply["Reply-To"] = orig_headers.get("Reply-To", "")
    reply["In-Reply-To"] = orig_headers["Message-ID"]

    return utils.sendmail(reply, creds)
