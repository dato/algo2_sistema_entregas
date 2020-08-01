from redis import Redis
from rq import Queue  # type: ignore

from config import load_config


settings = load_config()
redis_conn = Redis()
task_queue = Queue(settings.job_queue, connection=redis_conn)
