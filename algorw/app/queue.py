from redis import Redis
from rq import Queue


redis_conn = Redis()
task_queue = Queue(connection=redis_conn)
