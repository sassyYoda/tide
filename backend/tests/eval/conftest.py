"""Phase 5 eval-runner fixtures.

Wave 2 (plan 05-03) wires docker-compose-aware fixtures via testcontainers
(reusing the ``testcontainers[postgres,redis]`` pattern from
``backend/tests/conftest.py``) plus an SSE-stream parser borrowed from
``backend/tests/api/conftest.py::parse_sse_stream`` for unit-testing the
Ragas SSE collector. Wave 0 leaves this file as a marker — no fixture
functions defined yet.
"""
from __future__ import annotations
