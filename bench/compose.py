import logging
import os
from pathlib import Path
import subprocess
import shlex

COMPOSE_FILE = "docker-compose.yaml"


def _docker_compose(
    *args: str, cwd: Path | None = None, env: dict | None = None, timeout_s: int = 120
) -> None:
    logger = logging.getLogger(__name__)
    env = os.environ | (env or {})
    cwd = (cwd or Path.cwd()).resolve()

    cmd = ["docker", "compose", "-f", COMPOSE_FILE, *args]
    logger.info(f"[compose] cwd={cwd}")
    logger.info(f"[compose] $ {shlex.join(cmd)}")

    try:
        out = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            check=True,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if out.stdout:
            logger.info(out.stdout)
    except subprocess.TimeoutExpired as e:
        logger.error(f"[compose] TIMEOUT after {timeout_s}s: {shlex.join(cmd)}")
        if e.stdout:
            logger.error(f"[compose] partial output:\n{e.stdout}")

        try:
            ps = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    COMPOSE_FILE,
                    *args[:2],
                    "ps",
                ],
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            logger.debug(f"[compose] debug ps:\n{ps.stdout}")
        except Exception as _:
            pass

    except subprocess.CalledProcessError as e:
        logger.error(f"[compose] FAILED: {shlex.join(cmd)}")
        if e.stdout:
            logger.error(e.stdout)
        raise
