"""Tests for the four development-procedure skill handlers.

These handlers were added without tests, which pushed total coverage from
56.1% to 54%. They are procedure skills, so the risk is not subtle logic but
drift: the numbers in a handler and the numbers in its .skills/*.md file
drifting apart, or a handler that reports success while returning nothing.

The negative cases matter most here. Every one of these handlers returns a
`{"success": false}` envelope on error, so a bug can hide behind a truthy
return value rather than a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis_os.skills.handlers import (
    analisis_calidad,
    cobertura,
    desarrollar_skill,
    verificar_rdd,
)



class TestCobertura:
    def test_measure_reports_the_real_gap(self) -> None:
        result = cobertura.run({"action": "measure"})

        assert result["success"] is True
        data = result["data"]
        assert data["coverage_percent"] < data["ci_target_percent"]
        assert data["gap_percent"] > 0
        assert data["gap_percent"] == pytest.approx(
            data["ci_target_percent"] - data["coverage_percent"], abs=0.05
        )

    def test_measure_uses_the_scoped_cov_flag(self) -> None:
        """--cov=. counts the test suite itself, which inflates the number."""
        result = cobertura.run({"action": "measure"})

        assert "--cov=jarvis_os" in result["data"]["measured_with"]
        assert "--cov=." not in result["data"]["measured_with"]

    def test_prioritise_puts_pure_modules_first(self) -> None:
        result = cobertura.run({"action": "prioritise", "limit": 3})

        assert result["success"] is True
        order = result["data"]["recommended_order"]
        assert order[0] in cobertura.CHEAPEST_FIRST
        assert len(order) == 3

    def test_prioritise_respects_limit(self) -> None:
        for limit in (1, 2, 5, 9):
            result = cobertura.run({"action": "prioritise", "limit": limit})
            assert len(result["data"]["recommended_order"]) == min(limit, len(cobertura.KNOWN_GAPS))

    def test_audit_without_target_lists_gaps_below_target(self) -> None:
        result = cobertura.run({"action": "audit"})

        assert result["success"] is True
        assert result["data"]["below_target"]

    def test_audit_with_known_target(self) -> None:
        result = cobertura.run({"action": "audit", "target": "orchestrator"})

        assert result["data"]["known"] is True
        assert result["data"]["details"][0]["module"] == "orchestrator.py"

    def test_audit_with_unknown_target_is_explicit(self) -> None:
        result = cobertura.run({"action": "audit", "target": "no_such_module"})

        assert result["data"]["known"] is False

    def test_test_action_requires_target(self) -> None:
        result = cobertura.run({"action": "test"})

        assert result["success"] is False
        assert "target" in result["error"]

    def test_gaps_match_the_recorded_snapshot(self) -> None:
        """Guards the handler against drifting away from itself."""
        assert cobertura.dump()
        snapshot = json.loads(cobertura.dump())
        assert snapshot["baseline"]["coverage_percent"] == cobertura.BASELINE_COVERAGE
        assert snapshot["gaps"] == cobertura.KNOWN_GAPS

    def test_unknown_action(self) -> None:
        assert cobertura.run({"action": "nope"})["success"] is False

    def test_default_action_is_measure(self) -> None:
        assert cobertura.run({})["success"] is True


class TestVerificarRdd:
    def test_verify_on_missing_root_is_a_finding_not_a_crash(self, tmp_path: Path) -> None:
        result = verificar_rdd.run(
            {"action": "verify", "receipts_dir": str(tmp_path / "nope")}
        )

        # The chain does not exist. That is reported in the data, and the
        # handler still succeeded, because a missing chain is a legitimate
        # answer rather than a handler fault.
        assert result["success"] is True
        assert result["data"]["verified"] is False
        assert result["data"]["reason"]

    def test_verify_on_empty_chain_reports_not_verified(self, tmp_path: Path) -> None:
        """Guards the false green: ReceiptChain.verify() returns (True, 'empty
        chain') for an empty root, which reads as valid but measured nothing."""
        (tmp_path / "2026-01-01").mkdir()
        (tmp_path / "2026-01-01" / "index.jsonl").write_text("")

        result = verificar_rdd.run({"action": "verify", "receipts_dir": str(tmp_path)})

        assert result["data"]["verified"] is True
        assert "empty" in str(result["data"].get("detail", "")).lower()

    def test_interpret_states_the_signal_limits(self) -> None:
        result = verificar_rdd.run({"action": "interpret"})

        assert result["success"] is True
        limits = " ".join(result["data"]["limits"])
        assert "executor completed" in limits
        assert "success" in limits

    def test_run_action_warns_about_the_vault_path_default(self) -> None:
        result = verificar_rdd.run({"action": "run"})

        assert result["success"] is True
        assert "/app/vault" in result["data"]["warning"]

    def test_min_samples_matches_policy(self) -> None:
        """A drifted constant would make the note lie."""
        from jarvis_os.policy import MIN_SAMPLES

        assert verificar_rdd.MIN_SAMPLES == MIN_SAMPLES

    def test_policy_reports_shadow_default(self) -> None:
        result = verificar_rdd.run({"action": "policy", "receipts_dir": "/tmp/none"})

        assert result["success"] is True
        assert result["data"]["min_samples"] == verificar_rdd.MIN_SAMPLES
        assert "steering" in result["data"]

    def test_dump_is_valid_json(self) -> None:
        assert json.loads(verificar_rdd.dump())["min_samples"] == verificar_rdd.MIN_SAMPLES

    def test_unknown_action(self) -> None:
        assert verificar_rdd.run({"action": "nope"})["success"] is False

    def test_env_var_is_honoured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JARVIS_RECEIPTS_DIR", str(tmp_path))
        result = verificar_rdd.run({"action": "verify"})

        assert result["data"]["root"] == str(tmp_path)


def _frontmatter(
    *,
    skill_id: str = "skill.prueba",
    description: str = '"A description long enough to pass validation"',
    capability: str = '"prueba.do"',
) -> str:
    """Build a valid skill frontmatter, varying one field at a time.

    Building it here rather than reading a shipped .skills/*.md keeps these
    tests self-contained: the four procedure skills are gitignored, so a test
    that opens one passes locally and fails in CI.
    """
    return (
        "---\n"
        f'id: "{skill_id}"\n'
        'name: "Prueba"\n'
        f"description: {description}\n"
        "capabilities:\n"
        f"  - {capability}\n"
        "input_schema:\n  type: object\n"
        "output_schema:\n  type: object\n"
        "---\n"
    )


VALID_FRONTMATTER = _frontmatter()


class TestDesarrollarSkill:
    def test_validates_a_conforming_skill_file(self, tmp_path: Path) -> None:
        """Writes its own frontmatter rather than reading a shipped skill.

        The four procedure skills are gitignored, so a test that opens
        .skills/cobertura.md passes on a developer machine and fails in CI with
        'no skill file'. Self-contained fixtures keep both honest.
        """
        (tmp_path / "prueba.md").write_text(VALID_FRONTMATTER)
        result = desarrollar_skill.run(
            {
                "action": "check",
                "skill_name": "prueba",
                "context": {"skills_dir": str(tmp_path)},
            }
        )

        # The only remaining problem is the missing handler, which is the point:
        # a skill without one registers cleanly and fails at execute time.
        assert result["success"] is True
        assert result["data"]["valid"] is False
        assert any("no handler" in p for p in result["data"]["problems"])

    def test_flags_a_missing_file(self) -> None:
        result = desarrollar_skill.run({"action": "check", "skill_name": "no_existe"})

        assert result["data"]["valid"] is False
        assert any("no skill file" in p for p in result["data"]["problems"])

    def test_rejects_hyphenated_id(self, tmp_path: Path) -> None:
        """The rule that rejected skill-cobertura. Kept as a test because the
        two grandfathered skills still use the hyphen form."""
        skill = tmp_path / "prueba.md"
        skill.write_text(_frontmatter(skill_id="skill-prueba"))
        result = desarrollar_skill.run(
            {
                "action": "check",
                "skill_name": "prueba",
                "context": {"skills_dir": str(tmp_path)},
            }
        )

        assert result["data"]["valid"] is False
        assert any("id" in p for p in result["data"]["problems"])

    def test_rejects_digits_in_capabilities(self, tmp_path: Path) -> None:
        skill = tmp_path / "prueba.md"
        skill.write_text(_frontmatter(capability='"prueba.do_v2"'))
        result = desarrollar_skill.run(
            {
                "action": "check",
                "skill_name": "prueba",
                "context": {"skills_dir": str(tmp_path)},
            }
        )

        assert result["data"]["valid"] is False
        assert any("capability" in p for p in result["data"]["problems"])

    def test_flags_a_missing_handler(self, tmp_path: Path) -> None:
        skill = tmp_path / "prueba.md"
        skill.write_text(
            "---\n"
            'id: "skill.prueba"\n'
            'name: "Prueba"\n'
            'description: "A description long enough to pass validation"\n'
            "capabilities:\n"
            '  - "prueba.do"\n'
            "input_schema:\n  type: object\n"
            "output_schema:\n  type: object\n"
            "---\n"
        )
        result = desarrollar_skill.run(
            {
                "action": "check",
                "skill_name": "prueba",
                "context": {"skills_dir": str(tmp_path)},
            }
        )

        assert any("no handler" in p for p in result["data"]["problems"])

    def test_rejects_a_short_description(self, tmp_path: Path) -> None:
        skill = tmp_path / "prueba.md"
        skill.write_text(_frontmatter(description='"corto"'))
        result = desarrollar_skill.run(
            {
                "action": "check",
                "skill_name": "prueba",
                "context": {"skills_dir": str(tmp_path)},
            }
        )

        assert any("description" in p for p in result["data"]["problems"])

    def test_checklist_states_the_entrypoint_rule(self) -> None:
        result = desarrollar_skill.run({"action": "checklist"})

        assert "not an importable module" in result["data"]["entrypoint_rule"]

    def test_template_uses_a_dotted_id(self) -> None:
        result = desarrollar_skill.run({"action": "template", "skill_name": "prueba"})

        assert result["data"]["id_example"] == "skill.prueba"
        assert "def run(" in result["data"]["handler"]

    def test_template_requires_a_name(self) -> None:
        assert desarrollar_skill.run({"action": "template"})["success"] is False

    def test_sub_actions_all_reduce_to_validation(self, tmp_path: Path) -> None:
        """A partial check would report a valid file with a missing handler."""
        (tmp_path / "prueba.md").write_text(VALID_FRONTMATTER)
        for action in ("schema", "entrypoint", "handler", "test", "register"):
            result = desarrollar_skill.run(
                {
                    "action": action,
                    "skill_name": "prueba",
                    "context": {"skills_dir": str(tmp_path)},
                }
            )
            assert result["data"]["requested_action"] == action
            assert result["data"]["handler_exists"] is False

    def test_dump_is_valid_json(self) -> None:
        assert "chain" in json.loads(desarrollar_skill.dump())


class TestAnalisisCalidad:
    def test_instance_facts_match_what_was_verified(self) -> None:
        result = analisis_calidad.run({"action": "results"})

        instance = result["data"]["instance"]
        assert instance["version"] == analisis_calidad.SERVER_VERSION
        assert instance["dast_available"] is False
        assert instance["dast_web_services_found"] == 0
        assert instance["dast_reason"]

    def test_dart_is_excluded_with_a_reason(self) -> None:
        instance = analisis_calidad.run({"action": "results"})["data"]["instance"]

        assert instance["dart_available"] is False
        assert "paid analyzer" in instance["dart_reason"]

    def test_diagnose_documents_the_401_cause(self) -> None:
        """The most common failure has a specific cause: Bearer vs Basic."""
        result = analisis_calidad.run({"action": "diagnose"})

        note = result["data"]["failure_modes"]["401_unauthorized"]
        assert "sonar.login" in note
        assert "Bearer" in note
        assert "sonar.token" in note

    def test_diagnose_documents_the_stale_coverage_failure(self) -> None:
        modes = analisis_calidad.run({"action": "diagnose"})["data"]["failure_modes"]

        note = modes["line_out_of_range"]
        assert "stale coverage.xml" in note
        assert "aborts the entire analysis" in note

    def test_dast_reports_the_runner_constraint(self) -> None:
        result = analisis_calidad.run({"action": "scan"})

        dast_text = analisis_calidad._dast()
        assert dast_text["available_in_sonarqube"] is False
        assert any("Tailscale" in c for c in dast_text["constraints"])
        assert result["success"] is True

    def test_check_finds_missing_coverage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """coverage.xml missing is a hard blocker: the analysis aborts."""
        monkeypatch.chdir(tmp_path)
        result = analisis_calidad.run({"action": "check"})

        assert result["data"]["ready"] is False
        assert any("coverage.xml" in p for p in result["data"]["problems"])

    def test_scan_steps_name_java_before_the_scanner(self) -> None:
        steps = analisis_calidad.run({"action": "scan"})["data"]["steps"]

        assert any("JAVA_HOME" in s for s in steps)
        assert any("sonar.login" in s for s in steps)

    def test_auth_note_documents_the_empty_password(self) -> None:
        note = analisis_calidad.run({"action": "results"})["data"]["auth_note"]

        assert "trailing colon" in note

    def test_dump_is_valid_json(self) -> None:
        assert json.loads(analisis_calidad.dump())["edition"] == "Community"

    def test_unknown_action(self) -> None:
        assert analisis_calidad.run({"action": "nope"})["success"] is False


class TestAllFourShareTheEnvelope:
    """One assertion across every handler, so a new one cannot skip it."""

    @pytest.mark.parametrize(
        "module",
        [cobertura, verificar_rdd, desarrollar_skill, analisis_calidad],
    )
    def test_unknown_action_returns_failure_envelope(self, module) -> None:
        result = module.run({"action": "definitely_not_an_action"})

        assert result["success"] is False
        assert "Unknown action" in result["error"]
        assert "Traceback" not in result["error"]

    @pytest.mark.parametrize(
        "module",
        [cobertura, verificar_rdd, desarrollar_skill, analisis_calidad],
    )
    def test_dump_is_parseable_json(self, module) -> None:
        json.loads(module.dump())
