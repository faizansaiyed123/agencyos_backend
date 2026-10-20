"""Shared pagination parameters and response envelope."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

MAX_PAGE_SIZE = 100


class PageParams(BaseModel):
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageDep = Annotated[PageParams, Depends(page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
