from pydantic import BaseModel


class CorrectorTask(BaseModel):
    """Clase que se encola en Redis para procesar por el worker.
    """

    # Por el momento, esta clase solo actúa para indicarle a fetchmail que
    # debería comprobar el correo (porque IMAP IDLE últimamente cuelga, ver
    # algoritmos-rw/corrector#51). A futuro, esta clase tendrá todos los campos
    # necesarios, y Gmail será solamente backup.
    subject: str
