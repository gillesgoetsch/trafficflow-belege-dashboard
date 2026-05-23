"""Pagination helper that keeps query params consistent across list endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Query


@dataclass
class Page:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> Page:
    return Page(page=page, page_size=page_size)
