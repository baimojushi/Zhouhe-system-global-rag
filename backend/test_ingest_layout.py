import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from ingest_layout import (
        LIBRARY_FOLDERS,
        ensure_layout,
        ingest_root,
        iter_library_files,
        layout_status,
        library_folder,
    )
except ImportError:
    from backend.ingest_layout import (
        LIBRARY_FOLDERS,
        ensure_layout,
        ingest_root,
        iter_library_files,
        layout_status,
        library_folder,
    )


class IngestLayoutTest(unittest.TestCase):
    def test_default_root_is_windows_e_drive_in_wsl(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(str(ingest_root()), "/mnt/e/RAG")

    def test_ensure_creates_four_document_libraries_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "RAG"
            result = ensure_layout(root)
            self.assertEqual(len(result["libraries"]), 4)
            self.assertTrue(all((root / item["folder_name"]).is_dir() for item in LIBRARY_FOLDERS))
            self.assertFalse((root / "关联知识库").exists())

    def test_scan_is_recursive_and_filters_unsupported_hidden_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "RAG"
            ensure_layout(root)
            folder = library_folder("production", root)
            (folder / "子目录").mkdir()
            (folder / "说明.md").write_text("ok", encoding="utf-8")
            (folder / "子目录" / "脚本.py").write_text("print(1)", encoding="utf-8")
            (folder / "图片.png").write_bytes(b"not indexed")
            (folder / ".hidden.md").write_text("hidden", encoding="utf-8")
            outside = root / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            try:
                (folder / "escape.md").symlink_to(outside)
            except OSError:
                pass
            names = [item.name for item in iter_library_files("production", root)]
            self.assertEqual(names, ["脚本.py", "说明.md"])

    def test_association_library_has_no_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                library_folder("association", Path(temp))

    def test_layout_status_exposes_windows_and_wsl_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            result = ensure_layout(Path(temp) / "RAG")
            self.assertEqual(result["windows_root"], r"E:\RAG")
            self.assertTrue(result["libraries"][0]["windows_path"].startswith("E:\\RAG\\"))


if __name__ == "__main__":
    unittest.main()
