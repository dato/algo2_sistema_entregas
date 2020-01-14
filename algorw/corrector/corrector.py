#!/usr/bin/env python3

"""Script principal del corrector automático de Algoritmos II.

Las entradas al script son:

  - stdin: mensaje de correo enviado por el alumno

  - SKEL_DIR: un directorio con los archivos “base” de cada TP, p. ej. las
    pruebas de la cátedra y los archivos .h

  - WORKER_BIN: el binario que compila la entrega y la corre con Valgrind

El workflow es:

  - del mensaje entrante se detecta el identificador del TP (‘tp0’, ‘pila’,
    etc.) y el ZIP con la entrega

  - se ejecuta el worker, quien recibe por entrada estándar un archivo TAR
    que contiene los archivos de la entrega (subdirectorio "orig") y los
    archivos base (subdirectorio "skel")

Salida:

  - un mensaje al alumno con los resultados.

  - se guarda una copia de los archivos en DATA_DIR/<TP_ID>/<YYYY_CX>/<PADRON>.
"""

import ai_corrector
import datetime
import email
import email.message
import email.policy
import email.utils
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

from github import GithubException

from alu_repos import AluRepo
from config import Settings, load_config

from .. import utils


ROOT_DIR = pathlib.Path(os.environ["CORRECTOR_ROOT"])
SKEL_DIR = ROOT_DIR / os.environ["CORRECTOR_SKEL"]
DATA_DIR = ROOT_DIR / os.environ["CORRECTOR_TPS"]
WORKER_BIN = ROOT_DIR / os.environ["CORRECTOR_WORKER"]
GITHUB_URL = "https://github.com/" + os.environ["CORRECTOR_GH_REPO"]

MAX_ZIP_SIZE = 1024 * 1024  # 1 MiB
PADRON_REGEX = re.compile(r"\b(SP\d+|CBC\d+|\d{5,})\b")
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


class ErrorAlumno(Exception):
    """Excepción para cualquier error en la entrega.
    """


def main():
    """Función principal.

    El flujo de la corrección se corta lanzando excepciones ErrorAlumno.
    """
    os.umask(0o027)

    msg = email.message_from_binary_file(sys.stdin.buffer, policy=email.policy.default)
    try:
        procesar_entrega(msg)
    except ErrorAlumno as ex:
        send_reply(msg, "ERROR: {}.".format(ex))
    except ErrorInterno as ex:
        print(ex, file=sys.stderr)
        sys.exit(1)  # Ensure message will not be deleted by fetchmail.


def procesar_entrega(msg):
    """Recibe el mensaje del alumno y lanza el proceso de corrección.
    """
    _, addr_from = email.utils.parseaddr(msg["From"])

    # Ignoramos los mails que vienen del sistema de entregas.
    if "Entregas Algoritmos 2" not in msg["From"]:
        sys.stderr.write("Ignorando email de {}\n".format(addr_from))
        return

    subj = msg["Subject"]
    tp_id = guess_tp(subj)
    padron = get_padron_str(subj)
    zip_obj = find_zip(msg)
    skel_dir = SKEL_DIR / tp_id

    moss = Moss(DATA_DIR, tp_id, padron, msg["Date"])

    if AUSENCIA_REGEX.search(subj):
        # No es una entrega real, por tanto no se envía al worker.
        for path, zip_info in zip_walk(zip_obj):
            moss.save_data(path, zip_obj.read(zip_info))
        moss.commit_emoji()
        moss.flush()
        send_reply(
            msg,
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
    moss.flush()

    if retcode != 0:
        raise ErrorInterno(output)

    if TODO_OK_REGEX.search(output):
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
    send_reply(msg, f"{quote}{output}\n\n-- \n{firma}")


def guess_tp(subject):
    """Devuelve el identificador del TP de la entrega.

    Por ejemplo, ‘tp0’ o ‘pila’.
    """
    subj_words = [w.lower() for w in re.split(r"[^_\w]+", subject)]
    candidates = {p.name.lower(): p.name for p in SKEL_DIR.iterdir()}

    for word in subj_words:
        if word in candidates:
            return candidates[word]

    raise ErrorAlumno("no se encontró nombre del TP en el asunto")


def get_padron_str(subject):
    """Devuelve una cadena con el padrón, o padrones, de una entrega.

    En el caso de entregas conjuntas, se devuelve PADRÓN1_PADRÓN2, con
    PADRÓN1 < PADRÓN2.
    """
    subject = subject.replace(".", "")
    matches = PADRON_REGEX.findall(subject)

    if matches:
        # Los padrones suelen ser numéricos, pero técnicamnete nada obliga
        # a ello. Para ordenar ascendentemente cadenas que son casi siempre
        # números, podemos usar "0>{maxlen}" como key, que añade ceros a la
        # izquierda para dar a todos el mismo ancho.
        maxlen = max(len(x) for x in matches)
        matches = sorted(matches, key=lambda s: f"{s:0>{maxlen}}")
        return "_".join(matches)

    raise ErrorAlumno("no se encontró número de legajo en el asunto")


def find_zip(msg):
    """Busca un adjunto .zip en un mensaje y lo devuelve.

    Args:
        - msg: un objeto email.message.Message.

    Returns:
        - un objeto zipfile.ZipFile.
    """
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue  # Multipart es una enclosure.

        filename = part.get_filename() or ""
        content_type = part.get_content_type()

        if filename.lower().endswith(".zip") or content_type == "application/zip":
            zipbytes = part.get_payload(decode=True)
            if len(zipbytes) > MAX_ZIP_SIZE:
                raise ErrorAlumno(
                    "archivo ZIP demasiado grande ({} bytes)".format(len(zipbytes))
                )
            try:
                return zipfile.ZipFile(io.BytesIO(zipbytes))
            except zipfile.BadZipFile as ex:
                raise ErrorAlumno(
                    "no se pudo abrir el archivo {} ({} bytes): {}".format(
                        filename, len(zipbytes), ex
                    )
                )

    raise ErrorAlumno("no se encontró un archivo ZIP en el mensaje")


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

    def save_data(self, relpath, contents):
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


def send_reply(orig_msg, reply_text):
    """Envía una cadena de texto como respuesta a un correo recibido.
    """
    if cfg.test:
        print("ENVIARÍA: {}".format(reply_text), file=sys.stderr)
        return

    creds = utils.get_oauth_credentials(cfg)
    reply = email.message.Message(email.policy.default)
    reply.set_payload(reply_text, "utf-8")

    reply["From"] = cfg.sender.email
    reply["To"] = orig_msg["To"]
    reply["Cc"] = orig_msg.get("Cc", "")
    reply["Subject"] = "Re: " + orig_msg["Subject"]
    reply["Reply-To"] = orig_msg.get("Reply-To", "")
    reply["In-Reply-To"] = orig_msg["Message-ID"]

    return utils.sendmail(reply, creds)


if __name__ == "__main__":
    sys.exit(main())

# vi:et:sw=2
