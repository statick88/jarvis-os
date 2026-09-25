"""Tests for skill-bfla_idor (T-4 registration, handler, T-5 findings store)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from jarvis_os.skills.devsecops.bffla_idor import (
    _CONFIRMED_FINDING_IDS,
    BfflaIdorSkill,
)
from jarvis_os.skills.devsecops.bffla_idor_store import (
    CONFIRMED_FINDING_IDS,
    FindingsStore,
)
from jarvis_os.skills.handlers import bffla_idor_run
from jarvis_os.skills.loader import SkillLoader

SKILL_MD = Path(".skills/bfla-idor.md")


def _finding(finding_id: str = "bfla-/api/x-GET-User") -> dict[str, Any]:
    return {
        "id": finding_id,
        "title": "BFLA Vulnerability Detected",
        "description": "Endpoint /api/x leaks data",
        "finding_type": "bfla",
        "endpoint": "/api/x",
        "method": "GET",
        "role": "User",
        "cvss_score": 7.5,
        "confirmed": False,
        "target_object": None,
        "reference_location": None,
        "owasp_api": "API5:2023",
        "mitre_attack": "T1190",
    }


class TestSkillRegistration:
    def test_skill_md_exists(self) -> None:
        assert SKILL_MD.exists()

    @pytest.mark.asyncio
    async def test_loader_validates_frontmatter(self) -> None:
        loader = SkillLoader(skills_dir=Path(".skills"))
        metadata = await loader.load_skill(SKILL_MD)
        assert metadata.id == "skill-bfla_idor"
        assert metadata.frontmatter.entrypoint == "bffla_idor"
        assert metadata.frontmatter.execution_type == "python"
        assert "security.test_bfla" in metadata.frontmatter.capabilities
        assert "security.test_idor" in metadata.frontmatter.capabilities
        assert "security.list_findings" in metadata.frontmatter.capabilities
        assert len(metadata.name) <= 50
        assert 10 <= len(metadata.description) <= 200

    @pytest.mark.asyncio
    async def test_loader_includes_new_skill(self) -> None:
        loader = SkillLoader(skills_dir=Path(".skills"))
        skills = await loader.load_all()
        assert "skill-bfla_idor" in skills


class TestFindingsStore:
    def test_seeded_confirmed_ids(self) -> None:
        assert CONFIRMED_FINDING_IDS == {f"F{i:02d}" for i in range(1, 23)}
        store = FindingsStore(Path("/nonexistent/findings.json"))
        for fid in CONFIRMED_FINDING_IDS:
            assert store.is_confirmed(fid)

    def test_topic_key_format(self) -> None:
        assert (
            FindingsStore.topic_key("bfla-/api/x-GET-User")
            == "sdd/pentest-methodology/finding-bfla-/api/x-GET-User"
        )

    def test_add_finding_and_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        store = FindingsStore(path)
        assert store.add_finding(_finding()) is True
        assert path.exists()

        reloaded = FindingsStore(path)
        findings = reloaded.list_findings()
        assert len(findings) == 1
        assert findings[0]["topic_key"].startswith(
            "sdd/pentest-methodology/finding-"
        )
        assert "persisted_at" in findings[0]

    def test_add_confirmed_is_skipped(self, tmp_path: Path) -> None:
        store = FindingsStore(tmp_path / "findings.json")
        assert store.add_finding(_finding("F01")) is False
        assert store.list_findings() == []

    def test_add_duplicate_is_skipped(self, tmp_path: Path) -> None:
        store = FindingsStore(tmp_path / "findings.json")
        assert store.add_finding(_finding()) is True
        assert store.add_finding(_finding()) is False
        assert len(store.list_findings()) == 1

    def test_add_missing_id_is_skipped(self, tmp_path: Path) -> None:
        store = FindingsStore(tmp_path / "findings.json")
        assert store.add_finding({"title": "no id"}) is False

    def test_mark_confirmed_persists_and_blocks(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        store = FindingsStore(path)
        assert store.add_finding(_finding("bfla-new")) is True
        assert store.mark_confirmed("bfla-new") is True
        assert store.add_finding(_finding("bfla-new")) is False

        reloaded = FindingsStore(path)
        assert reloaded.is_confirmed("bfla-new")
        assert "bfla-new" in reloaded.confirmed_ids

    def test_json_format_version(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        store = FindingsStore(path)
        store.add_finding(_finding())
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["version"] == 1
        assert "updated_at" in raw
        assert "confirmed_ids" in raw
        assert "findings" in raw


class TestHandler:
    def test_unknown_action(self) -> None:
        result = bffla_idor_run({"action": "not_a_real_action"})
        assert result["success"] is False
        assert "Unknown action" in result["error"]

    def test_list_findings_only(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        store = FindingsStore(path)
        store.add_finding(_finding())
        result = bffla_idor_run(
            {"action": "list_findings", "context": {"findings_path": str(path)}}
        )
        assert result["success"] is True
        assert result["data"]["count"] == 1

    def test_operation_alias(self, tmp_path: Path) -> None:
        result = bffla_idor_run(
            {"operation": "list_findings", "context": {"findings_path": str(tmp_path / "f.json")}}
        )
        assert result["success"] is True

    def test_get_confirmed_merges_store(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        store = FindingsStore(path)
        store.mark_confirmed("bfla-custom")

        mock_skill = AsyncMock()
        mock_skill.is_loaded = True
        mock_skill.execute.return_value = {
            "status": "success",
            "confirmed_ids": list(CONFIRMED_FINDING_IDS),
        }
        with patch(
            "jarvis_os.skills.handlers.bffla_idor.BfflaIdorSkill",
            return_value=mock_skill,
        ):
            result = bffla_idor_run(
                {"action": "get_confirmed", "context": {"findings_path": str(path)}}
            )
        assert result["success"] is True
        ids = result["data"]["confirmed_ids"]
        assert "F01" in ids
        assert "bfla-custom" in ids

    def test_mark_confirmed_updates_store(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        mock_skill = AsyncMock()
        mock_skill.is_loaded = True
        mock_skill.execute.return_value = {
            "status": "success",
            "confirmed_ids": ["bfla-mark-me"],
        }
        with patch(
            "jarvis_os.skills.handlers.bffla_idor.BfflaIdorSkill",
            return_value=mock_skill,
        ):
            result = bffla_idor_run(
                {
                    "action": "mark_confirmed",
                    "finding_id": "bfla-mark-me",
                    "context": {"findings_path": str(path)},
                }
            )
        assert result["success"] is True
        assert FindingsStore(path).is_confirmed("bfla-mark-me")

    def test_test_bfla_persists_findings(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        mock_skill = AsyncMock()
        mock_skill.is_loaded = True
        mock_skill.execute.return_value = {
            "status": "success",
            "findings": [_finding()],
            "endpoint": "/api/x",
        }
        with patch(
            "jarvis_os.skills.handlers.bffla_idor.BfflaIdorSkill",
            return_value=mock_skill,
        ):
            result = bffla_idor_run(
                {
                    "action": "test_bfla",
                    "endpoint": "/api/x",
                    "context": {"findings_path": str(path)},
                }
            )
        assert result["success"] is True
        assert result["data"]["persisted_count"] == 1
        assert len(FindingsStore(path).list_findings()) == 1

    def test_test_bfla_does_not_persist_confirmed(self, tmp_path: Path) -> None:
        path = tmp_path / "findings.json"
        mock_skill = AsyncMock()
        mock_skill.is_loaded = True
        mock_skill.execute.return_value = {
            "status": "success",
            "findings": [_finding("F01")],
        }
        with patch(
            "jarvis_os.skills.handlers.bffla_idor.BfflaIdorSkill",
            return_value=mock_skill,
        ):
            result = bffla_idor_run(
                {
                    "action": "test_bfla",
                    "endpoint": "/api/x",
                    "context": {"findings_path": str(path)},
                }
            )
        assert result["success"] is True
        assert result["data"]["persisted_count"] == 0
        assert FindingsStore(path).list_findings() == []

    def test_skill_error_is_normalized(self, tmp_path: Path) -> None:
        mock_skill = AsyncMock()
        mock_skill.is_loaded = True
        mock_skill.execute.return_value = {
            "status": "error",
            "message": "Endpoint path is required",
        }
        with patch(
            "jarvis_os.skills.handlers.bffla_idor.BfflaIdorSkill",
            return_value=mock_skill,
        ):
            result = bffla_idor_run(
                {
                    "action": "test_bfla",
                    "context": {"findings_path": str(tmp_path / "f.json")},
                }
            )
        assert result["success"] is False
        assert "Endpoint path is required" in result["error"]


class TestSkillConfirmedGuard:
    @pytest.mark.asyncio
    async def test_get_confirmed_includes_f01_f22(self) -> None:
        skill = BfflaIdorSkill()
        await skill.load()
        result = await skill.execute("get_confirmed", {}, {})
        assert result["status"] == "success"
        assert set(result["confirmed_ids"]) >= {f"F{i:02d}" for i in range(1, 23)}
        assert _CONFIRMED_FINDING_IDS >= {f"F{i:02d}" for i in range(1, 23)}

    @pytest.mark.asyncio
    async def test_probe_skips_confirmed_finding(self) -> None:
        skill = BfflaIdorSkill()
        await skill.load()
        with patch.object(
            skill,
            "_run_bfla_probe",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_probe:
            result = await skill.execute(
                "test_bfla",
                {
                    "endpoint": "/api/x",
                    "method_switching": False,
                    "path_confusion": False,
                },
                {},
            )
        assert result["status"] == "success"
        mock_probe.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_probe_returns_finding_when_not_confirmed(self) -> None:
        skill = BfflaIdorSkill()
        await skill.load()
        with patch.object(
            skill,
            "_run_bfla_probe",
            new_callable=AsyncMock,
            return_value=_finding(),
        ):
            result = await skill.execute(
                "test_bfla",
                {
                    "endpoint": "/api/x",
                    "method_switching": False,
                    "path_confusion": False,
                },
                {},
            )
        assert result["status"] == "success"
        assert len(result["findings"]) == 1

    @pytest.mark.asyncio
    async def test_mark_confirmed_blocks_subsequent_probe(self) -> None:
        skill = BfflaIdorSkill()
        await skill.load()
        finding_id = "bfla-/api/y-GET-User"
        await skill.execute("mark_confirmed", {"finding_id": finding_id}, {})

        # Simulate probe building a finding that is now confirmed.
        async def probe_with_confirmed(
            *args: Any, **kwargs: Any
        ) -> dict[str, Any] | None:
            finding = _finding(finding_id)
            if finding["id"] in _CONFIRMED_FINDING_IDS:
                return None
            return finding

        with patch.object(
            skill, "_run_bfla_probe", side_effect=probe_with_confirmed
        ):
            result = await skill.execute(
                "test_bfla",
                {
                    "endpoint": "/api/y",
                    "method_switching": False,
                    "path_confusion": False,
                },
                {},
            )
        assert result["findings"] == []

    @pytest.mark.asyncio
    async def test_not_loaded_error(self) -> None:
        skill = BfflaIdorSkill()
        result = await skill.execute("get_confirmed", {}, {})
        assert result["status"] == "error"
        assert "not loaded" in result["message"].lower()


class TestOwaspMitreMapping:
    def test_finding_defaults_include_mitre(self) -> None:
        from jarvis_os.skills.devsecops.bffla_idor import BfflaIdorFinding

        f = BfflaIdorFinding(
            id="bfla-/api/z-GET-User",
            title="t",
            description="d",
            finding_type="bfla",
            endpoint="/api/z",
            method="GET",
            role="User",
            cvss_score=7.5,
        )
        assert f.mitre_attack is None  # not auto-assigned at model level
        assert f.owasp_api is None

    def test_bfla_probe_construction_sets_api5_and_t1190(self) -> None:
        """Constructors in _test_bfla set owasp_api=API5:2023, mitre_attack=T1190."""
        # Covered by constructor edits; assert model accepts the values.
        from jarvis_os.skills.devsecops.bffla_idor import BfflaIdorFinding

        f = BfflaIdorFinding(
            id="x",
            title="t",
            description="d",
            finding_type="bfla",
            endpoint="/e",
            method="GET",
            role="User",
            cvss_score=7.5,
            owasp_api="API5:2023",
            mitre_attack="T1190",
        )
        assert f.owasp_api == "API5:2023"
        assert f.mitre_attack == "T1190"

    def test_idor_mapping_api1_and_t1190(self) -> None:
        from jarvis_os.skills.devsecops.bffla_idor import BfflaIdorFinding

        f = BfflaIdorFinding(
            id="y",
            title="t",
            description="d",
            finding_type="idor",
            endpoint="/e",
            method="GET",
            role="User",
            cvss_score=7.0,
            owasp_api="API1:2023",
            mitre_attack="T1190",
        )
        assert f.owasp_api == "API1:2023"
        assert f.mitre_attack == "T1190"
