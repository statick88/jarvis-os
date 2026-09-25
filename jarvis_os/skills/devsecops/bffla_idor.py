"""BFLA/IDOR Testing Skill for JARVIS-OS.

Provides API Business Logic Field Level Authorization (BFLA) and Insecure
Direct Object Reference (IDOR) testing capabilities against FastAPI-based
endpoints. Integrates with the SkillExecutor pipeline and persists findings
via the Engram vault.

Critical: RDD must remain active (receipt-driven development: on globally).
Findings must not re-test already confirmed findings (per pentest methodology:
"Do NOT re-test already confirmed findings F01-F22").
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
from pydantic import BaseModel, Field

from jarvis_os.skills.base import BaseSkill, SkillPermission

logger = logging.getLogger(__name__)

# Role definitions for authorization testing
ROLES = [
    "SuperAdmin",
    "BusinessAdmin",
    "Staff",
    "Medical",
    "Fundraiser",
    "User",
]

# BFLA/IDOR finding tracking (in-memory, persisted via Engram).
# Seed external confirmed findings F01-F22 so they are never re-tested.
_CONFIRMED_FINDING_IDS: set[str] = {f"F{i:02d}" for i in range(1, 23)}

# CVSS 3.1 base scores for finding categories
CVSS_BASE_SCORES = {
    "bfla": 7.5,
    "idor": 7.0,
}


class BfflaIdorFinding(BaseModel):
    """Represents a BFLA or IDOR finding."""

    id: str
    title: str
    description: str
    finding_type: str = Field(..., description="bfla or idor")
    endpoint: str
    method: str
    role: str
    cvss_score: float
    confirmed: bool = False
    target_object: str | None = None
    reference_location: str | None = None
    owasp_api: str | None = Field(
        None,
        description="OWASP API Security Top 10 id (API1:2023 for IDOR/BOLA, API5:2023 for BFLA)",
    )
    mitre_attack: str | None = Field(
        None,
        description="MITRE ATT&CK technique id (T1190 Exploit Public-Facing Application)",
    )


class BfflaIdorSkill(BaseSkill):
    """Skill for BFLA/IDOR API security testing."""

    def __init__(self) -> None:
        super().__init__(
            name="bfla-idor-testing",
            version="1.0.0",
            permissions=[
                SkillPermission.EXECUTE_COMMANDS,
                SkillPermission.WRITE_VAULT,
            ],
        )
        self.description = (
            "BFLA and IDOR testing against FastAPI endpoints with role-based "
            "authorization validation"
        )

    async def load(self) -> None:
        await super().load()
        logger.debug("BFLA/IDOR Testing Skill loaded")

    async def execute(
        self,
        operation: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a BFLA/IDOR testing operation."""
        if not self.is_loaded:
            return {"status": "error", "message": "Skill not loaded"}

        op = operation.lower()

        if op == "enumerate_endpoints":
            return await self._enumerate_endpoints(parameters)
        if op == "test_bfla":
            return await self._test_bfla(parameters)
        if op == "test_idor":
            return await self._test_idor(parameters)
        if op == "get_confirmed":
            return {"status": "success", "confirmed_ids": list(_CONFIRMED_FINDING_IDS)}
        if op == "mark_confirmed":
            finding_id = parameters.get("finding_id")
            if finding_id:
                _CONFIRMED_FINDING_IDS.add(finding_id)
            return {"status": "success", "confirmed_ids": list(_CONFIRMED_FINDING_IDS)}
        return {"status": "error", "message": f"Unknown operation: {operation}"}

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "bfla-idor-testing",
            "version": self.version,
            "operations": {
                "enumerate_endpoints": {
                    "description": "Parse FastAPI routes and enumerate all endpoints, grouped by role",
                    "parameters": {
                        "include_internal": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include internal/admin endpoints",
                        }
                    },
                },
                "test_bfla": {
                    "description": "Test BFLA vulnerability on endpoint with lower-privilege token",
                    "parameters": {
                        "endpoint": {"type": "string", "description": "Target endpoint path"},
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                            "default": "GET",
                        },
                        "lower_privilege_role": {
                            "type": "string",
                            "description": "Role to test with",
                            "enum": ROLES,
                        },
                        "method_switching": {"type": "boolean", "default": True},
                        "path_confusion": {"type": "boolean", "default": True},
                    },
                },
                "test_idor": {
                    "description": "Test Insecure Direct Object Reference on endpoint",
                    "parameters": {
                        "endpoint": {"type": "string", "description": "Target endpoint path"},
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                            "default": "GET",
                        },
                        "target_object": {"type": "string"},
                        "lower_privilege_role": {
                            "type": "string",
                            "description": "Role to test with",
                            "enum": ROLES,
                        },
                        "reference_locations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["url_param", "query_string", "body", "header", "cookie"],
                        },
                    },
                },
            },
        }

    async def _enumerate_endpoints(
        self, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """Parse FastAPI routes and enumerate all endpoints, grouped by role."""
        include_internal = parameters.get("include_internal", False)

        # Locate the FastAPI app instance
        app: Any = None
        try:
            import jarvis_os.orchestrator as orch_module

            app = getattr(orch_module, "app", None)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not import orchestrator app: %s", exc)

        if app is None:
            return {
                "status": "error",
                "message": "Could not locate FastAPI application instance",
            }

        endpoints: list[dict[str, Any]] = []

        for route in app.routes:
            if not (hasattr(route, "methods") and hasattr(route, "path")):
                continue

            methods: set[str] = set(route.methods or ())
            path: str = str(route.path)

            if not include_internal and any(
                token in path
                for token in ("/health", "/docs", "/redoc", "/openapi")
            ):
                continue

            role = self._determine_role(path, methods, include_internal)
            endpoints.append(
                {
                    "path": path,
                    "methods": sorted(methods),
                    "role": role,
                    "description": self._endpoint_description(path, role),
                }
            )

        grouped: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
        for ep in endpoints:
            grouped[ep["role"]].append(ep)

        return {
            "status": "success",
            "total_endpoints": len(endpoints),
            "grouped_by_role": grouped,
            "all_roles": ROLES,
        }

    @staticmethod
    def _determine_role(
        path: str, methods: set[str], include_internal: bool
    ) -> str:
        """Determine the primary role associated with an endpoint."""
        del methods  # unused; kept for signature stability
        path_lower = path.lower()

        if any(kw in path_lower for kw in ("patient", "medical", "health", "clinical")):
            return "Medical"
        if any(kw in path_lower for kw in ("admin", "super", "config", "setting")):
            return "SuperAdmin" if include_internal else "BusinessAdmin"
        if any(kw in path_lower for kw in ("donor", "fundraiser", "campaign", "donation")):
            return "Fundraiser"
        if any(kw in path_lower for kw in ("staff", "employee", "worker")):
            return "Staff"
        return "User"

    @staticmethod
    def _endpoint_description(path: str, role: str) -> str:
        """Generate a human-readable description for an endpoint."""
        return f"Endpoint for {role} role at {path}"

    async def _test_bfla(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Test BFLA vulnerability on endpoint with lower-privilege token."""
        endpoint = parameters.get("endpoint", "")
        method = parameters.get("method", "GET")
        lower_privilege_role = parameters.get("lower_privilege_role", "User")
        method_switching = parameters.get("method_switching", True)
        path_confusion = parameters.get("path_confusion", True)

        if not endpoint:
            return {"status": "error", "message": "Endpoint path is required"}

        findings: list[dict[str, Any]] = []

        # Test 1: original method
        finding = await self._run_bfla_probe(
            endpoint, method, lower_privilege_role, "bfla"
        )
        if finding:
            findings.append(finding)

        # Test 2: method switching
        if method_switching:
            for other in ("POST", "PUT", "DELETE", "PATCH"):
                if other == method.upper():
                    continue
                f = await self._run_bfla_probe(
                    endpoint, other, lower_privilege_role, "method_switching"
                )
                if f:
                    findings.append(f)

        # Test 3: path confusion (trailing-slash variants)
        if path_confusion:
            for variant in (endpoint.rstrip("/"), endpoint + "/"):
                if variant == endpoint:
                    continue
                f = await self._run_bfla_probe(
                    variant, method, lower_privilege_role, "path_confusion"
                )
                if f:
                    findings.append(f)

        return {
            "status": "success",
            "findings": findings,
            "endpoint": endpoint,
            "tested_role": lower_privilege_role,
        }

    @staticmethod
    def _base_url() -> str:
        return os.environ.get("BFLA_IDOR_BASE_URL", "http://127.0.0.1:3000").rstrip("/")

    @staticmethod
    def _role_token(role: str) -> str:
        """Return a bearer token for the given role, if configured."""
        env_key = f"BFLA_IDOR_TOKEN_{role.upper()}"
        return os.environ.get(env_key, "")

    async def _run_bfla_probe(
        self,
        endpoint: str,
        method: str,
        role: str,
        vector: str,
    ) -> dict[str, Any] | None:
        """Run one BFLA probe against the live API and return a finding if triggered."""
        url = f"{self._base_url()}{endpoint}"
        headers: dict[str, str] = {}
        token = self._role_token(role)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method.upper(), url, headers=headers
                ) as resp:
                    if resp.status >= 400:
                        return None
                    body = await resp.text()
        except Exception as exc:
            logger.debug("BFLA probe failed (%s): %s", vector, exc)
            return None

        haystack = body.lower()
        if "password" not in haystack and "secret" not in haystack:
            return None

        title = "BFLA Vulnerability Detected"
        if vector == "method_switching":
            title = "BFLA via Method Switching"
        elif vector == "path_confusion":
            title = "BFLA via Path Confusion"

        finding = BfflaIdorFinding(
            id=f"bfla-{endpoint}-{method}-{role}",
            title=title,
            description=(
                f"Endpoint {endpoint} with {method} method returns privileged "
                f"data to {role} role"
            ),
            finding_type="bfla",
            endpoint=endpoint,
            method=method,
            role=role,
            cvss_score=CVSS_BASE_SCORES["bfla"],
            owasp_api="API5:2023",
            mitre_attack="T1190",
        )
        if finding.id in _CONFIRMED_FINDING_IDS:
            return None
        return finding.model_dump()

    async def _test_idor(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Test Insecure Direct Object Reference on endpoint."""
        endpoint = parameters.get("endpoint", "")
        method = parameters.get("method", "GET")
        target_object = parameters.get("target_object", "patient_id")
        lower_privilege_role = parameters.get("lower_privilege_role", "User")
        reference_locations = parameters.get(
            "reference_locations",
            ["url_param", "query_string", "body", "header", "cookie"],
        )

        if not endpoint:
            return {"status": "error", "message": "Endpoint path is required"}

        findings: list[dict[str, Any]] = []

        for loc in reference_locations:
            body_text = await self._run_idor_probe(
                endpoint, method, lower_privilege_role, target_object, loc
            )
            if body_text is None:
                continue

            haystack = body_text.lower()
            if not any(kw in haystack for kw in ("username", "patient_", "medical_")):
                continue

            finding = BfflaIdorFinding(
                id=f"idor-{endpoint}-{target_object}-{loc}-{lower_privilege_role}",
                title="IDOR Vulnerability Detected",
                description=(
                    f"Endpoint {endpoint} allows {lower_privilege_role} to "
                    f"access {target_object}=1 via {loc}"
                ),
                finding_type="idor",
                endpoint=endpoint,
                method=method,
                role=lower_privilege_role,
                cvss_score=CVSS_BASE_SCORES["idor"],
                owasp_api="API1:2023",
                mitre_attack="T1190",
                target_object=target_object,
                reference_location=loc,
            )
            if finding.id in _CONFIRMED_FINDING_IDS:
                continue
            findings.append(finding.model_dump())

        return {
            "status": "success",
            "findings": findings,
            "endpoint": endpoint,
            "tested_object": target_object,
            "tested_role": lower_privilege_role,
            "reference_locations_tested": reference_locations,
        }

    async def _run_idor_probe(
        self,
        endpoint: str,
        method: str,
        role: str,
        target_object: str,
        reference_location: str,
    ) -> str | None:
        """Probe one IDOR reference location; return response body on 2xx, else None."""
        base = self._base_url()
        headers: dict[str, str] = {}
        token = self._role_token(role)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        test_value = "1"
        url = f"{base}{endpoint}"
        data: dict[str, str] | None = None

        if reference_location == "url_param":
            url = f"{base}{endpoint}".replace(
                f"{{{target_object}}}", test_value
            )
            if f"{{{target_object}}}" in endpoint:
                pass  # already substituted above
            elif not url.rstrip("/").endswith(test_value):
                url = f"{url.rstrip('/')}/{test_value}"
        elif reference_location == "query_string":
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{target_object}={test_value}"
        elif reference_location == "body":
            data = {target_object: test_value}
        elif reference_location == "header":
            headers[target_object] = test_value
        elif reference_location == "cookie":
            headers["Cookie"] = f"{target_object}={test_value}"

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method.upper(), url, headers=headers, data=data
                ) as resp:
                    if resp.status >= 400:
                        return None
                    return await resp.text()
        except Exception as exc:
            logger.debug(
                "IDOR probe failed (%s/%s): %s", target_object, reference_location, exc
            )
            return None
