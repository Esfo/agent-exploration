"""Build the hardened multi-language sandbox image (``--initiate``).

The runtime confines execution with the container flags in
:mod:`swarm.sandbox.docker_backend` (``--network none``, ``--cap-drop ALL``,
``--security-opt no-new-privileges``, read-only root + tmpfs, memory/cpu/pids
limits). This module pre-builds an image that has the language toolchains the
coding/testing/optimization/math agents may need, so first execution is fast and
offline. A non-root ``agent`` user is created in the image as defence in depth.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

DEFAULT_TAG = "recursive-local-swarm-sandbox:latest"

DOCKERFILE = r"""
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive

# Interpreters, compilers and package managers for the languages the sandbox
# runner knows how to execute.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 python3-pip python3-venv \
        nodejs npm \
        ruby \
        golang \
        gcc g++ make \
        default-jdk \
        php-cli \
        perl \
        lua5.4 \
        r-base-core \
        sqlite3 \
        ghc \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (defence in depth; the work dir is bind-mounted at runtime).
RUN useradd --create-home --uid 10001 agent
USER agent
WORKDIR /agent
""".lstrip()


def build_image(tag: str = DEFAULT_TAG, *, log=print) -> bool:
    """Build the sandbox image. Returns True on success."""
    import shutil
    if shutil.which("docker") is None:
        log("docker is not installed; cannot build the sandbox image.")
        return False
    with tempfile.TemporaryDirectory() as td:
        dockerfile = Path(td) / "Dockerfile"
        dockerfile.write_text(DOCKERFILE, encoding="utf-8")
        log(f"Building hardened sandbox image {tag} (this can take a while)…")
        try:
            subprocess.run(["docker", "build", "-t", tag, td], check=True)
        except subprocess.CalledProcessError as e:
            log(f"image build failed: {e}")
            return False
    log(f"sandbox image {tag} ready.")
    return True
