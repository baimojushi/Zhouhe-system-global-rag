import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from ingest_layout import ensure_layout, library_folder
    from ingest_service import queue_ingest_file
    from knowledge_store import KnowledgeStore
    from post_parse_filename import (
        canonical_filename,
        collision_safe_target,
        read_mineru_evidence,
        recover_pending_file_renames,
        rename_after_mineru,
    )
    NORMALIZER_MODULE = "post_parse_filename"
except ImportError:
    from backend.ingest_layout import ensure_layout, library_folder
    from backend.ingest_service import queue_ingest_file
    from backend.knowledge_store import KnowledgeStore
    from backend.post_parse_filename import (
        canonical_filename,
        collision_safe_target,
        read_mineru_evidence,
        recover_pending_file_renames,
        rename_after_mineru,
    )
    NORMALIZER_MODULE = "backend.post_parse_filename"


PROPOSAL = {
    "decision": "rename",
    "document_type": "paper",
    "title": "Evidence-Aware Retrieval for Long Documents",
    "creator": "Li Ming",
    "year": "2025",
    "edition": "",
    "confidence": 0.96,
    "reason": "论文首页给出标题、作者与年份",
}


class PostParseFilenameTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "RAG"
        self.artifact = Path(self.temp.name) / "artifact"
        self.artifact.mkdir()
        (self.artifact / "document.md").write_text(
            "# Evidence-Aware Retrieval for Long Documents\n\n"
            "Li Ming\n\n2025\n\nAbstract\n" + "research evidence " * 30,
            encoding="utf-8",
        )
        (self.artifact / "content_list.json").write_text(
            json.dumps([{"type": "text", "page_idx": 0, "text": "Title page and abstract"}]),
            encoding="utf-8",
        )
        self.db = Path(self.temp.name) / "control.db"
        self.store = KnowledgeStore(self.db)
        ensure_layout(self.root)
        self.env = patch.dict(os.environ, {
            "RAG_INGEST_ROOTS": str(self.root),
            "RAG_PDF_AUTO_RENAME": "true",
            "RAG_PDF_RENAME_MIN_CONFIDENCE": "0.82",
            "RAG_PDF_RENAME_LOCK_FILE": str(Path(self.temp.name) / "rename.lock"),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _claimed_job(self, filename: str = "download_final_123 (1).pdf"):
        source = library_folder("academic", self.root) / filename
        source.write_bytes(b"%PDF-1.7\npost-parse-test")
        queued, _ = queue_ingest_file(
            self.store, source, "academic", "ac-unclassified", "test"
        )
        claimed = self.store.claim_next_job("worker-test", 300)
        self.assertEqual(queued["id"], claimed["id"])
        return source.resolve(), claimed

    def test_reads_bounded_mineru_artifacts(self):
        evidence = read_mineru_evidence(str(self.artifact), max_chars=1000)
        self.assertIn("Evidence-Aware", evidence["markdown_excerpt"])
        self.assertEqual(evidence["content_blocks"][0]["page"], 0)

    def test_canonical_visual_format_and_validation(self):
        name, confidence, _ = canonical_filename(PROPOSAL)
        self.assertEqual(
            name,
            "[论文] Evidence-Aware Retrieval for Long Documents - Li Ming - 2025.pdf",
        )
        self.assertEqual(confidence, 0.96)
        with self.assertRaises(ValueError):
            canonical_filename(dict(PROPOSAL, confidence=0.4))

    @patch(f"{NORMALIZER_MODULE}.request_gemma_filename", return_value=(PROPOSAL, "gemma-test"))
    def test_renames_after_parse_and_synchronizes_all_paths(self, _gemma):
        old_path, job = self._claimed_job()
        updated, outcome = rename_after_mineru(self.store, job, str(self.artifact))
        new_path = Path(updated["source_path"])
        self.assertEqual(outcome.state, "applied")
        self.assertFalse(old_path.exists())
        self.assertTrue(new_path.exists())
        self.assertTrue(new_path.name.startswith("[论文] Evidence-Aware"))

        document = self.store.get_document(job["document_id"])
        self.assertEqual(document["source_path"], str(new_path))
        self.assertEqual(document["source_name"], new_path.name)
        self.assertEqual(document["title"], new_path.stem)
        versions = self.store.list_versions(job["document_id"])
        current = next(item for item in versions if item["id"] == job["version_id"])
        self.assertEqual(current["source_uri"], str(new_path))

        # The rewritten idempotency key prevents the next 5-minute scan from
        # creating a duplicate version merely because the physical path changed.
        repeated, state = queue_ingest_file(
            self.store, new_path, "academic", "ac-unclassified", "test"
        )
        self.assertEqual(state, "existing")
        self.assertEqual(repeated["id"], job["id"])
        self.assertEqual(self.store.list_file_rename_events("academic")[0]["state"], "applied")

    @patch(f"{NORMALIZER_MODULE}.request_gemma_filename", side_effect=RuntimeError("offline"))
    def test_gemma_failure_keeps_original_and_allows_indexing(self, _gemma):
        source, job = self._claimed_job("unclear.pdf")
        updated, outcome = rename_after_mineru(self.store, job, str(self.artifact))
        self.assertEqual(outcome.state, "skipped")
        self.assertEqual(updated["source_path"], str(source))
        self.assertTrue(source.exists())
        self.assertEqual(self.store.list_file_rename_events("academic")[0]["state"], "skipped")

    def test_collision_uses_deterministic_hash_and_never_overwrites(self):
        source, _job = self._claimed_job("source.pdf")
        target = source.with_name("[论文] Existing.pdf")
        target.write_bytes(b"do-not-overwrite")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        safe = collision_safe_target(source, target.name, digest)
        self.assertRegex(safe.name, r"^\[论文\] Existing \[[0-9a-f]{8}\]\.pdf$")
        self.assertEqual(target.read_bytes(), b"do-not-overwrite")
        safe.write_bytes(b"first-collision")
        second_safe = collision_safe_target(source, target.name, digest)
        self.assertRegex(
            second_safe.name, r"^\[论文\] Existing \[[0-9a-f]{8}-2\]\.pdf$"
        )
        self.assertEqual(safe.read_bytes(), b"first-collision")

    def test_recovers_crash_between_disk_rename_and_database_commit(self):
        source, job = self._claimed_job("crash-window.pdf")
        proposed_name, confidence, reason = canonical_filename(PROPOSAL)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        target = collision_safe_target(source, proposed_name, digest)
        event = self.store.create_file_rename_event(
            job, digest, str(source), str(target), source.name, target.name,
            "proposed", "gemma-test", confidence, reason, "{}", "test",
        )
        source.rename(target)  # Simulate process death immediately after this line.
        self.assertEqual(event["state"], "proposed")

        recovered = recover_pending_file_renames(self.store)
        self.assertEqual(recovered, 1)
        current = self.store.list_jobs("academic")[0]
        self.assertEqual(current["source_path"], str(target))
        self.assertEqual(
            self.store.list_file_rename_events("academic")[0]["state"], "applied"
        )


if __name__ == "__main__":
    unittest.main()
