#!/usr/bin/env python3
"""MinerU HTTP API client — submit, poll, and fetch parse results.

Uses the async ``/tasks`` endpoint as the primary path; ``/file_parse``
is available for small/sync use cases.

Environment variables:
  RAG_MINERU_API_URL     — MinerU API base URL (default: http://127.0.0.1:18000)
  RAG_MINERU_POLL_INTERVAL — seconds between status polls (default: 5)
  RAG_MINERU_MAX_PARSE_SECONDS — max wall-clock seconds per task (default: 3600)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger("mineru_client")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINERU_API_URL = os.environ.get(
    "RAG_MINERU_API_URL", "http://127.0.0.1:18000"
)
POLL_INTERVAL = float(os.environ.get("RAG_MINERU_POLL_INTERVAL", "5"))
MAX_PARSE_SECONDS = int(os.environ.get("RAG_MINERU_MAX_PARSE_SECONDS", "3600"))
SUBMIT_TIMEOUT = int(os.environ.get("RAG_MINERU_SUBMIT_TIMEOUT_SECONDS", "300"))
POLL_TIMEOUT = int(os.environ.get("RAG_MINERU_POLL_TIMEOUT_SECONDS", "10"))


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MinerUTaskStatus:
    """Reflects the MinerU task status response."""
    task_id: str
    status: str  # pending / processing / completed / failed
    backend: str = ""
    file_names: list[str] = field(default_factory=list)
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    queued_ahead: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")

    @property
    def is_success(self) -> bool:
        return self.status == "completed"


@dataclass
class MinerUParseResult:
    """Parsed document result from MinerU."""
    task_id: str
    backend: str
    version: str
    md_content: str = ""
    content_list: list[Any] = field(default_factory=list)
    middle_json: dict[str, Any] = field(default_factory=dict)
    model_output: dict[str, Any] = field(default_factory=dict)
    images: dict[str, bytes] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MinerUError(RuntimeError):
    """Base MinerU client error."""


class MinerUConnectionError(MinerUError):
    """Cannot reach the MinerU API server."""


class MinerUTimeoutError(MinerUError):
    """Task exceeded the maximum allowed parse time."""


class MinerUTaskFailedError(MinerUError):
    """MinerU reported task failure."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MinerUClient:
    """HTTP client for the MinerU document parsing API."""

    def __init__(
        self,
        base_url: str = MINERU_API_URL,
        poll_interval: float = POLL_INTERVAL,
        max_parse_seconds: int = MAX_PARSE_SECONDS,
        submit_timeout: int = SUBMIT_TIMEOUT,
        poll_timeout: int = POLL_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.max_parse_seconds = max_parse_seconds
        self.submit_timeout = submit_timeout
        self.poll_timeout = poll_timeout

    # -- Health check -------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Check MinerU API health. Raises MinerUConnectionError on failure."""
        try:
            resp = httpx.get(
                f"{self.base_url}/health",
                timeout=min(self.submit_timeout, 10),
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.RequestError as exc:
            raise MinerUConnectionError(
                f"Cannot reach MinerU at {self.base_url}: {exc}"
            ) from exc

    # -- Async task submission ----------------------------------------------

    def submit_task(
        self,
        file_path: str,
        backend: str = "hybrid-engine",
        effort: str = "medium",
        lang_list: Optional[list[str]] = None,
        parse_method: str = "auto",
        formula_enable: bool = True,
        table_enable: bool = True,
        image_analysis: bool = False,
        return_md: bool = True,
        return_content_list: bool = False,
        return_middle_json: bool = False,
        return_model_output: bool = False,
        return_images: bool = False,
        start_page_id: int = 0,
        end_page_id: int = 99999,
    ) -> MinerUTaskStatus:
        """Submit a file for async parsing via POST /tasks.

        Returns the initial task status with a ``task_id`` for polling.
        """
        path = Path(file_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise MinerUError(f"File not found: {file_path}")

        data: dict[str, Any] = {
            "backend": backend,
            "effort": effort,
            "parse_method": parse_method,
            "formula_enable": str(formula_enable).lower(),
            "table_enable": str(table_enable).lower(),
            "image_analysis": str(image_analysis).lower(),
            "return_md": str(return_md).lower(),
            "return_content_list": str(return_content_list).lower(),
            "return_middle_json": str(return_middle_json).lower(),
            "return_model_output": str(return_model_output).lower(),
            "return_images": str(return_images).lower(),
            "start_page_id": str(start_page_id),
            "end_page_id": str(end_page_id),
        }
        if lang_list:
            data["lang_list"] = ",".join(lang_list)

        try:
            with path.open("rb") as fh:
                files = {"files": (path.name, fh, "application/pdf")}
                resp = httpx.post(
                    f"{self.base_url}/tasks",
                    data=data,
                    files=files,
                    timeout=self.submit_timeout,
                )
            resp.raise_for_status()
            body = resp.json()
            return MinerUTaskStatus(
                task_id=body.get("task_id", ""),
                status=body.get("status", "pending"),
                backend=body.get("backend", backend),
                file_names=body.get("file_names", [path.name]),
                created_at=body.get("created_at", ""),
                queued_ahead=body.get("queued_ahead", 0),
                raw=body,
            )
        except httpx.RequestError as exc:
            raise MinerUConnectionError(
                f"Failed to submit task to MinerU: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise MinerUError(
                f"MinerU returned {exc.response.status_code}: {exc.response.text}"
            ) from exc

    # -- Task status polling ------------------------------------------------

    def get_task_status(self, task_id: str) -> MinerUTaskStatus:
        """Get the current status of an async parse task."""
        try:
            resp = httpx.get(
                f"{self.base_url}/tasks/{task_id}",
                timeout=self.poll_timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            return MinerUTaskStatus(
                task_id=body.get("task_id", task_id),
                status=body.get("status", "unknown"),
                backend=body.get("backend", ""),
                file_names=body.get("file_names", []),
                created_at=body.get("created_at", ""),
                started_at=body.get("started_at", ""),
                completed_at=body.get("completed_at", ""),
                error=body.get("error", ""),
                queued_ahead=body.get("queued_ahead", 0),
                raw=body,
            )
        except httpx.RequestError as exc:
            raise MinerUConnectionError(
                f"Failed to poll task {task_id}: {exc}"
            ) from exc

    def poll_until_complete(
        self,
        task_id: str,
        max_seconds: Optional[int] = None,
    ) -> MinerUTaskStatus:
        """Poll task status until terminal or timeout. Returns final status."""
        deadline = time.time() + (max_seconds or self.max_parse_seconds)
        queued_deadline = time.time() + 600  # max 10 min waiting in queue
        last_status: Optional[MinerUTaskStatus] = None
        while time.time() < deadline:
            status = self.get_task_status(task_id)
            last_status = status
            if status.is_terminal:
                return status
            # If still pending with tasks ahead for too long, give up
            if status.status == "pending" and not status.started_at:
                if time.time() > queued_deadline:
                    raise MinerUTimeoutError(
                        f"Task {task_id} has been queued for >10 min "
                        f"(ahead={status.queued_ahead}). "
                        f"Last status: {status.status}"
                    )
            time.sleep(self.poll_interval)

        raise MinerUTimeoutError(
            f"Task {task_id} did not complete within "
            f"{max_seconds or self.max_parse_seconds}s. "
            f"Last status: {last_status.status if last_status else 'unknown'}"
        )

    # -- Result fetching ----------------------------------------------------

    def get_task_result(self, task_id: str) -> MinerUParseResult:
        """Fetch the completed task result.

        Returns structured parse result. Raises MinerUError if the task
        is not yet complete or has failed.
        """
        try:
            resp = httpx.get(
                f"{self.base_url}/tasks/{task_id}/result",
                timeout=self.poll_timeout,
            )
            resp.raise_for_status()
            body = resp.json()
        except httpx.RequestError as exc:
            raise MinerUConnectionError(
                f"Failed to fetch result for task {task_id}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise MinerUError(
                f"Result fetch returned {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc

        result = MinerUParseResult(
            task_id=task_id,
            backend=body.get("backend", ""),
            version=body.get("version", ""),
            raw=body,
        )

        # Extract per-file results
        results = body.get("results", {})
        for fname, fresult in results.items():
            if isinstance(fresult, dict):
                result.md_content = fresult.get("md_content", "")
                result.content_list = fresult.get("content_list", [])
                result.middle_json = fresult.get("middle_json", {})
                result.model_output = fresult.get("model_output", {})
                # Images are returned as base64 in the JSON when return_images=True
                if "images" in fresult:
                    result.images = fresult["images"]
            break  # Only process the first file for now

        return result

    # -- Sync parse (small files) -------------------------------------------

    def parse_sync(
        self,
        file_path: str,
        **kwargs: Any,
    ) -> MinerUParseResult:
        """Submit a file via /file_parse (synchronous) and return the result.

        Suitable for small files (<10 pages) or admin/manual use.
        For production pipelines, prefer ``submit_task`` + ``poll_until_complete``.
        """
        path = Path(file_path).expanduser().resolve(strict=True)
        if not path.is_file():
            raise MinerUError(f"File not found: {file_path}")

        data: dict[str, Any] = {
            "backend": kwargs.get("backend", "hybrid-engine"),
            "effort": kwargs.get("effort", "medium"),
            "return_md": "true",
        }
        for key in ("return_content_list", "return_middle_json",
                     "return_model_output", "return_images",
                     "formula_enable", "table_enable", "image_analysis"):
            if key in kwargs:
                data[key] = str(kwargs[key]).lower()

        try:
            with path.open("rb") as fh:
                files = {"files": (path.name, fh, "application/pdf")}
                resp = httpx.post(
                    f"{self.base_url}/file_parse",
                    data=data,
                    files=files,
                    timeout=self.max_parse_seconds,
                )
            resp.raise_for_status()
            body = resp.json()
        except httpx.RequestError as exc:
            raise MinerUConnectionError(
                f"Sync parse failed: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise MinerUError(
                f"Sync parse returned {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc

        result = MinerUParseResult(
            task_id="",
            backend=body.get("backend", kwargs.get("backend", "hybrid-engine")),
            version=body.get("version", ""),
            raw=body,
        )
        results = body.get("results", {})
        for fname, fresult in results.items():
            if isinstance(fresult, dict):
                result.md_content = fresult.get("md_content", "")
                result.content_list = fresult.get("content_list", [])
            break
        return result

    # -- Convenience: submit + poll + fetch ---------------------------------

    def parse(
        self,
        file_path: str,
        **kwargs: Any,
    ) -> MinerUParseResult:
        """Full pipeline: submit async task, poll until complete, fetch result.

        This is the recommended entry point for production use.
        """
        submitted = self.submit_task(file_path, **kwargs)
        final = self.poll_until_complete(submitted.task_id)
        if final.status == "failed":
            raise MinerUTaskFailedError(
                f"MinerU task {final.task_id} failed: {final.error}"
            )
        return self.get_task_result(final.task_id)
