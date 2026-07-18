#!/usr/bin/env python3
"""Regression tests for the V2 persistent knowledge control plane."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_store import (  # noqa: E402
    KnowledgeStore,
    StoreConflict,
    StoreValidationError,
)


class KnowledgeStoreTest(unittest.TestCase):
    def setUp(self):
        # Keep ephemeral databases outside the repository so concurrent ESLint
        # scans never race a disappearing directory.  The stable parent is
        # ignored by both Git and the lint command.
        test_root = Path(__file__).resolve().parents[1] / ".test-work"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.db_path = Path(self.temp.name) / "control.db"
        self.store = KnowledgeStore(self.db_path)

    def tearDown(self):
        self.temp.cleanup()

    def test_seeds_every_library_independently(self):
        libraries = self.store.list_libraries()
        self.assertEqual(5, len(libraries))
        self.assertTrue(all(self.store.get_tree(item["id"])["tree"] for item in libraries))
        self.assertEqual(1, sum(
            1 for node in self.store.get_tree("production")["tree"]
            if node["is_unclassified"]
        ))

    def test_library_and_node_crud_with_optimistic_version(self):
        library = self.store.create_library("工程资料", "engineering")
        self.assertEqual("kb_engineering_v1", library["collection_name"])
        root = self.store.get_tree("engineering")
        node = self.store.create_node(
            "engineering", "设备", expected_version=root["version"]
        )
        self.assertEqual(2, node["taxonomy_version"])
        with self.assertRaises(StoreConflict):
            self.store.create_node(
                "engineering", "过期请求", expected_version=root["version"]
            )
        renamed = self.store.update_node(
            node["id"], {"name": "生产设备", "description": "设备知识"},
            expected_version=2,
        )
        self.assertEqual("生产设备", renamed["name"])

    def test_node_move_rejects_cycles(self):
        version = self.store.get_tree("notes")["version"]
        parent = self.store.create_node("notes", "父节点", expected_version=version)
        child = self.store.create_node(
            "notes", "子节点", parent_id=parent["id"],
            expected_version=parent["taxonomy_version"],
        )
        with self.assertRaises(StoreValidationError):
            self.store.move_node(
                parent["id"], child["id"],
                expected_version=child["taxonomy_version"],
            )

    def test_document_primary_alias_tags_and_move(self):
        document = self.store.create_document(
            "production", "部署说明.md", "pr-unclassified",
            mime_type="text/markdown", source_path="/kb/部署说明.md",
            content_hash="abc123",
        )
        self.assertEqual("unclassified", document["status"])
        result = self.store.move_documents([document["id"]], "pr-platform")
        self.assertEqual(1, result["moved_count"])
        moved = self.store.get_document(document["id"])
        self.assertEqual("pr-platform", moved["primary_node_id"])
        self.assertEqual("active", moved["status"])

        aliased = self.store.add_alias(document["id"], "pr-sop")
        self.assertEqual(["pr-sop"], [item["id"] for item in aliased["aliases"]])
        tag = self.store.create_tag("production", "需复核", "#ff3153")
        tagged = self.store.set_document_tags(document["id"], [tag["id"]])
        self.assertEqual("需复核", tagged["tags"][0]["name"])

    def test_archive_branch_moves_documents_to_unclassified(self):
        document = self.store.create_document(
            "production", "向量故障.md", "pr-vector", content_hash="hash-vector"
        )
        version = self.store.get_tree("production")["version"]
        archived = self.store.archive_node("pr-platform", expected_version=version)
        self.assertGreaterEqual(archived["archived_nodes"], 4)
        moved = self.store.get_document(document["id"])
        self.assertEqual("pr-unclassified", moved["primary_node_id"])
        self.assertEqual("unclassified", moved["status"])

    def test_ingest_job_is_idempotent_and_not_a_document_chunk(self):
        first = self.store.queue_ingest(
            "academic", "ac-unclassified", "/kb/paper.pdf", "same-key"
        )
        second = self.store.queue_ingest(
            "academic", "ac-unclassified", "/kb/paper.pdf", "same-key"
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, len(self.store.list_jobs("academic")))

    def test_document_migration_is_idempotent(self):
        first = self.store.create_document(
            "academic", "同一论文.pdf", "ac-unclassified",
            source_path="/kb/same.pdf", content_hash="same-hash",
            index_status="indexed", idempotent=True,
        )
        second = self.store.create_document(
            "academic", "同一论文.pdf", "ac-unclassified",
            source_path="/kb/same.pdf", content_hash="same-hash",
            index_status="indexed", idempotent=True,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, self.store.list_documents("academic")["count"])

    def test_persistence_and_cursor_pagination(self):
        for index in range(3):
            self.store.create_document(
                "notes", f"笔记 {index}", "nt-unclassified",
                source_path=f"/kb/note-{index}.md", content_hash=str(index),
            )
        first = self.store.list_documents("notes", limit=2)
        self.assertEqual(2, first["count"])
        self.assertIsNotNone(first["next_cursor"])
        second = self.store.list_documents(
            "notes", limit=2, cursor=first["next_cursor"]
        )
        self.assertEqual(1, second["count"])

        reopened = KnowledgeStore(self.db_path)
        self.assertEqual(3, reopened.list_documents("notes")["count"])


if __name__ == "__main__":
    unittest.main()
