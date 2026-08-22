"""Persistent, host-process job tracking for aircraft training and evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import uuid
from typing import Any, Iterable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AircraftTrainingJobStore:
    """Small JSON-backed job store suitable for one Image-Mate backend process."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / "jobs.json"
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._normalize_interrupted_jobs()

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write(self, jobs: dict[str, dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            json.dump(jobs, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(self.path)

    def _normalize_interrupted_jobs(self) -> None:
        with self.lock:
            jobs = self._read()
            changed = False
            for job in jobs.values():
                if job.get("status") in {"queued", "running"}:
                    job.update(
                        {
                            "status": "interrupted",
                            "message": "The backend restarted before this job completed.",
                            "updated_at": _now(),
                            "finished_at": _now(),
                        }
                    )
                    changed = True
            if changed:
                self._write(jobs)

    def create(self, *, kind: str, payload: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        with self.lock:
            jobs = self._read()
            job_id = str(uuid.uuid4())
            now = _now()
            job = {
                "job_id": job_id,
                "kind": str(kind),
                "status": "queued",
                "progress": 0,
                "message": "Queued.",
                "error": "",
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
                "output_dir": str(Path(output_dir).expanduser().resolve()),
                "payload": dict(payload),
                "logs": "",
            }
            jobs[job_id] = job
            self._write(jobs)
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self._read().get(str(job_id))
            return dict(job) if isinstance(job, dict) else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            jobs = list(self._read().values())
        jobs.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return [dict(job) for job in jobs[: max(1, min(int(limit), 200))]]

    def update(self, job_id: str, **updates: Any) -> dict[str, Any] | None:
        with self.lock:
            jobs = self._read()
            job = jobs.get(str(job_id))
            if not isinstance(job, dict):
                return None
            job.update(updates)
            job["updated_at"] = _now()
            self._write(jobs)
            return dict(job)


def run_job_command(
    store: AircraftTrainingJobStore,
    job_id: str,
    command: Iterable[str],
    *,
    cwd: Path,
    summary_path: Path,
) -> None:
    """Run a host command in a daemon thread and persist its outcome."""

    command_list = [str(value) for value in command]
    store.update(job_id, status="running", started_at=_now(), message="Running on the configured host training runtime.", command=command_list)
    output_lines: list[str] = []
    try:
        process = subprocess.Popen(
            command_list,
            cwd=str(Path(cwd).expanduser().resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            output_lines.append(line.rstrip())
            if len(output_lines) > 400:
                output_lines.pop(0)
            store.update(job_id, logs="\n".join(output_lines[-200:]))
        return_code = process.wait()
    except Exception as exc:
        store.update(
            job_id,
            status="failed",
            error=str(exc)[:1000],
            message="Could not start the host training command.",
            finished_at=_now(),
            logs="\n".join(output_lines[-200:]),
        )
        return

    summary: dict[str, Any] | None = None
    if Path(summary_path).is_file():
        try:
            parsed = json.loads(Path(summary_path).read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                summary = parsed
        except (OSError, ValueError):
            summary = None
    succeeded = return_code == 0
    store.update(
        job_id,
        status="succeeded" if succeeded else "failed",
        progress=100 if succeeded else 0,
        message="Completed." if succeeded else "Host command failed.",
        error="" if succeeded else ("\n".join(output_lines[-20:]) or f"Command exited with status {return_code}"),
        finished_at=_now(),
        logs="\n".join(output_lines[-200:]),
        summary=summary,
        return_code=return_code,
    )
