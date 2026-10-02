"""Skill handler: analisis_calidad (SonarQube SAST procedure).

Operationalises `.skills/analisis-calidad.md`. Reports the instance facts that
were verified rather than assumed, because the DAST and Dart questions both have
easy wrong answers.

Never runs sonar-scanner as a subprocess: it needs Java 11+, a Tailscale route
to the host, and a credential. This reports what the pipeline must supply and
how to read the outcome.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Verified against the live instance, not read from documentation.
SERVER_VERSION = "9.9.8.100196"
EDITION = "Community"
ANALYZABLE_LANGUAGES = 24
WEB_SERVICES_TOTAL = 37
DAST_SERVICES_FOUND = 0

# Java 11+ requirement. The default JDK 8 fails with UnsupportedClassVersionError
# (class file version 55.0 vs 52.0).
MIN_JAVA_MAJOR = 11

DAST_UNAVAILABLE_REASON = (
    "SonarQube Community Edition does not include DAST. Verified: 9.9.8.100196, "
    "24 analyzable languages, 0 DAST web services among 37 exposed. Licensing "
    "boundary, not a configuration gap."
)

DART_UNAVAILABLE_REASON = (
    "The Dart analyzer is not installed on this instance and is a paid analyzer "
    "for SonarQube Server, so jarvis_ui/ cannot be analyzed. Excluded explicitly "
    "rather than silently counted as zero files."
)

FAILURE_MODES = {
    "401_unauthorized": (
        "SonarQube Server 9.9 rejects 'Authorization: Bearer'. The token must be "
        "the Basic-auth username, so the flag is -Dsonar.login, never "
        "-Dsonar.token. The workflow names its env var SONAR_LOGIN for this "
        "reason even though the GitHub secret is SONAR_TOKEN; renaming it back "
        "looks like cleanup and silently breaks every scan."
    ),
    "line_out_of_range": (
        "A stale coverage.xml referencing a line that no longer exists. The "
        "Cobertura parser aborts the entire analysis, not just coverage import. "
        "CI regenerates the report every run; never reuse one across runs."
    ),
    "zero_files": (
        "sonar.sources is jarvis_os, which has 71 Python files. A zero-file "
        "result means the path is wrong or the exclusions matched everything."
    ),
}

SCAN_STEPS = [
    "export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home",
    'export PATH="$JAVA_HOME/bin:$PATH"',
    "pytest tests/ --cov=jarvis_os --cov-report=xml -q",
    'SONAR_HOST_URL=http://100.65.184.25:9000 sonar-scanner -Dsonar.login="$SONAR_TOKEN"',
]

SINGLE_SOURCE_OF_TRUTH = (
    "sonar-project.properties holds every analysis property. The workflow passes "
    "only the credential. Do not reintroduce -Dsonar.* flags into the workflow; "
    "the previous one duplicated sources, tests, coverage paths and exclusions "
    "inline, so two definitions could disagree with no indication of which won."
)


def _instance() -> dict[str, Any]:
    return {
        "version": SERVER_VERSION,
        "edition": EDITION,
        "project_key": "jarvis-os",
        "dast_available": False,
        "dast_reason": DAST_UNAVAILABLE_REASON,
        "dart_available": False,
        "dart_reason": DART_UNAVAILABLE_REASON,
        "analyzable_languages": ANALYZABLE_LANGUAGES,
        "web_services_total": WEB_SERVICES_TOTAL,
        "dast_web_services_found": DAST_SERVICES_FOUND,
        "host_is_tailscale_only": True,
    }


def _diagnose() -> dict[str, Any]:
    return {
        "failure_modes": FAILURE_MODES,
        "single_source_of_truth": SINGLE_SOURCE_OF_TRUTH,
        "min_java_major": MIN_JAVA_MAJOR,
        "note": (
            "A 401 is the most common failure and has a specific cause, not a "
            "wrong token. Check the flag name before rotating anything."
        ),
    }


def _dast() -> dict[str, Any]:
    return {
        "available_in_sonarqube": False,
        "reason": DAST_UNAVAILABLE_REASON,
        "out_of_band_tool": "OWASP ZAP baseline",
        "constraints": [
            "The API is reachable only at 100.65.184.25:8000 over Tailscale, so "
            "DAST cannot run from a GitHub-hosted runner without Tailscale OAuth "
            "credentials or a self-hosted runner.",
            "There is no public endpoint: 187.124.80.68 returns nothing on 8000, "
            "9000 or 443.",
            "ZAP reaches only unauthenticated routes without credentials. The last "
            "run saw 5 URLs and reported 0 High, 0 Medium, 2 Low, 1 informational. "
            "That is a five-URL sample, not an assessment of the API.",
        ],
    }


def _check() -> dict[str, Any]:
    """Check the local prerequisites for a scan."""
    problems: list[str] = []
    java_home = ""
    try:
        import subprocess

        proc = subprocess.run(
            ["java", "-version"], capture_output=True, text=True, timeout=10, check=False
        )
        match = re.search(r'version "(\d+)', (proc.stderr or "") + (proc.stdout or ""))
        if match and int(match.group(1)) < MIN_JAVA_MAJOR:
            problems.append(
                f"java major {match.group(1)} < {MIN_JAVA_MAJOR}; the scanner "
                "fails with UnsupportedClassVersionError"
            )
    except Exception as exc:  # noqa: BLE001 - absence of java is a finding
        problems.append(f"java not resolvable: {exc}")

    coverage = Path("coverage.xml")
    if not coverage.exists():
        problems.append(
            "coverage.xml missing; run pytest --cov=jarvis_os --cov-report=xml "
            "first, or the analysis aborts with 'Line N is out of range'"
        )

    if not Path("sonar-project.properties").exists():
        problems.append("sonar-project.properties missing")

    return {
        "ready": not problems,
        "java_home": java_home,
        "coverage_present": coverage.exists(),
        "problems": problems,
        "steps": SCAN_STEPS,
    }


def _results() -> dict[str, Any]:
    return {
        "instance": _instance(),
        "read_command": (
            'curl -s -u "$SONAR_TOKEN:" "$HOST/api/measures/component'
            '?component=jarvis-os&metricKeys=coverage,bugs,vulnerabilities"'
        ),
        "auth_note": (
            "The trailing colon in -u \"$TOKEN:\" is required: the token is the "
            "username and the password is empty."
        ),
        "known_state": {
            "coverage_percent": 56.1,
            "bugs": 0,
            "vulnerabilities": 0,
            "ncloc": 9090,
        },
    }


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the quality-analysis skill."""
    action = input_data.get("action", "checklist")
    try:
        if action == "check":
            return {"success": True, "data": _check()}
        if action == "diagnose":
            return {"success": True, "data": _diagnose()}
        if action == "results":
            return {"success": True, "data": _results()}
        if action in {"scan", "verify", "checklist"}:
            return {
                "success": True,
                "data": {
                    "instance": _instance(),
                    "steps": SCAN_STEPS,
                    "single_source_of_truth": SINGLE_SOURCE_OF_TRUTH,
                    "note": (
                        "This skill does not invoke sonar-scanner: it needs Java "
                        "11+, a Tailscale route and a credential. Run the steps "
                        "directly from a machine on the tailnet."
                    ),
                },
            }
        return {"success": False, "error": f"Unknown action: {action}"}
    except Exception as exc:
        message = str(exc)
        logger.exception("analisis_calidad skill failed")
        return {"success": False, "error": message}


def dump() -> str:
    """Machine-readable snapshot of the instance facts."""
    return json.dumps(_instance(), indent=2, sort_keys=True)
