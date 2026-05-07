from __future__ import annotations

from typing import List

from helpers.geometry import Pt, dist


def pair_nearest(source_points: List[Pt], target_points: List[Pt], max_dist: float) -> int:
    used_targets = set()
    pairs = 0

    for src in source_points:
        best_idx = None
        best_dist = float("inf")

        for idx, dst in enumerate(target_points):
            if idx in used_targets:
                continue

            d = dist(src, dst)
            if d < best_dist:
                best_dist = d
                best_idx = idx

        if best_idx is not None and best_dist <= max_dist:
            used_targets.add(best_idx)
            pairs += 1

    return pairs