import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from ingest_layout import ensure_layout, library_folder
    from ingest_service import scan_ingest_folders
    from knowledge_store import KnowledgeStore
except ImportError:
    from backend.ingest_layout import ensure_layout, library_folder
    from backend.ingest_service import scan_ingest_folders
    from backend.knowledge_store import KnowledgeStore


class IngestServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "RAG"
        self.db = Path(self.temp.name) / "control.db"
        self.store = KnowledgeStore(self.db)
        ensure_layout(self.root)
        self.env = patch.dict("os.environ", {"RAG_INGEST_ROOTS": str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_stable_file_is_queued_to_library_unclassified(self):
        source = library_folder("production", self.root) / "说明.md"
        source.write_text("稳定内容", encoding="utf-8")
        result = scan_ingest_folders(
            self.store,
            library_id="production",
            stability_seconds=30,
            wait_fn=lambda _seconds: False,
        )
        self.assertEqual(result["submitted_count"], 1)
        document = self.store.get_document(result["jobs"][0]["document_id"])
        self.assertEqual(document["primary_node_id"], "pr-unclassified")

    def test_changed_during_stability_window_is_deferred(self):
        source = library_folder("academic", self.root) / "论文.md"
        source.write_text("first", encoding="utf-8")

        def mutate(_seconds):
            source.write_text("second and longer", encoding="utf-8")
            return False

        result = scan_ingest_folders(
            self.store,
            library_id="academic",
            stability_seconds=30,
            wait_fn=mutate,
        )
        self.assertEqual(result["submitted_count"], 0)
        self.assertEqual(result["unstable_count"], 1)

    def test_repeat_scan_reuses_idempotent_job(self):
        source = library_folder("notes", self.root) / "想法.md"
        source.write_text("same", encoding="utf-8")
        first = scan_ingest_folders(self.store, library_id="notes")
        second = scan_ingest_folders(self.store, library_id="notes")
        self.assertEqual(first["jobs"][0]["job_id"], second["jobs"][0]["job_id"])
        self.assertEqual(len(self.store.list_jobs("notes")), 1)

    def test_shutdown_interrupts_stability_window(self):
        source = library_folder("ai-work", self.root) / "记录.md"
        source.write_text("content", encoding="utf-8")
        result = scan_ingest_folders(
            self.store,
            library_id="ai-work",
            stability_seconds=30,
            wait_fn=lambda _seconds: True,
        )
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["submitted_count"], 0)


if __name__ == "__main__":
    unittest.main()
