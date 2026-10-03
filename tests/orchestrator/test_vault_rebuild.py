"""T-3: POST /v1/vault/rebuild returns rebuilt index (FASE 11)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import jarvis_os.orchestrator as orch_mod
from jarvis_os.orchestrator import app


def _write_wiki_note(path: Path, note_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f'id: "{note_id}"\n'
        f'title: "{note_id}"\n'
        'tags: ["skill"]\n'
        'created: "2026-10-02T10:00:00+00:00"\n'
        'modified: "2026-10-02T10:00:00+00:00"\n'
        "---\n\nNote for rebuild endpoint test.\n",
        encoding="utf-8",
    )


def test_vault_rebuild_returns_success(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    _write_wiki_note(vault / "wiki" / "note-a.md", "note-a")

    monkeypatch.setattr(
        orch_mod,
        "get_settings",
        lambda: SimpleNamespace(vault=SimpleNamespace(vault_root=vault)),
    )
    client = TestClient(app)
    response = client.post("/v1/vault/rebuild")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert (vault / "wiki" / ".boveda_index.json").exists()
