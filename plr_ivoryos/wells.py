"""What a step's arguments mean, said in a way IvoryOS can read without importing anything.

IvoryOS NextGen reads two things from a driver, both by duck typing, so this package depends on
nothing from IvoryOS:

* Metadata in an `Annotated[...]` hint that has an `ivoryos_schema()` method. Its keys are added
  to that parameter's entry in the schema: `Labware("plate")` makes the argument a choice among
  the plates on the worktable, `Wells("plate")` makes it wells picked on a plate (the plate is
  chosen in the same picker), and `PerWell("targets")` makes it one value per well.
* Methods named `__ivoryos_labware__` and friends on the driver (see liquid_handler.py), which
  report the worktable. Dunder names, so they are never offered as steps.

The original IvoryOS reads `Annotated[str, ...]` as `str`, so there these are plain text fields.

Wells are written as PyLabRobot writes them, as text: `assay_plate[A1:H1]` is PyLabRobot's
`assay_plate["A1:H1"]`, so one argument names the labware and its wells together, the way a
PyLabRobot `Well` knows its plate. Several are separated by commas (`reservoir[A1], reservoir[A2]`),
a bare name is every well, and a list of them is what a batch step receives for its rows.

Inside the brackets: "A1", "A1:H1" (down a column), "A1:A12" (along a row), "A1:H3" (the
rectangle, column by column), "all", or several separated by commas. One
difference from PyLabRobot's own `plate["A1:B2"]` is deliberate: PyLabRobot reads a rectangle row
by row (A1, A2, B1, B2), this reads it column by column (A1, B1, A2, B2), which is the order a
multichannel head works in and the order the IvoryOS plate picker writes. A single column or row
reads the same in both. IvoryOS NextGen checks wells with copies of `expand_wells` and `expand_references`
(`ivoryos_edge.labware`); they must agree.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Union

# What a wells argument carries: "plate[A1]", "plate[A1:H1, A3]", "plate" (all of it), several
# separated by commas, or a list of those (a batch step's rows).
WellSelection = Union[str, List[str]]
ALL = "all"


class Labware:
    """`Annotated[str, Labware("plate")]`: the name of a labware on the worktable. Categories
    narrow the choice ("plate", "tip_rack", "reservoir", "tube_rack"); none means any."""

    def __init__(self, *categories: str):
        self.categories = list(categories)

    def ivoryos_schema(self) -> dict:
        return {"labware": self.categories}


class Wells:
    """`Annotated[WellSelection, Wells("plate")]`: wells written with their labware,
    `assay_plate[A1:H1]`. Categories narrow which labware ("plate", "tip_rack", ...)."""

    def __init__(self, *categories: str):
        self.categories = list(categories)

    def ivoryos_schema(self) -> dict:
        return {"type": "wells", "wells": {"labware": self.categories}}


class PerWell:
    """`Annotated[Union[float, List[float]], PerWell("targets")]`: one value for every well of that
    argument, or one per well in the same order."""

    def __init__(self, of: str):
        self.of = of

    def ivoryos_schema(self) -> dict:
        return {"type": "float", "numeric": True, "per_well": self.of}


class Site:
    """`Annotated[str, Site()]`: a place on the worktable a labware can sit (a slot, a carrier
    position)."""

    def ivoryos_schema(self) -> dict:
        return {"labware_site": True}


def _index(grid: List[List[str]]) -> Dict[str, tuple]:
    return {name: (r, c) for r, row in enumerate(grid) for c, name in enumerate(row)}


def _span(a: int, b: int) -> Iterable[int]:
    return range(a, b + 1) if a <= b else range(a, b - 1, -1)


def expand_wells(selection: Any, grid: List[List[str]]) -> List[str]:
    """A selection as the positions it names, in visiting order. Raises ValueError naming what is
    not a position: a typo must not become a smaller transfer."""
    index = _index(grid)
    if isinstance(selection, (list, tuple)):
        tokens = [str(t).strip() for t in selection]
    else:
        tokens = [t for t in re.split(r"[,;\s]+", str(selection if selection is not None else "").strip()) if t]
    out: List[str] = []
    for token in tokens:
        if not token:
            continue
        if token.lower() in (ALL, "*"):
            columns = len(grid[0]) if grid else 0
            out.extend(grid[r][c] for c in range(columns) for r in range(len(grid)))
            continue
        if ":" in token:
            first, _, last = token.partition(":")
            first, last = first.strip(), last.strip()
            for corner in (first, last):
                if corner not in index:
                    raise ValueError(f"'{corner}' is not a position")
            (r1, c1), (r2, c2) = index[first], index[last]
            out.extend(grid[r][c] for c in _span(c1, c2) for r in _span(r1, r2))
            continue
        if token not in index:
            raise ValueError(f"'{token}' is not a position")
        out.append(token)
    return out


_REFERENCE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[([^\]]*)\])?\s*[,;]?\s*")
_WELL_NAME = re.compile(r"[A-Za-z]{1,2}[0-9]{1,3}")


def parse_references(value: Any) -> List[tuple]:
    """`assay_plate[A1:H1], reservoir[A1]` (or a list of such) as [(labware, selection or None)].
    A bare name (`assay_plate`) has no selection. Raises ValueError for anything else."""
    items = value if isinstance(value, (list, tuple)) else [value]
    out: List[tuple] = []
    for item in items:
        text = str(item if item is not None else "").strip()
        position = 0
        while position < len(text):
            match = _REFERENCE.match(text, position)
            if not match or match.end() == position:
                raise ValueError(f"'{text}' is not written as labware[wells], e.g. assay_plate[A1:H1]")
            out.append((match.group(1), match.group(2)))
            position = match.end()
    if not out:
        raise ValueError("no wells were given")
    return out


def expand_references(value: Any, grids: Dict[str, List[List[str]]], kinds: Optional[Dict[str, str]] = None,
                      categories: Iterable[str] = ()) -> List[tuple]:
    """Every (labware, well) a value names, in order. `grids` is each labware's position names;
    a bare name is all of them. Raises ValueError saying what is wrong, naming the labware."""
    wanted = list(categories or ())
    out: List[tuple] = []
    for labware, selection in parse_references(value):
        if labware not in grids:
            hint = " (write wells with their labware, e.g. assay_plate[A1])" if _WELL_NAME.fullmatch(labware) else ""
            raise ValueError(f"'{labware}' is not on this worktable{hint}; it has {', '.join(grids) or 'nothing'}")
        kind = (kinds or {}).get(labware)
        if wanted and kind and kind not in wanted:
            raise ValueError(f"'{labware}' is a {kind.replace('_', ' ')}, not a {' or '.join(c.replace('_', ' ') for c in wanted)}")
        try:
            wells = expand_wells(ALL if selection is None else selection, grids[labware])
        except ValueError as e:
            raise ValueError(f"{e} on {labware}") from None
        out.extend((labware, well) for well in wells)
    return out
