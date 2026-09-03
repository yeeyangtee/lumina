"""Gunicorn defaults tuned for a small LAN gallery and slow SMB reads."""

import os


bind = os.environ.get('NFS_VIEWER_BIND', '0.0.0.0:5050')
workers = int(os.environ.get('NFS_VIEWER_WORKERS', '2'))
threads = int(os.environ.get('NFS_VIEWER_THREADS', '4'))
worker_class = 'gthread'
timeout = int(os.environ.get('NFS_VIEWER_TIMEOUT', '120'))
keepalive = 5
accesslog = '-'
errorlog = '-'
capture_output = True
