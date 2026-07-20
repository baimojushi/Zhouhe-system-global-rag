import unittest

try:
    from query_rewriter import (
        extract_json_object,
        normalize_query,
        reciprocal_rank_fusion,
        retrieve_with_optional_rewrite,
        sanitize_rewrite_candidates,
    )
except ImportError:
    from backend.query_rewriter import (
        extract_json_object,
        normalize_query,
        reciprocal_rank_fusion,
        retrieve_with_optional_rewrite,
        sanitize_rewrite_candidates,
    )


class QueryRewriterTest(unittest.TestCase):
    def test_normalize_and_bound_query(self):
        self.assertEqual(normalize_query("  WSL2\n  启动失败  "), "WSL2 启动失败")
        self.assertEqual(len(normalize_query("x" * 700)), 500)

    def test_extract_json_tolerates_code_fence(self):
        parsed = extract_json_object('```json\n{"queries":["甲","乙"]}\n```')
        self.assertEqual(parsed["queries"], ["甲", "乙"])

    def test_candidates_are_deduplicated_and_capped(self):
        variants = sanitize_rewrite_candidates(
            "Gemma 启动失败",
            [" Gemma  启动失败 ", "llama.cpp Gemma 无法启动", "显存不足 OOM", "额外问法"],
            max_variants=2,
        )
        self.assertEqual(variants, ["llama.cpp Gemma 无法启动", "显存不足 OOM"])

    def test_weighted_rrf_keeps_original_and_deduplicates(self):
        original = [
            {"chunk_id": "a", "title": "A"},
            {"chunk_id": "b", "title": "B"},
        ]
        expanded = [
            {"chunk_id": "b", "title": "B"},
            {"chunk_id": "c", "title": "C"},
        ]
        fused = reciprocal_rank_fusion([
            ("原问题", original, 1.35),
            ("扩展问题", expanded, 1.0),
        ], top_k=3)
        self.assertEqual([item["chunk_id"] for item in fused], ["b", "a", "c"])
        self.assertEqual(fused[0]["matched_queries"], ["原问题", "扩展问题"])
        self.assertGreater(fused[0]["score"], fused[1]["score"])

    def test_fusion_handles_items_without_chunk_id(self):
        item = {"document_id": "doc-1", "page": 2, "content": "same"}
        fused = reciprocal_rank_fusion([
            ("q1", [item], 1.0),
            ("q2", [dict(item)], 1.0),
        ], top_k=5)
        self.assertEqual(len(fused), 1)


class QueryRewriteOrchestrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_expansion_searches_all_queries_and_fuses(self):
        async def rewrite_call(query, limit):
            self.assertEqual((query, limit), ("原问题", 2))
            return {"queries": ["替代问法"], "model": "test-model", "prompt_tokens": 12}

        calls = []

        def search_call(query, limit):
            calls.append((query, limit))
            if query == "原问题":
                return [{"chunk_id": "a"}, {"chunk_id": "b"}]
            return [{"chunk_id": "b"}, {"chunk_id": "c"}]

        results, metadata = await retrieve_with_optional_rewrite(
            original_query="原问题",
            top_k=3,
            rewrite_enabled=True,
            max_variants=2,
            rewrite_call=rewrite_call,
            search_call=search_call,
        )
        self.assertTrue(metadata["applied"])
        self.assertEqual(metadata["schema_version"], "1.0")
        self.assertEqual(metadata["queries"], ["原问题", "替代问法"])
        self.assertEqual([item["chunk_id"] for item in results], ["b", "a", "c"])
        self.assertEqual([query for query, _ in calls], ["原问题", "替代问法"])

    async def test_model_failure_falls_back_to_original_only(self):
        async def rewrite_call(_query, _limit):
            raise TimeoutError("model timeout")

        calls = []

        def search_call(query, _limit):
            calls.append(query)
            return [{"chunk_id": "original"}]

        results, metadata = await retrieve_with_optional_rewrite(
            original_query="原问题",
            top_k=3,
            rewrite_enabled=True,
            max_variants=2,
            rewrite_call=rewrite_call,
            search_call=search_call,
        )
        self.assertFalse(metadata["applied"])
        self.assertEqual(calls, ["原问题"])
        self.assertEqual(results[0]["chunk_id"], "original")
        self.assertIn("原问题检索", metadata["fallback_reason"])

    async def test_disabled_mode_never_calls_model(self):
        async def rewrite_call(_query, _limit):
            self.fail("disabled rewrite must not call model")

        results, metadata = await retrieve_with_optional_rewrite(
            original_query="原问题",
            top_k=1,
            rewrite_enabled=False,
            max_variants=2,
            rewrite_call=rewrite_call,
            search_call=lambda _query, _limit: [{"chunk_id": "a"}],
        )
        self.assertFalse(metadata["enabled"])
        self.assertFalse(metadata["applied"])
        self.assertEqual(results[0]["chunk_id"], "a")


if __name__ == "__main__":
    unittest.main()
