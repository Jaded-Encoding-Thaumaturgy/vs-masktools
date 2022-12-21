from __future__ import annotations

from typing import Protocol

from vstools import CustomEnum, PlanesT, SingleOrArrOpt, vs

__all__ = [
    'MorphoFunc',
    'XxpandMode',
    'Coordinates'
]


class MorphoFunc(Protocol):
    def __call__(
        self, clip: vs.VideoNode, planes: PlanesT = ...,
        threshold: int | None = ..., coordinates: SingleOrArrOpt[int] = ...
    ) -> vs.VideoNode:
        ...


class XxpandMode(CustomEnum):
    """Expand/inpand mode"""

    RECTANGLE = object()
    """Rectangular shape"""

    ELLIPSE = object()
    """Elliptical shape"""

    LOSANGE = object()
    """Diamond shape"""


class Coordinates(list[int], CustomEnum):
    VERTICAL = [0, 1, 0, 0, 0, 0, 1, 0]
    HORIZONTAL = [0, 0, 0, 1, 1, 0, 0, 0]
    RECTANGLE = [1, 1, 1, 1, 1, 1, 1, 1]
    DIAMOND = [0, 1, 0, 1, 1, 0, 1, 0]
    CORNERS = [1, 0, 1, 0, 0, 1, 0, 1]

    @classmethod
    def from_iter(cls, iter: int) -> Coordinates:
        return cls.DIAMOND if (iter % 3) != 1 else cls.RECTANGLE

    @classmethod
    def from_xxpand_mode(cls, xxpand_mode: XxpandMode, iter: int = 1) -> Coordinates:
        if xxpand_mode == XxpandMode.LOSANGE or (xxpand_mode is XxpandMode.ELLIPSE and iter % 3 != 1):
            return Coordinates.DIAMOND

        return Coordinates.RECTANGLE
