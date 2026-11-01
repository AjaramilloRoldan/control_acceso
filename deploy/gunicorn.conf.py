bind = '127.0.0.1:8000'
# Un solo proceso: el rate limiting cuenta en memoria y varios workers lo dividirían
workers = 1
worker_class = 'gthread'
threads = 8
timeout = 60
accesslog = '-'
errorlog = '-'
