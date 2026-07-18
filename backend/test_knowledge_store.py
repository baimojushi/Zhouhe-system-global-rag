#!/usr/bin/env python3
"""Regression tests for the V2 persistent knowledge control plane."""

import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_store import (  # noqa: E402
    KnowledgeStore,
    SCHEMA_VERSION,
    StoreConflict,
    StoreNotFound,
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

    def _proposal_fixture(self, title: str = "待分类文档"):
        document = self.store.create_document(
            "production", title, "pr-unclassified",
            source_path=f"/kb/{title}.md", content_hash=title,
        )
        proposal = self.store.create_proposal("production", llm_model="test")
        item = self.store.add_proposal_item(
            proposal["id"], document["id"], "pr-unclassified", "pr-platform",
            confidence=0.91, reason_code="TEST",
        )
        return document, proposal, item

    def test_schema_v5_is_reported_and_reopen_is_idempotent(self):
        self.assertEqual(5, SCHEMA_VERSION)
        self.assertEqual(5, self.store.stats()["schema_version"])
        conn = self.store._connect()
        conn.execute(
            "UPDATE schema_meta SET value = '3' WHERE key = 'schema_version'"
        )
        conn.commit()
        conn.close()
        reopened = KnowledgeStore(self.db_path)
        conn = reopened._connect()
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        columns = {
            row["name"] for row in conn.execute(
                "PRAGMA table_info(proposal_items)"
            ).fetchall()
        }
        conn.close()
        self.assertEqual("5", version)
        self.assertIn("applied_document_revision", columns)

    def test_early_v4_tables_missing_v5_columns_are_migrated(self):
        legacy_path = Path(self.temp.name) / "early-v4.db"
        conn = sqlite3.connect(legacy_path)
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '3');
            CREATE TABLE classification_proposals (
              id TEXT PRIMARY KEY, library_id TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'draft', llm_model TEXT NOT NULL DEFAULT '',
              llm_response_json TEXT NOT NULL DEFAULT '{}',
              routing_cards_json TEXT NOT NULL DEFAULT '[]', subtree_json TEXT NOT NULL DEFAULT '[]',
              prompt_tokens INTEGER NOT NULL DEFAULT 0, completion_tokens INTEGER NOT NULL DEFAULT 0,
              created_by TEXT NOT NULL DEFAULT 'auto-classifier', created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE proposal_items (
              id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, document_id TEXT NOT NULL,
              version_id TEXT NOT NULL DEFAULT '', source_node_id TEXT NOT NULL,
              target_node_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
              confidence REAL NOT NULL DEFAULT 0, reason_code TEXT NOT NULL DEFAULT '',
              llm_reasoning TEXT NOT NULL DEFAULT '', previous_node_id TEXT NOT NULL DEFAULT '',
              applied_at TEXT NOT NULL DEFAULT '', reverted_at TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()
        migrated = KnowledgeStore(legacy_path)
        conn = migrated._connect()
        proposal_columns = {
            row["name"] for row in conn.execute(
                "PRAGMA table_info(classification_proposals)"
            ).fetchall()
        }
        item_columns = {
            row["name"] for row in conn.execute(
                "PRAGMA table_info(proposal_items)"
            ).fetchall()
        }
        conn.close()
        self.assertIn("applied_at", proposal_columns)
        self.assertIn("previous_document_status", item_columns)
        self.assertIn("base_document_revision", item_columns)

    def test_proposal_review_apply_revert_are_idempotent(self):
        document, proposal, item = self._proposal_fixture()
        approved = self.store.approve_proposal_item(proposal["id"], item["id"])
        self.assertEqual("approved", approved["status"])
        again = self.store.approve_proposal_item(proposal["id"], item["id"])
        self.assertEqual("approved", again["status"])

        applied = self.store.apply_proposal(proposal["id"])
        self.assertFalse(applied["idempotent"])
        self.assertEqual("pr-platform", self.store.get_document(document["id"])["primary_node_id"])
        self.assertTrue(self.store.apply_proposal(proposal["id"])["idempotent"])

        reverted = self.store.revert_proposal(proposal["id"])
        self.assertFalse(reverted["idempotent"])
        restored = self.store.get_document(document["id"])
        self.assertEqual("pr-unclassified", restored["primary_node_id"])
        self.assertEqual("unclassified", restored["status"])
        self.assertTrue(self.store.revert_proposal(proposal["id"])["idempotent"])

    def test_proposal_item_cannot_be_reviewed_through_another_proposal(self):
        _document, proposal, item = self._proposal_fixture()
        other = self.store.create_proposal("production", llm_model="test")
        with self.assertRaises(StoreNotFound):
            self.store.approve_proposal_item(other["id"], item["id"])
        self.assertEqual(
            "pending", self.store.get_proposal(proposal["id"])["items"][0]["status"]
        )

    def test_proposal_rejects_non_writable_target_and_duplicates(self):
        document = self.store.create_document(
            "production", "规则测试", "pr-unclassified", content_hash="rules"
        )
        version = self.store.get_tree("production")["version"]
        smart = self.store.create_node(
            "production", "智能视图", kind="smart", expected_version=version
        )
        proposal = self.store.create_proposal("production")
        with self.assertRaises(StoreValidationError):
            self.store.add_proposal_item(
                proposal["id"], document["id"], "pr-unclassified", smart["id"]
            )
        item = self.store.add_proposal_item(
            proposal["id"], document["id"], "pr-unclassified", "pr-platform"
        )
        self.assertEqual("pending", item["status"])
        with self.assertRaises(StoreConflict):
            self.store.add_proposal_item(
                proposal["id"], document["id"], "pr-unclassified", "pr-sop"
            )

    def test_apply_is_atomic_when_one_approved_item_becomes_stale(self):
        first = self.store.create_document(
            "production", "第一项", "pr-unclassified", content_hash="first"
        )
        second = self.store.create_document(
            "production", "第二项", "pr-unclassified", content_hash="second"
        )
        proposal = self.store.create_proposal("production")
        first_item = self.store.add_proposal_item(
            proposal["id"], first["id"], "pr-unclassified", "pr-platform"
        )
        second_item = self.store.add_proposal_item(
            proposal["id"], second["id"], "pr-unclassified", "pr-sop"
        )
        self.store.approve_proposal_item(proposal["id"], first_item["id"])
        self.store.approve_proposal_item(proposal["id"], second_item["id"])
        self.store.move_documents([second["id"]], "pr-vector")

        with self.assertRaises(StoreConflict):
            self.store.apply_proposal(proposal["id"])
        self.assertEqual(
            "pr-unclassified", self.store.get_document(first["id"])["primary_node_id"]
        )
        self.assertEqual(
            "approved", self.store.get_proposal(proposal["id"])["items"][0]["status"]
        )

    def test_revert_refuses_to_overwrite_later_manual_edit(self):
        document, proposal, item = self._proposal_fixture("撤销冲突")
        self.store.approve_proposal_item(proposal["id"], item["id"])
        self.store.apply_proposal(proposal["id"])
        self.store.update_document(document["id"], {"title": "人工修改后的标题"})
        with self.assertRaises(StoreConflict):
            self.store.revert_proposal(proposal["id"])
        self.assertEqual(
            "pr-platform", self.store.get_document(document["id"])["primary_node_id"]
        )

    def test_stale_worker_cannot_complete_or_fail_another_workers_job(self):
        job = self.store.queue_ingest(
            "academic", "ac-unclassified", "/kb/lease.md", "lease-key"
        )
        claimed = self.store.claim_next_job("worker-a", lease_seconds=300)
        self.assertEqual(job["id"], claimed["id"])
        with self.assertRaises(StoreConflict):
            self.store.complete_job(job["id"], "worker-b", chunks_indexed=1)
        with self.assertRaises(StoreConflict):
            self.store.fail_job(job["id"], "worker-b", "not owner")
        completed = self.store.finalize_ingest_job(
            job["id"], "worker-a", 2, "kb_academic_v1"
        )
        self.assertEqual("completed", completed["state"])
        active = self.store.get_active_version(completed["document_id"])
        self.assertEqual(completed["version_id"], active["id"])

    def test_expired_lease_consumes_retry_budget(self):
        job = self.store.queue_ingest(
            "notes", "nt-unclassified", "/kb/expired.md", "expired-key"
        )
        self.store.claim_next_job("worker-expired", lease_seconds=300)
        conn = self.store._connect()
        conn.execute(
            """UPDATE ingest_jobs SET lease_until = '2000-01-01T00:00:00+00:00',
               max_retries = 1 WHERE id = ?""",
            (job["id"],),
        )
        conn.commit()
        conn.close()
        self.assertEqual(1, self.store.release_expired_leases())
        terminal = self.store.list_jobs("notes")[0]
        self.assertEqual("failed", terminal["state"])
        self.assertEqual(1, terminal["retry_count"])


if __name__ == "__main__":
    unittest.main()
