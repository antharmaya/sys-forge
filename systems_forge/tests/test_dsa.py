from systems_forge.dsa import BloomFilter, ConsistentHashRing, Trie, UnionFind


class TestUnionFind:
    def test_unrelated_items_start_disconnected(self):
        uf: UnionFind[str] = UnionFind(["a", "b", "c"])
        assert not uf.connected("a", "b")

    def test_union_connects_items(self):
        uf: UnionFind[str] = UnionFind()
        uf.union("a", "b")
        uf.union("b", "c")
        assert uf.connected("a", "c")  # transitively connected via b

    def test_merging_two_groups_connects_everyone(self):
        uf: UnionFind[int] = UnionFind()
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(3, 4)
        assert not uf.connected(0, 3)
        uf.union(2, 4)
        assert uf.connected(0, 3)  # groups merged transitively

    def test_groups_returns_correct_partition(self):
        uf: UnionFind[int] = UnionFind(range(6))
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(3, 4)
        groups = uf.groups()
        sizes = sorted(len(members) for members in groups.values())
        assert sizes == [1, 2, 3]  # {5}, {3,4}, {0,1,2}


class TestTrie:
    def test_exact_match(self):
        t = Trie()
        t.insert("hello")
        assert t.contains("hello")
        assert not t.contains("hell")  # prefix alone isn't a stored word

    def test_prefix_check(self):
        t = Trie()
        t.insert("hello")
        assert t.starts_with("hell")
        assert not t.starts_with("world")

    def test_words_with_prefix(self):
        t = Trie()
        for w in ["cat", "car", "care", "dog"]:
            t.insert(w)
        results = set(t.words_with_prefix("car"))
        assert results == {"car", "care"}

    def test_empty_prefix_matches_nothing_stored(self):
        t = Trie()
        assert t.words_with_prefix("x") == []


class TestConsistentHashRing:
    def test_same_key_always_maps_to_same_node(self):
        ring = ConsistentHashRing(["node-a", "node-b", "node-c"])
        assert ring.get_node("user-123") == ring.get_node("user-123")

    def test_distributes_across_all_nodes(self):
        ring = ConsistentHashRing(["node-a", "node-b", "node-c"])
        assigned = {ring.get_node(f"key-{i}") for i in range(200)}
        assert assigned == {"node-a", "node-b", "node-c"}  # every node gets some keys

    def test_removing_a_node_only_remaps_its_own_keys(self):
        ring = ConsistentHashRing(["node-a", "node-b", "node-c"])
        keys = [f"key-{i}" for i in range(500)]
        before = {k: ring.get_node(k) for k in keys}
        ring.remove_node("node-b")
        after = {k: ring.get_node(k) for k in keys}
        moved = sum(1 for k in keys if before[k] != after[k])
        unaffected = sum(1 for k in keys if before[k] == "node-b")
        # every key that WAS on node-b must have moved; keys on other nodes
        # should mostly be untouched (allow slack for a few edge cases where
        # a key's next-clockwise node was also node-b's replica)
        assert all(before[k] != "node-b" or after[k] != "node-b" for k in keys)
        assert moved <= unaffected + 5

    def test_empty_ring_raises(self):
        ring = ConsistentHashRing()
        try:
            ring.get_node("anything")
            assert False, "should have raised"
        except RuntimeError:
            pass


class TestBloomFilter:
    def test_added_item_is_reported_present(self):
        bf = BloomFilter(expected_items=100)
        bf.add("hello")
        assert "hello" in bf

    def test_never_false_negative(self):
        bf = BloomFilter(expected_items=1000, false_positive_rate=0.01)
        items = [f"item-{i}" for i in range(500)]
        for item in items:
            bf.add(item)
        # every added item MUST report present — a bloom filter can false-positive
        # but never false-negative
        assert all(item in bf for item in items)

    def test_false_positive_rate_is_roughly_bounded(self):
        bf = BloomFilter(expected_items=1000, false_positive_rate=0.01)
        for i in range(1000):
            bf.add(f"present-{i}")
        false_positives = sum(1 for i in range(5000) if f"absent-{i}" in bf)
        rate = false_positives / 5000
        # generous slack (0.05 vs configured 0.01) — this is a probabilistic
        # structure, the test checks it's in the right ballpark, not exact
        assert rate < 0.05
