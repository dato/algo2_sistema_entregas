import os
import signal
import sys

from ..common.tasks import CorrectorTask


def corregir_entrega(task: CorrectorTask):
    reload_fetchmail()


def reload_fetchmail():
    try:
        with open(os.path.expanduser("~/.fetchmail.pid")) as pidfile:
            pid = int(pidfile.readline())
            os.kill(pid, signal.SIGUSR1)
    except (IOError, OSError, ValueError) as ex:
        print(f"could not reload fetchmail: {ex}", file=sys.stderr)
