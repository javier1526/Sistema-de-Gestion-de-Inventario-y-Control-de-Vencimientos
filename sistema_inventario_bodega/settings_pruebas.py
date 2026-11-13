"""Pruebas aisladas en memoria: no conectan con la base local de bodega."""

import os

# Es un valor ficticio exclusivo del proceso de pruebas.
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ.setdefault('DJANGO_SECRET_KEY', 'clave-ficticia-solo-para-pruebas-aisladas')

from .settings import *  # noqa: E402,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1', '[::1]']

