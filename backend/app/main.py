"""Minimal FastAPI placeholder factory. Plan 06 wires routes + `/metrics`."""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="Tide API", version="0.1.0")


app = create_app()
