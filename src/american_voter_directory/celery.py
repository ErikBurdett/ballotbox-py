import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "american_voter_directory.settings")

app = Celery("american_voter_directory")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

