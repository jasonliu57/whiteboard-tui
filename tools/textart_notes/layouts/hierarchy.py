"""Basic hierarchy normalization used by outline-like styles."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from ..core.models import InputError


@dataclass(frozen=True)
class FlatNode:
    path: tuple[int, ...]
    depth: int
    text: str


@dataclass(frozen=True)
class HierarchyFacts:
    root_id: str
    input_order: tuple[str, ...]
    parent: Mapping[str, str | None]
    depth: Mapping[str, int]
    sibling_index: Mapping[str, int]
    preorder: tuple[str, ...]
    subtree_ids: Mapping[str, tuple[str, ...]]


def analyze_hierarchy(
    root_id: str,
    input_order: Sequence[str],
    children: Mapping[str, Sequence[str]],
    *,
    max_depth: int = 64,
) -> HierarchyFacts:
    """Validate a strict rooted tree and return canonical hierarchy facts."""

    order = tuple(input_order)
    if not order or len(set(order)) != len(order):
        raise InputError("hierarchy node order must be non-empty and unique")
    if root_id not in order:
        raise InputError(f"hierarchy root {root_id!r} is missing")
    if set(children) != set(order):
        raise InputError("hierarchy children map must contain every node exactly once")

    parent: dict[str, str | None] = {key: None for key in order}
    normalized: dict[str, tuple[str, ...]] = {}
    for key in order:
        values = tuple(children[key])
        if len(set(values)) != len(values):
            raise InputError(f"hierarchy node {key!r} repeats a child")
        for child in values:
            if child not in parent:
                raise InputError(f"hierarchy node {key!r} references missing child {child!r}")
            if parent[child] is not None:
                raise InputError(
                    f"hierarchy child {child!r} has parents {parent[child]!r} and {key!r}"
                )
            parent[child] = key
        normalized[key] = values

    color = {key: 0 for key in order}

    def detect(key: str) -> None:
        color[key] = 1
        for child in normalized[key]:
            if color[child] == 1:
                raise InputError(f"hierarchy contains a cycle through {child!r}")
            if color[child] == 0:
                detect(child)
        color[key] = 2

    for key in order:
        if color[key] == 0:
            detect(key)
    if parent[root_id] is not None:
        raise InputError("hierarchy root must not have a parent")
    orphans = [key for key in order if key != root_id and parent[key] is None]
    if orphans:
        raise InputError("hierarchy contains orphan nodes: " + ", ".join(orphans))

    depth: dict[str, int] = {}
    sibling_index: dict[str, int] = {root_id: 0}
    preorder: list[str] = []
    subtrees: dict[str, tuple[str, ...]] = {}

    def walk(key: str, level: int) -> tuple[str, ...]:
        if level > max_depth:
            raise InputError(f"hierarchy exceeds maximum depth {max_depth}")
        depth[key] = level
        preorder.append(key)
        gathered = [key]
        for index, child in enumerate(normalized[key]):
            sibling_index[child] = index
            gathered.extend(walk(child, level + 1))
        result = tuple(gathered)
        subtrees[key] = result
        return result

    reachable = walk(root_id, 0)
    if len(reachable) != len(order):
        missing = [key for key in order if key not in set(reachable)]
        raise InputError("hierarchy contains unreachable nodes: " + ", ".join(missing))
    return HierarchyFacts(
        root_id,
        order,
        MappingProxyType(parent),
        MappingProxyType(depth),
        MappingProxyType(sibling_index),
        tuple(preorder),
        MappingProxyType(subtrees),
    )


def flatten_hierarchy(nodes: object, *, max_depth: int = 12) -> list[FlatNode]:
    """Normalize ``[{text, children}]`` into stable pre-order rows."""

    if not isinstance(nodes, list):
        raise InputError("hierarchy nodes must be a list")
    output: list[FlatNode] = []

    def visit(items: list[object], parent: tuple[int, ...]) -> None:
        for index, raw in enumerate(items):
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                raise InputError("each hierarchy node needs a string 'text'")
            path = parent + (index,)
            depth = len(path) - 1
            if depth > max_depth:
                raise InputError(f"hierarchy exceeds maximum depth {max_depth}")
            text = raw["text"].strip()
            if not text:
                raise InputError("hierarchy node text cannot be empty")
            output.append(FlatNode(path, depth, text))
            children = raw.get("children", [])
            if not isinstance(children, list):
                raise InputError("node children must be a list")
            visit(children, path)

    visit(nodes, ())
    return output
