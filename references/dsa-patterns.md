# DSA Patterns Mapped to Real Engineering Problems

These aren't interview trivia — each one exists because a real system needed exactly this shape of solution.
Recognizing the *symptom* that calls for a pattern is the actual skill; the algorithm itself is a known quantity
once you've named it correctly.

## Sliding window → rate limiting, moving averages

**Symptom:** "how many events happened in the last N seconds" or "what's the moving average over a window."

```python
from collections import deque
import time

class SlidingWindowCounter:
    def __init__(self, window_seconds: float):
        self.window = window_seconds
        self.events: deque[float] = deque()

    def hit(self) -> int:
        now = time.monotonic()
        self.events.append(now)
        while self.events and self.events[0] < now - self.window:
            self.events.popleft()
        return len(self.events)
```
`deque` gives O(1) append/popleft — a plain list would be O(n) to pop from the front, which matters once you're
calling this on every request. Use `time.monotonic()`, never `time.time()`, for measuring durations — wall-clock
time can jump backward (NTP correction, DST) and monotonic time never does.

## Token bucket → API rate limiting (the industry-standard shape)

**Symptom:** "allow bursts up to N, but average no more than R per second over time."

```python
import time

class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.last_refill = time.monotonic()

    def allow(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False
```
This is the same core algorithm behind most production rate limiters (this is the RFC-standard shape referenced
in RateGuard's own `AGENTS.md` — `tokens = min(burst, tokens + elapsed × rps)`). Note the distinction from a
**leaky bucket**: token bucket allows bursts up to capacity, leaky bucket smooths output to a strictly constant
rate — pick token bucket when bursts are fine and you only care about the average, leaky bucket when you need a
hard ceiling on instantaneous rate (e.g., protecting a downstream system that can't handle bursts at all).

## Union-Find → dependency grouping, cluster detection

**Symptom:** "these things belong to the same group, and I'm discovering more links incrementally."

```python
class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
```
Real use: detecting which services end up in the same failure-blast-radius group as you incrementally learn
about dependency edges, or clustering duplicate records as you discover more matching pairs. Path compression +
union by rank together give near-O(1) amortized operations — without both, a naive version degrades to O(n) per
operation on adversarial input.

## Topological sort → build order, migration order, task DAGs

**Symptom:** "these things depend on each other, what order do I process them in."

```python
from collections import deque

def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    in_degree = {node: 0 for node in graph}
    for deps in graph.values():
        for dep in deps:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    queue = deque(n for n, d in in_degree.items() if d == 0)
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for dep in graph.get(node, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    if len(order) != len(in_degree):
        raise ValueError("cycle detected — dependency graph is not a DAG")
    return order
```
**The cycle check at the end is not optional** — if it triggers, that's real information: your config, your
migration list, or your service dependency declaration genuinely has a circular dependency, and the fix is in the
data, not the algorithm.

## Heap / priority queue → job scheduling, top-K, k-way merge

**Symptom:** "give me the next-highest-priority item, repeatedly, cheaply."

```python
import heapq

# Job scheduler: lower number = higher priority, processed first
jobs: list[tuple[int, str]] = []
heapq.heappush(jobs, (2, "low-priority-report"))
heapq.heappush(jobs, (0, "critical-alert"))
priority, job = heapq.heappop(jobs)  # (0, "critical-alert")
```
Python's `heapq` is a min-heap only — for a max-heap, push negated values, or wrap in a tuple that sorts the way
you want. This is the right structure any time you're repeatedly asking "what's next" from a changing set, rather
than sorting the whole set once (sorting is O(n log n) upfront and doesn't help if new items arrive after you
started; a heap keeps each push/pop at O(log n) regardless).

## Trie → routing, autocomplete, prefix lookup

**Symptom:** "look this up by prefix" — URL routers, config-key namespaces, autocomplete.

```python
class TrieNode:
    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_end = False

class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for ch in word:
            node = node.children.setdefault(ch, TrieNode())
        node.is_end = True

    def starts_with(self, prefix: str) -> bool:
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return False
            node = node.children[ch]
        return True
```
Beats a linear scan over all keys checking `.startswith()` once the key set is large — lookup cost is bound by
the length of the query, not the number of keys.

## LRU vs LFU → caching, know which one your access pattern needs

**Symptom:** "cache with a size limit, need to evict something."

```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def expensive_lookup(key: str) -> str:
    ...
```
`functools.lru_cache` is genuinely production-grade for the common case — don't hand-roll an LRU with an
`OrderedDict` unless you need something it doesn't give you (per-entry TTL, size-in-bytes rather than
count-based eviction). **LRU vs LFU is a real decision, not a coin flip:** LRU evicts what hasn't been touched
*recently* — right when access has temporal locality (today's data matters more than last week's). LFU evicts
what's touched *least often overall* — right when some keys are reliably hot forever regardless of recency (a
popular product page shouldn't get evicted just because there was a burst of traffic to something else an hour
ago). Picking LRU for an LFU-shaped access pattern is a real, measurable cache-hit-rate bug, not just a stylistic
choice.

## Graph BFS/DFS → dependency graphs, blast-radius analysis

**Symptom:** "if this node fails/changes, what else is affected."

```python
from collections import deque

def blast_radius(graph: dict[str, list[str]], start: str) -> set[str]:
    visited = {start}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited
```
BFS (queue) vs DFS (stack, or recursion) give the same reachability set — pick BFS when you also care about
*distance* (how many hops away is each affected node, useful for prioritizing an incident response by proximity),
DFS when you only need the set and want lower memory overhead on a very wide graph.

## Consistent hashing → sharding, load distribution

**Symptom:** "distribute keys across N nodes, and don't reshuffle everything when N changes."

The problem with naive `hash(key) % num_nodes`: changing `num_nodes` by even one remaps almost every key. A
consistent hash ring maps both nodes and keys onto the same hash space; adding/removing a node only remaps the
keys that land in that node's specific arc of the ring, roughly `1/N` of all keys instead of nearly all of them.
This is the reason distributed caches and sharded databases don't fall over every time you scale the cluster.

## Bloom filter → membership testing at scale

**Symptom:** "has this been seen before" across a dataset too large to hold in a hash set, and false positives are
acceptable but false negatives are not.

A bloom filter is a bit array plus several hash functions: setting a key sets K bits; checking a key checks
whether all K bits are set. It can say "definitely not present" with certainty, or "possibly present" with a
tunable false-positive rate — it can never falsely say "definitely not present" for something that was actually
added. Real use: a cache checks the bloom filter before hitting the database on a lookup that's likely to miss —
if the filter says "definitely not present," skip the expensive lookup entirely; this is exactly why databases
like Cassandra and browsers' safe-browsing lists use them.

## Dynamic programming → optimal resource allocation

**Symptom:** "best way to allocate a limited resource across competing demands" — the shape to recognize is
*overlapping subproblems* (the same smaller decision recurs across different larger decisions) plus *optimal
substructure* (the best overall answer is built from best answers to the subproblems). Don't force-fit DP onto
a problem that's actually greedy-optimal (e.g., interval scheduling to maximize count is greedy, not DP) — the
tell is whether a locally-greedy choice can be proven never to hurt the global optimum; if yes, skip DP's
overhead and just write the greedy version.
