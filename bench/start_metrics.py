import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from .compose import _docker_compose

from prometheus_api_client.prometheus_connect import PrometheusConnect

@contextmanager
def track_metrics(
    project_name: str,
    *,
    compose_cwd: Path | None = None,
    startup_sleep_s: float = 5.0,
) -> Generator[PrometheusConnect, None, None]:
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

    conn = PrometheusConnect(url="http://localhost:9090", disable_ssl=True)
    if not conn.check_prometheus_connection():
        raise RuntimeError("Could not connect to Prometheus at http://localhost:9090")
    try:
        yield conn
    finally:
        _docker_compose(
            "-p", project_name, "stop", "cadvisor", "prometheus", cwd=compose_cwd
        )
