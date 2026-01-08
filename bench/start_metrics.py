import time
from contextlib import contextmanager
from pathlib import Path
from .compose import _docker_compose


@contextmanager
def track_metrics(
    project_name: str,
    *,
    compose_cwd: Path | None = None,
    startup_sleep_s: float = 3.0,
):
    _docker_compose(
        "-p",
        project_name,
        "up",
        "-d",
        "--force-recreate",
        "cadvisor",
        "prometheus",
        cwd=compose_cwd,
    )
    if startup_sleep_s > 0:
        time.sleep(startup_sleep_s)

    try:
        yield
    finally:
        _docker_compose(
            "-p", project_name, "stop", "cadvisor", "prometheus", cwd=compose_cwd
        )
