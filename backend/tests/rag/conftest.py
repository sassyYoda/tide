"""RAG test fixtures — Qdrant testcontainer + ephemeral collection.

Session-scoped Qdrant container (first run pulls qdrant/qdrant:v1.17.1).
Function-scoped AsyncQdrantClient that tears down the `fishing_reports`
collection between tests so each test starts clean.
"""

from __future__ import annotations

import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import pytest_asyncio
from testcontainers.core.container import DockerContainer


def _wait_qdrant_ready(host: str, port: int, timeout: float = 60.0) -> None:
    """Poll the Qdrant /readyz endpoint until 200 or timeout.

    Plan 02-00 conftest started the container but provided no readiness wait;
    AsyncQdrantClient races the container boot and gets connection-refused on
    the first request. Plan 02-06 (Rule 3 auto-fix) adds an HTTP readiness
    poll before yielding so integration tests are deterministic.
    """
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/readyz"
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return
        except (URLError, ConnectionError, OSError) as e:
            last_err = e
        time.sleep(0.5)
    raise RuntimeError(
        f"Qdrant container did not become ready within {timeout}s: {last_err}"
    )


@pytest.fixture(scope="session")
def qdrant_container():
    """Session-scoped Qdrant container. First run pulls the image."""
    ctr = (
        DockerContainer("qdrant/qdrant:v1.17.1")
        .with_exposed_ports(6333)
        .with_env("QDRANT__SERVICE__HTTP_PORT", "6333")
    )
    ctr.start()
    try:
        host = ctr.get_container_host_ip()
        port = int(ctr.get_exposed_port(6333))
        _wait_qdrant_ready(host, port)
        yield ctr
    finally:
        ctr.stop()


@pytest.fixture(scope="session")
def qdrant_url(qdrant_container) -> str:
    host = qdrant_container.get_container_host_ip()
    port = int(qdrant_container.get_exposed_port(6333))
    return f"http://{host}:{port}"


@pytest_asyncio.fixture
async def qdrant_client(qdrant_url):
    """Function-scoped AsyncQdrantClient with `fishing_reports` wiped."""
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(url=qdrant_url, timeout=5.0)
    existing = {c.name for c in (await client.get_collections()).collections}
    if "fishing_reports" in existing:
        await client.delete_collection("fishing_reports")
    try:
        yield client
    finally:
        await client.close()
