"""src-python/api/ — FastAPI route modules.

One module per endpoint group; each exports a `router` that server.py
registers via app.include_router.  Splitting the route surface into
separate files keeps each concern small (~100-300 lines) and makes it
easy to grep for a specific endpoint by its file name.

Modules
───────
  upload.py    — POST /upload (file ingest + ffmpeg extraction for video)
  slurmify.py  — POST /slurmify, GET /jobs/{id}/progress, GET /jobs/{id}
  fx.py        — POST /burn-fx (job pattern same as slurmify)
  render.py    — POST /render-video (job pattern same as slurmify)
  files.py     — GET /files/{id} with HTTP range support, GET /files/{id}/download
"""
