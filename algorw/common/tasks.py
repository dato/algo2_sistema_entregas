from typing import List, Optional

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
    mensaje: bytes
    legajos: List[str]
    group_id: Optional[str] = None
