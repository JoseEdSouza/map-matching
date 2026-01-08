import os
from pathlib import Path
import subprocess


COMPOSE_FILE = "docker-compose.yaml"


def _docker_compose(
    *args: str, cwd: Path | None = None, env: dict | None = None
) -> None:
    env = os.environ | (env or {})
    cwd = (cwd or Path.cwd()).resolve()

    subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        cwd=cwd,
        check=True,
        env=env,
    )
