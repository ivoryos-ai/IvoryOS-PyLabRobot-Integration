"""What each well holds, by liquid, and what happened on the worktable during a step.

PyLabRobot 1.0 tracks how much is in each well and which tip spots still hold a tip, and no longer
which liquid it is. The Labware view shows both, so this module keeps the rest, without knowing
anything about a particular robot: it compares the worktable before and after a step (`take`,
`changes`) and moves liquids accordingly (`Ledger.apply`).

Wells that lost volume in a step were aspirated from and wells that gained volume were dispensed
into. A head's channels are matched to wells in the order a head works, column by column and down
each column (A1, B1, ... H1, A2): eight wells for eight tips go one per channel, one well for eight
tips (a reservoir) is shared, and anything else is pooled across the head.
"""

import dataclasses
import threading
from typing import Dict, List, Optional, Tuple

from pylabrobot.resources import Container, ItemizedResource, TipRack

# A liquid nobody named: the volume is tracked, what it is is not.
UNKNOWN = "liquid"
_EPS = 1e-9

Key = Tuple[str, str]  # (labware, well)


@dataclasses.dataclass
class Snapshot:
    volumes: Dict[Key, float]
    tips: Dict[Key, bool]
    places: Dict[str, Optional[str]]
    order: Dict[Key, Tuple[str, int, int]]


