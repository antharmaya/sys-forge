"""DSA structures that solve real systems problems and aren't already in the
stdlib. (Topological sort IS in the stdlib — use `graphlib.TopologicalSorter`,
don't reimplement it; it already raises `graphlib.CycleError` on a cycle.)
"""

from __future__ import annotations

import bisect
import hashlib
from typing import Generic, Hashable, Iterable, TypeVar

T = TypeVar("T", bound=Hashable)

# ─────────────────────────────────────────────────────────────────────────
# Union-Find (disjoint set)
# ─────────────────────────────────────────────────────────────────────────


class UnionFind(Generic[T]):
    """Disjoint-set over arbitrary hashable items (not just int indices) —
    for grouping items incrementally as you discover more links between
    them: failure-blast-radius clustering, dedup-merge as more matches are
    found, connected-component detection in a dependency graph."""

    def __init__(self, items: Iterable[T] = ()):
        self._parent: dict[T, T] = {}
        self._rank: dict[T, int] = {}
        for item in items:
            self.add(item)

    def add(self, item: T) -> None:
        if item not in self._parent:
            self._parent[item] = item
            self._rank[item] = 0

    def find(self, item: T) -> T:
        self.add(item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        # path compression: point every visited node directly at the root
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: T, b: T) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def connected(self, a: T, b: T) -> bool:
        return self.find(a) == self.find(b)

    def groups(self) -> dict[T, list[T]]:
        result: dict[T, list[T]] = {}
        for item in self._parent:
            result.setdefault(self.find(item), []).append(item)
        return result


# ─────────────────────────────────────────────────────────────────────────
# Trie
# ─────────────────────────────────────────────────────────────────────────


class Trie:
    """Prefix tree for routing tables, autocomplete, config-key namespaces —
    anywhere lookup is by prefix rather than exact match. Cost is bound by
    the length of the query, not the number of stored keys."""

    def __init__(self) -> None:
        self._children: dict[str, Trie] = {}
        self._is_end = False

    def insert(self, word: str) -> None:
        node = self
        for ch in word:
            node = node._children.setdefault(ch, Trie())
        node._is_end = True

    def contains(self, word: str) -> bool:
        node = self._walk(word)
        return node is not None and node._is_end

    def starts_with(self, prefix: str) -> bool:
        return self._walk(prefix) is not None

    def words_with_prefix(self, prefix: str) -> list[str]:
        node = self._walk(prefix)
        if node is None:
            return []
        results: list[str] = []
        node._collect(prefix, results)
        return results

    def _walk(self, s: str) -> Trie | None:
        node = self
        for ch in s:
            if ch not in node._children:
                return None
            node = node._children[ch]
        return node

    def _collect(self, prefix: str, out: list[str]) -> None:
        if self._is_end:
            out.append(prefix)
        for ch, child in self._children.items():
            child._collect(prefix + ch, out)


# ─────────────────────────────────────────────────────────────────────────
# Consistent hash ring
# ─────────────────────────────────────────────────────────────────────────


class ConsistentHashRing:
    """Distributes keys across nodes such that adding/removing a node only
    remaps the keys landing in that node's arc of the ring (~1/N of all
    keys), instead of the near-total remap a naive `hash(key) % num_nodes`
    causes on every scaling event. Virtual nodes (replicas per real node)
    smooth out the distribution — too few and some nodes get a
    disproportionate share of the ring."""

    def __init__(self, nodes: Iterable[str] = (), replicas: int = 100):
        self.replicas = replicas
        self._ring: dict[int, str] = {}
        self._sorted_hashes: list[int] = []
        for node in nodes:
            self.add_node(node)

    @staticmethod
    def _hash(key: str) -> int:
        return int(hashlib.sha256(key.encode()).hexdigest(), 16)

    def add_node(self, node: str) -> None:
        for i in range(self.replicas):
            h = self._hash(f"{node}#{i}")
            self._ring[h] = node
            bisect.insort(self._sorted_hashes, h)

    def remove_node(self, node: str) -> None:
        for i in range(self.replicas):
            h = self._hash(f"{node}#{i}")
            if h in self._ring:
                del self._ring[h]
                idx = bisect.bisect_left(self._sorted_hashes, h)
                if idx < len(self._sorted_hashes) and self._sorted_hashes[idx] == h:
                    self._sorted_hashes.pop(idx)

    def get_node(self, key: str) -> str:
        if not self._ring:
            raise RuntimeError("ring has no nodes")
        h = self._hash(key)
        idx = bisect.bisect(self._sorted_hashes, h) % len(self._sorted_hashes)
        return self._ring[self._sorted_hashes[idx]]


# ─────────────────────────────────────────────────────────────────────────
# Bloom filter
# ─────────────────────────────────────────────────────────────────────────


class BloomFilter:
    """Probabilistic membership test: never a false negative ("definitely
    not present" is always correct), tunable false-positive rate. Use to
    skip an expensive lookup (DB query, network call) on keys that
    definitely haven't been seen, before paying the cost of checking the
    real store for keys that might have been."""

    def __init__(self, expected_items: int, false_positive_rate: float = 0.01):
        import math

        self.size = max(1, int(-expected_items * math.log(false_positive_rate) / (math.log(2) ** 2)))
        self.num_hashes = max(1, round((self.size / expected_items) * math.log(2)))
        self._bits = bytearray((self.size + 7) // 8)

    def _hash_positions(self, item: str) -> list[int]:
        # Double hashing (Kirsch-Mitzenmacher): derive num_hashes indices from
        # just two real hash computations instead of computing num_hashes
        # independent hashes — standard, well-studied technique, not a shortcut.
        h1 = int(hashlib.sha256(item.encode()).hexdigest(), 16)
        h2 = int(hashlib.md5(item.encode()).hexdigest(), 16)
        return [(h1 + i * h2) % self.size for i in range(self.num_hashes)]

    def add(self, item: str) -> None:
        for pos in self._hash_positions(item):
            self._bits[pos // 8] |= 1 << (pos % 8)

    def __contains__(self, item: str) -> bool:
        return all(self._bits[pos // 8] & (1 << (pos % 8)) for pos in self._hash_positions(item))
