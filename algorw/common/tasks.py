from pathlib import PurePath
from typing import Dict, List, Optional

from pydantic import BaseModel


class CorrectorTask(BaseModel):
    """Clase que se encola en Redis para procesar por el worker.
    """

    # Por el momento, esta clase solo actúa de wrapper "legacy" para los
    # correos que el sistema de entregas envía a Gmail. Como primer paso
    # en la reescritura, el corrector ahora los obtiene de Redis. Gmail
    # actúa ahora como backup (se le puede aplicar la etiqueta ‘entregas’
    # a un mail para que el corrector lo vuelva a procesar). A futuro, esta
    # clase irá teniendo todos los campos  necesarios para que el corrector
    # no necesite parsear nada.

    tp_id: str
    zipfile: bytes
    legajos: List[str]
    orig_headers: Dict[str, str]
    group_id: Optional[str] = None

    # Ubicación de la entrega en el repo de entregas. A día de hoy el sistema
    # de entregas elige la ruta, y el corrector guarda los archivos. Próximamente,
    # el sistema de entregas guardará los archivos, y el corrector los leerá.
    repo_relpath: PurePath

    class Config:
        arbitrary_types_allowed = True