def take(labware: Dict[str, object], place_of) -> Snapshot:
    """The worktable now: every well's volume, every tip spot, where every labware sits."""
    volumes: Dict[Key, float] = {}
    tips: Dict[Key, bool] = {}
    order: Dict[Key, Tuple[str, int, int]] = {}
    places: Dict[str, Optional[str]] = {}
    for name, resource in labware.items():
        places[name] = place_of(resource)
        items = resource.get_all_items() if isinstance(resource, ItemizedResource) else [resource]
        rows = getattr(resource, "num_items_y", 1) or 1
        for i, item in enumerate(items):
            well = resource.get_child_identifier(item) if isinstance(resource, ItemizedResource) else "A1"
            order[(name, well)] = (name, i // rows, i % rows)  # column, then row
            if isinstance(resource, TipRack):
                tips[(name, well)] = bool(item.has_tip())
            elif isinstance(item, Container):
                volumes[(name, well)] = float(item.tracker.get_used_volume())
    return Snapshot(volumes, tips, places, order)


@dataclasses.dataclass
class Changes:
    lost: List[Tuple[Key, float]]
    gained: List[Tuple[Key, float]]
    tips_taken: List[Key]
    tips_returned: List[Key]
    moved: List[str]

    def by_labware(self, keys: List[Key]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for labware, well in keys:
            out.setdefault(labware, []).append(well)
        return out


def changes(before: Snapshot, after: Snapshot) -> Changes:
    def ordered(keys):
        return sorted(keys, key=lambda k: after.order.get(k) or before.order.get(k) or (k[0], 0, 0))

    lost, gained = [], []
    for key in ordered(set(before.volumes) | set(after.volumes)):
        delta = after.volumes.get(key, 0.0) - before.volumes.get(key, 0.0)
        if delta < -_EPS:
            lost.append((key, -delta))
        elif delta > _EPS:
            gained.append((key, delta))
    taken = [k for k in ordered(before.tips) if before.tips[k] and not after.tips.get(k, False)]
    returned = [k for k in ordered(after.tips) if after.tips[k] and not before.tips.get(k, False)]
    moved = [name for name, place in after.places.items() if name in before.places and before.places[name] != place]
    return Changes(lost, gained, taken, returned, moved)


class Ledger:
    """Liquids by well, and in each head's tips, by channel. Changed on the background loop and read
    from IvoryOS's own threads, hence the lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.wells: Dict[Key, Dict[str, float]] = {}
        self.tips: Dict[str, List[Dict[str, float]]] = {}

    def clear(self) -> None:
        with self.lock:
            self.wells.clear()
            self.tips.clear()

    def of(self, key: Key) -> Dict[str, float]:
        with self.lock:
            return dict(self.wells.get(key) or {})

    def set(self, key: Key, liquid: Optional[str], volume: float) -> None:
        with self.lock:
            if liquid and volume > _EPS:
                self.wells[key] = {liquid: volume}
            else:
                self.wells.pop(key, None)

    def add(self, key: Key, liquid: str, volume: float) -> None:
        with self.lock:
            held = self.wells.setdefault(key, {})
            held[liquid] = held.get(liquid, 0.0) + volume

    def rename(self, old: str, new: str) -> None:
        with self.lock:
            for key in [k for k in self.wells if k[0] == old]:
                self.wells[(new, key[1])] = self.wells.pop(key)

    def forget(self, labware: str) -> None:
        with self.lock:
            for key in [k for k in self.wells if k[0] == labware]:
                del self.wells[key]

    def _take(self, key: Key, volume: float) -> Dict[str, float]:
        held = self.wells.get(key) or {}
        total = sum(held.values())
        if total <= _EPS:
            return {UNKNOWN: volume}
        share = min(1.0, volume / total)
        taken = {liquid: amount * share for liquid, amount in held.items()}
        for liquid, amount in taken.items():
            held[liquid] -= amount
        return taken

    @staticmethod
    def _give(tip: Dict[str, float], volume: float) -> Dict[str, float]:
        total = sum(tip.values())
        if total <= _EPS:
            return {UNKNOWN: volume}
        share = min(1.0, volume / total)
        given = {liquid: amount * share for liquid, amount in tip.items()}
        for liquid, amount in given.items():
            tip[liquid] -= amount
        return given

    def apply(self, head: Optional[str], channels: int, change: Changes, tips_before: int, tips_after: int) -> None:
        """Move liquids as a step on `head` (with `channels` tips on it while it worked) did."""
        with self.lock:
            if head is not None:
                if tips_before == 0 and tips_after > 0 or change.tips_taken:
                    self.tips[head] = [{} for _ in range(max(tips_after, 1))]
                pools = self.tips.setdefault(head, [{} for _ in range(max(channels, 1))])
                if len(pools) < channels:
                    pools.extend({} for _ in range(channels - len(pools)))
            else:
                pools = [{}]
            n = max(1, min(channels, len(pools)) if head is not None else 1)
            if change.lost:
                draws = self._pair(change.lost, n)
                for channel, key, volume in draws:
                    for liquid, amount in self._take(key, volume).items():
                        pools[channel][liquid] = pools[channel].get(liquid, 0.0) + amount
            if change.gained:
                for channel, key, volume in self._pair(change.gained, n):
                    for liquid, amount in self._give(pools[channel], volume).items():
                        held = self.wells.setdefault(key, {})
                        held[liquid] = held.get(liquid, 0.0) + amount
            if head is not None and tips_after == 0:
                self.tips.pop(head, None)

    @staticmethod
    def _pair(moves: List[Tuple[Key, float]], n: int) -> List[Tuple[int, Key, float]]:
        """(channel, well, volume) for each part of a step: one well per channel, one well shared
        by every channel, or (anything else) every well split evenly across the channels."""
        if len(moves) == n:
            return [(i, key, volume) for i, (key, volume) in enumerate(moves)]
        if len(moves) == 1:
            key, volume = moves[0]
            return [(i, key, volume / n) for i in range(n)]
        return [(i, key, volume / n) for key, volume in moves for i in range(n)]

    def contents(self, key: Key, volume: float) -> Dict[str, float]:
        """What a well holding `volume` holds, by liquid: the ledger's account scaled to the volume
        PyLabRobot tracks (which is the truth), and unnamed liquid where there is no account."""
        with self.lock:
            held = {k: v for k, v in (self.wells.get(key) or {}).items() if v > _EPS}
        total = sum(held.values())
        if volume <= _EPS:
            return {}
        if total <= _EPS:
            return {UNKNOWN: volume}
        return {liquid: amount * volume / total for liquid, amount in held.items()}
