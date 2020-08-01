import os
import signal
import sys

from ..common.tasks import CorrectorTask


def reload_fetchmail(task: CorrectorTask):
    try:
        with open(os.path.expanduser("~/.fetchmail.pid")) as pidfile:
            pid = int(pidfile.readline())
            os.kill(pid, signal.SIGUSR1)
    except (IOError, OSError, ValueError) as ex:
        print(f"could not reload fetchmail: {ex}", file=sys.stderr)
