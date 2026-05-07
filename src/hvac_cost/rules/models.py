from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any



@dataclass
class ROI:
    enabled: bool = False
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0
    margin: float = 0.0

    def contains_xy(self, x: float, y: float) -> bool:
        if not self.enabled:
            return True
        xmin = self.xmin - self.margin
        xmax = self.xmax + self.margin
        ymin = self.ymin - self.margin
        ymax = self.ymax + self.margin
        return xmin <= x <= xmax and ymin <= y <= ymax

    def contains_pt(self, p: Pt) -> bool:
        return self.contains_xy(p.x, p.y)


@dataclass
class Rule:
    id: str
    name: str
    type: str  # "block_count" | "symbol_count"
    enabled: bool = True
    roi: ROI = field(default_factory=ROI)
    params: Dict[str, Any] = field(default_factory=dict)