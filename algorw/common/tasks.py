from pathlib import PurePath
from typing import Dict, List, Optional

from pydantic import BaseModel, SecretStr

from .models import Repo


class RepoSync(BaseModel):
    """Clase que describe la sincronización de una entrega.
    """

    # El repositorio donde se sincroniza la entrega.
    alu_repo: Repo

    # El nombre de cuenta de Github que realizó la entrega.
    github_id: str

    # El token para autenticar la instalación de Github.
    auth_token: SecretStr

    class Config:
        arbitrary_types_allowed = True


class CorrectorTask(BaseModel):
    """Clase que se encola en Redis para procesar por el corrector.

    La cola de rq es ahora la principal comunicación entre el sistema de
    entregas y el corrector. Gmail actua ahora como backup, o “corrector
    legacy” (procesa y corrige las entregas, pero no envía el correo de
    respuesta a les alumnes; este correo queda solo en la casilla).
    """

    # "tp_id es el ID del TP; suele ir en minúsculas, y se usa como nombre
    # de directorio en skel.
    tp_id: str
    zipfile: bytes
    legajos: List[str]

    # "orig_headers" son los headers del correo original que envió el sistema
    # de entregas. TODO: eliminar de corrector.py toda la lógica que trata la
    # entrada como un correo.
    orig_headers: Dict[str, str]

    # Ubicación de la entrega en el repo de entregas. A día de hoy el sistema
    # de entregas elige la ruta, y el corrector guarda los archivos. Próximamente,
    # el sistema de entregas guardará los archivos, y el corrector los leerá.
    repo_relpath: PurePath

    # Sincronización a repositorios de alumnes.
    repo_sync: Optional[RepoSync] = None

    class Config:
        arbitrary_types_allowed = True
