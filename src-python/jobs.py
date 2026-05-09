"""
src-python/jobs.py — In-memory job tracker for long-running operations
─────────────────────────────────────────────────────────────────────────

Slurmify operations (slurmify, burn-fx, render-video) take seconds-to-tens-
of-seconds.  Rather than blocking an HTTP request that long (and risking
client-side timeouts), the API endpoints kick off a background task and
return a `job_id` immediately.  The frontend then subscribes to a Server-
Sent Events stream that emits progress updates until the job finishes.

This module owns the JOBS registry — a simple dict keyed by job_id.  It is
intentionally process-local (not Redis, not a DB) because:

  1. The sidecar is a single Python process; there is no "other instance"
     that needs to see the same jobs.
  2. The frontend retries by re-running the job, not by reconnecting to a
     persistent ID.  If the user reloads the app the in-flight job is
     orphaned and a new one starts — that's fine.
  3. Adding Redis / SQLite would force the user's beta build to install
     and run a second daemon.  Not worth the complexity for v0.2.0.

If we ever need to support multiple concurrent renders or resume on
reconnect, this is the place to swap in a real queue (Celery, RQ, etc.).
For now it's a dict and it's fine.

────────────────────────────────────────────────────────────────────────
Lifecycle
────────────────────────────────────────────────────────────────────────
  1. Endpoint creates a Job(), inserts it into JOBS, returns job_id.
  2. Background task mutates job.progress / job.desc / job.done.
  3. SSE endpoint reads the job and emits payloads until job.done.
  4. JOBS retains finished jobs for `JOB_TTL_SEC` so a slow client
     can still pick up the final output_id.  After that they're
     garbage-collected by `prune_expired()`.

Thread safety: writes to a single Job's fields from a single background
thread are race-free in CPython for our use (each field is a single
reference / float / bool assignment, all atomic at the bytecode level).
We are NOT writing to the same Job from multiple threads.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

# Default time-to-live for finished jobs.  After this many seconds since
# completion, prune_expired() removes them from JOBS.  Long enough that a
# user with a slow network can still GET /files/{id} after the SSE stream
# closes, but short enough that a long-running sidecar process doesn't
# accumulate a large dict of dead jobs.
JOB_TTL_SEC = 300  # 5 minutes


@dataclass
class Job:
    """One slurmify / burn-fx / render-video operation in progress.

    Fields
    ------
    id : str
        UUID4 string assigned at creation.  Used as the key in JOBS and
        the URL parameter on /jobs/{id}/...
    progress : float
        0.0 to 1.0 — fraction of the operation complete.  Updated by
        the slurmcore _progress callback; the JS frontend renders a
        progress bar from this.
    desc : str
        Human-readable current step ("Time-stretching…", "Slicing…",
        "Mixing…", "Done ✓").  Updated alongside progress.
    done : bool
        Set to True when the operation finishes, whether successfully
        or not.  The SSE stream closes on the first True.
    output_id : str | None
        Set on successful completion to the file_id of the produced
        audio / video output — the frontend uses it to GET /files/{id}.
        None on failure.
    error : str | None
        Error message on failure.  None on success.  When non-None,
        the frontend displays this as a toast or banner.
    started_at, finished_at : float
        Wall-clock timestamps for diagnostics + TTL pruning.
    """

    id:          str
    progress:    float       = 0.0
    desc:        str         = ""
    done:        bool        = False
    output_id:   str | None  = None
    error:       str | None  = None
    started_at:  float       = field(default_factory=time.time)
    finished_at: float | None = None

    # ── Serialization ───────────────────────────────────────────────────
    # The SSE payload is a JSON object.  We exclude `started_at` and
    # `finished_at` because the frontend doesn't need them — they're
    # only here for server-side diagnostics + pruning.

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":        self.id,
            "progress":  self.progress,
            "desc":      self.desc,
            "done":      self.done,
            "output_id": self.output_id,
            "error":     self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    def mark_done(self, output_id: str | None = None, error: str | None = None) -> None:
        """Idempotent finishing helper — sets the terminal flags + timestamp."""
        self.output_id   = output_id
        self.error       = error
        self.done        = True
        self.finished_at = time.time()
        # On success, force progress to 1.0 — sometimes the slurmcore
        # _progress callback doesn't quite hit it on the last step.
        if error is None:
            self.progress = 1.0


# Global registry.  module-level dict; access from any endpoint or the
# SSE generator.  A real queue would replace this; for v0.2.0 it's plenty.
JOBS: dict[str, Job] = {}


def prune_expired() -> int:
    """Drop jobs that finished more than JOB_TTL_SEC ago.

    Called opportunistically — currently from the slurmify endpoint when
    a new job starts.  Cheap (just iterates the dict), so calling it
    eagerly is fine.

    Returns the number of jobs removed (mostly for diagnostic logging).
    """
    cutoff = time.time() - JOB_TTL_SEC
    expired = [
        jid for jid, j in JOBS.items()
        if j.finished_at is not None and j.finished_at < cutoff
    ]
    for jid in expired:
        del JOBS[jid]
    return len(expired)
