import json
import time

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .compose import _docker_compose


def _ensure_list(x: str | list[str]) -> list[str]:
    if isinstance(x, str):
        xs = [x]
    else:
        xs = x
    return [s.strip() for s in xs if s.strip()]


@contextmanager
def launch_service(
    service_name: str | list[str],
    project_name: str,
    *,
    dataset_id: str,
    mode: str,
    experiment_id: str | None = None,
    config: dict | None = None,
    matcher_name: str | None = None,
    compose_cwd: Path | None = None,
    startup_sleep_s: float = 2.0,
) -> Iterator[str]:
    """
    Launch one or more matcher services via docker compose, passing env vars used by labels.

    Returns (yields) the experiment_id used for this run.
    """
    services = _ensure_list(service_name)
    if not services:
        raise ValueError("service_name must not be empty")

    exp_id = experiment_id or uuid4().hex

    env: dict[str, str] = {
        "DATASET_ID": dataset_id,
        "MODE": mode,
        "EXPERIMENT_ID": exp_id,
        "CONFIG": "None",
    }

    if matcher_name is not None:
        env["MATCHER_NAME"] = matcher_name

    if config is not None:
        env["CONFIG"] = json.dumps(config, separators=(",", ":"))

    _docker_compose(
        "-p",
        project_name,
        "up",
        "-d",
        "--force-recreate",
        "--wait",
        *services,
        cwd=compose_cwd,
        env=env,
    )

    # Give the service a moment (cheap & pragmatic)
    if startup_sleep_s > 0:
        time.sleep(startup_sleep_s)

    try:
        yield exp_id
    finally:
        _docker_compose("-p", project_name, "stop", *services, cwd=compose_cwd)
