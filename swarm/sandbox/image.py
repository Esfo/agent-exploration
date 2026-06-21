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

# Common Python libraries the coding/testing/optimization/math agents reach for.
# Baked in at build time so they're available even under --network none at runtime.
RUN pip3 install --no-cache-dir --break-system-packages \
        numpy \
        scipy \
        pandas \
        sympy \
        matplotlib \
        scikit-learn \
        networkx \
        requests \
        pytest \
        pydantic

# Non-root user (defence in depth; the work dir is bind-mounted at runtime).
RUN useradd --create-home --uid 10001 agent
USER agent
WORKDIR /agent
""".lstrip()


def _image_id(tag: str) -> str | None:
    try:
        out = subprocess.run(["docker", "images", "-q", tag],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def build_image(tag: str = DEFAULT_TAG, *, log=print) -> bool:
    """(Re)build the sandbox image, erasing the previous one. Returns True on
    success. A fresh build with the same tag would otherwise leave the old image
    dangling; here the replaced image is removed."""
    import shutil
    if shutil.which("docker") is None:
        log("docker is not installed; cannot build the sandbox image.")
        return False
    old_id = _image_id(tag)
    with tempfile.TemporaryDirectory() as td:
        dockerfile = Path(td) / "Dockerfile"
        dockerfile.write_text(DOCKERFILE, encoding="utf-8")
        log(f"Building hardened sandbox image {tag} (this can take a while)...")
        try:
            subprocess.run(["docker", "build", "-t", tag, td], check=True)
        except subprocess.CalledProcessError as e:
            log(f"image build failed: {e}")
            return False
    new_id = _image_id(tag)
    if old_id and new_id and old_id != new_id:
        subprocess.run(["docker", "rmi", "-f", old_id], capture_output=True, timeout=60)
        log(f"removed the previous sandbox image ({old_id[:12]}).")
    log(f"sandbox image {tag} ready.")
    return True
