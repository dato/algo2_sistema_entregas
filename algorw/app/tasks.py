import os
import signal
import sys

from pydantic import BaseModel


class EntregaTask(BaseModel):
    """Clase que se encola en Redis para procesar por el worker.
    """

    # Por el momento, esta clase solo actúa para indicarle a fetchmail que
    # debería comprobar el correo (porque IMAP IDLE últimamente cuelga, ver
    # algoritmos-rw/corrector#51). A futuro, esta clase tendrá todos los campos
    # necesarios, y Gmail será solamente backup.
    subject: str


def reload_fetchmail(task: EntregaTask):
    try:
        with open(os.path.expanduser("~/.fetchmail.pid")) as pidfile:
            pid = int(pidfile.readline())
            os.kill(pid, signal.SIGUSR1)
    except (IOError, OSError, ValueError) as ex:
        print(f"could not reload fetchmail: {ex}", file=sys.stderr)
