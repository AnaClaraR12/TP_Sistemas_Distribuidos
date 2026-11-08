"""Gunicorn: workers = 2*CPU+1 (sobrescreva com GUNICORN_WORKERS)."""

import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8005')}"
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = 30
graceful_timeout = 20
keepalive = 5
accesslog = "-"
errorlog = "-"
max_requests = 2000
max_requests_jitter = 200
