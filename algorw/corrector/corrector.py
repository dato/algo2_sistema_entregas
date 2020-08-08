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


load_dotenv()


ROOT_DIR = pathlib.Path(os.environ["CORRECTOR_ROOT"])
SKEL_DIR = ROOT_DIR / os.environ["CORRECTOR_SKEL"]
DATA_DIR = ROOT_DIR / os.environ["CORRECTOR_TPS"]
WORKER_BIN = ROOT_DIR / os.environ["CORRECTOR_WORKER"]
GITHUB_URL = "https://github.com/" + os.environ["CORRECTOR_GH_REPO"]

AUSENCIA_REGEX = re.compile(r" \(ausencia\)$")
TODO_OK_REGEX = re.compile(r"^Todo OK$", re.M)


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

    moss = Moss(DATA_DIR, tp_id, padron, task.orig_headers["Date"])

    if AUSENCIA_REGEX.search(subj):
        # No es una entrega real, por tanto no se envía al worker.
        for zip_info in zip_obj.infolist():
            if not zip_info.is_dir():
                moss.save_data(zip_info.filename, zip_obj.read(zip_info))
        moss.commit_emoji()
        moss.flush()
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
        tar_path = "skel" / path.relative_to(skel_dir)
        tar.add(entry.path, tar_path.as_posix())

    # A continuación añadir los archivos de la entrega (ZIP).
    for zip_info in zip_obj.infolist():
        if zip_info.is_dir():
            continue
        info = tarfile.TarInfo(f"orig/{zip_info.filename}")
        info.size = zip_info.file_size
        info.mtime = zip_datetime(zip_info).timestamp()
        info.type, info.mode = tarfile.REGTYPE, 0o644

        moss.save_data(zip_info.filename, zip_obj.read(zip_info))
        tar.addfile(info, zip_obj.open(zip_info.filename))

    tar.close()

    stdout, _ = worker.communicate()
    output = stdout.decode("utf-8")
    retcode = worker.wait()

    moss.save_output(f"{subj}\n\n{output}")
    moss.commit_emoji(output)
    moss.flush()

    if retcode != 0:
        raise ErrorInterno(output)

    if TODO_OK_REGEX.search(output) and False:
        try:
            # Sincronizar la entrega con los repositorios individuales.
            alu_repo = AluRepo.from_legajos(padron.split("_"), tp_id)
            alu_repo.ensure_exists(skel_repo="algorw-alu/algo2_tps")
            alu_repo.sync(moss.location(), tp_id)
        except (KeyError, ValueError):
            pass
        except GithubException as ex:
            print(f"error al sincronizar: {ex}", file=sys.stderr)
        else:
            if alu_repo.has_reviewer():
                # Insertar, por el momento, la URL del repositorio.
                # TODO: insertar URL para un pull request si es el primer Todo OK.
                message = "Esta entrega fue importada a:"
                output = TODO_OK_REGEX.sub(
                    rf"\g<0>\n\n{message}\n{alu_repo.url}/tree/{tp_id}", output
                )

    quote = ai_corrector.vida_corrector(tp_id)
    firma = "URL de esta entrega (para uso docente):\n" + moss.url()
    send_reply(task.orig_headers, f"{quote}{output}\n\n-- \n{firma}")


class Moss:
    """Guarda código fuente del alumno.
    """

    def __init__(self, pathobj, tp_id, padron, subj_date):
        self._dest = pathobj / tp_id / cfg.cuatri / padron
        shutil.rmtree(self._dest, ignore_errors=True)
        self._dest.mkdir(parents=True)
        self._date = subj_date  # XXX(dato): verify RFC822
        self._commit_message = f"New {tp_id} upload from {padron}"

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

    def save_data(self, relpath: str, contents: bytes) -> bool:
        """Guarda un archivo si es código fuente.

        Devuelve True si se guardó, False si se decidió no guardarlo.
        """
        path = self._dest / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return self._git(["add", relpath]) == 0

    def flush(self):
        """Termina de guardar los archivos en el repositorio.
        """
        self._git(["add", "--no-ignore-removal", "."])
        self._git(["commit", "-m", self._commit_message, "--date", self._date])
        self._git(["push", "--force-with-lease", "origin", ":"])

    def _git(self, args):
        subprocess.call(["git"] + args, cwd=self._dest)

    def save_output(self, output):
        filepath = self._dest / "README.md"
        filepath.write_text(f"```\n{output}```")
        return self._git(["add", filepath]) == 0

    def commit_emoji(self, output=None):
        if output is None:
            emoji = ":question:"
        elif "Todo OK" in output.split("\n", 1)[0]:
            emoji = ":heavy_check_mark:"
        else:
            emoji = ":x:"
        self._commit_message = f"{emoji} " + self._commit_message


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

    reply["From"] = f"Corrector en beta <{cfg.sender.email}>"
    reply["To"] = cfg.sender.email
    reply["Subject"] = "Re: " + orig_headers["Subject"]
    reply["In-Reply-To"] = orig_headers["Message-ID"]

    return utils.sendmail(reply, creds)
