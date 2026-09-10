"""Celery configuration and explicit queue routing for SACAI workloads."""

from celery import Celery
from kombu import Queue

from .config import get_settings


def create_celery_app() -> Celery:
    """Create and configure the Celery application used by API and workers.

    Settings are read from the environment and the returned application routes
    PlanetIR, ISIS3, and maintenance tasks into independently capped queues.
    """

    settings = get_settings()
    app = Celery("sacai", broker=settings.redis_url, backend=settings.result_backend_url)
    app.conf.update(
        task_queues=(
            Queue(settings.planetir_queue),
            Queue(settings.isis_queue),
            Queue(settings.maintenance_queue),
            Queue(settings.notebook_queue),
        ),
        task_routes={
            "sacai.planetir": {"queue": settings.planetir_queue},
            "sacai.isis3": {"queue": settings.isis_queue},
            "sacai.cleanup": {"queue": settings.maintenance_queue},
            "sacai.workflow": {"queue": settings.planetir_queue},
            "sacai.notebook": {"queue": settings.notebook_queue},
        },
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_soft_time_limit=settings.job_soft_time_limit_seconds,
        task_time_limit=settings.job_time_limit_seconds,
        task_annotations={
            "sacai.isis3": {
                "soft_time_limit": settings.isis_soft_time_limit_seconds,
                "time_limit": settings.isis_time_limit_seconds,
            },
            "sacai.workflow": {
                "soft_time_limit": settings.isis_soft_time_limit_seconds,
                "time_limit": settings.isis_time_limit_seconds,
            },
            "sacai.notebook": {
                "soft_time_limit": settings.notebook_soft_time_limit_seconds,
                "time_limit": settings.notebook_time_limit_seconds,
            },
        },
        result_expires=7 * 24 * 3600,
        accept_content=["json"],
        task_serializer="json",
        result_serializer="json",
    )
    return app


celery_app = create_celery_app()
