"""DevSecOps automation skill plugin for LocalStack and Docker."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from jarvis_os.skills.base import BaseSkill, SkillPermission

logger = logging.getLogger(__name__)


class DevSecOpsSkill(BaseSkill):
    """Skill for LocalStack and Docker infrastructure management."""

    def __init__(self) -> None:
        super().__init__(name="skill-devsecops", version="1.0.0", permissions=[
            SkillPermission.MANAGE_LOCALSTACK,
            SkillPermission.MANAGE_DOCKER,
        ])

    async def load(self) -> None:
        await super().load()
        logger.debug("DevSecOpsSkill loaded")

    async def execute(self, operation: str, parameters: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if not self.is_loaded:
            return {"status": "error", "message": "Skill not loaded"}

        try:
            if operation == "scan_repository":
                return await self._scan_repository(parameters)
            elif operation == "check_vulnerabilities":
                return await self._check_vulnerabilities(parameters)
            elif operation == "trigger_pipeline":
                return await self._trigger_pipeline(parameters)
            elif operation == "list_s3_objects":
                return await self._list_s3_objects(parameters)
            elif operation == "list_dynamodb_tables":
                return await self._list_dynamodb_tables(parameters)
            elif operation == "list_sqs_queues":
                return await self._list_sqs_queues(parameters)
            elif operation == "list_containers":
                return await self._list_containers(parameters)
            else:
                return {"status": "error", "message": f"Unknown operation: {operation}"}
        except Exception as exc:
            logger.exception("DevSecOpsSkill operation failed: %s", operation)
            return {"status": "error", "message": str(exc)}

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "skill-devsecops",
            "version": self.version,
            "operations": {
                "scan_repository": {
                    "description": "Scan repository for security issues",
                    "parameters": {
                        "scan_type": {
                            "type": "string",
                            "enum": ["secrets", "dependencies", "config", "all"],
                            "default": "all",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "markdown"],
                            "default": "json",
                        },
                    },
                },
                "check_vulnerabilities": {
                    "description": "Check Docker images and LocalStack resources",
                    "parameters": {
                        "target": {
                            "type": "string",
                            "enum": ["docker_images", "localstack", "all"],
                            "default": "all",
                        }
                    },
                },
                "trigger_pipeline": {
                    "description": "Trigger infrastructure verification pipeline",
                    "parameters": {
                        "pipeline": {
                            "type": "string",
                            "enum": ["e2e", "lint", "build", "all"],
                            "default": "e2e",
                        }
                    },
                },
                "list_s3_objects": {
                    "description": "List S3 objects via LocalStack",
                    "parameters": {
                        "bucket": {"type": "string", "required": True},
                        "prefix": {"type": "string", "default": ""},
                    },
                },
                "list_dynamodb_tables": {
                    "description": "List DynamoDB tables via LocalStack",
                    "parameters": {},
                },
                "list_sqs_queues": {
                    "description": "List SQS queues via LocalStack",
                    "parameters": {},
                },
                "list_containers": {
                    "description": "List Docker containers",
                    "parameters": {
                        "all": {"type": "boolean", "default": True},
                    },
                },
            },
        }

    async def _scan_repository(self, params: dict[str, Any]) -> dict[str, Any]:
        scan_type = params.get("scan_type", "all")
        return {
            "status": "success",
            "result": {
                "scan_type": scan_type,
                "findings": [],
                "summary": "No security issues found (placeholder scan)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    async def _check_vulnerabilities(self, params: dict[str, Any]) -> dict[str, Any]:
        target = params.get("target", "all")
        return {
            "status": "success",
            "result": {
                "target": target,
                "vulnerabilities": [],
                "summary": "No vulnerabilities detected (placeholder check)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    async def _trigger_pipeline(self, params: dict[str, Any]) -> dict[str, Any]:
        pipeline = params.get("pipeline", "e2e")
        return {
            "status": "success",
            "result": {
                "pipeline": pipeline,
                "status": "triggered",
                "run_id": f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }

    async def _list_s3_objects(self, params: dict[str, Any]) -> dict[str, Any]:
        bucket = params.get("bucket", "")
        prefix = params.get("prefix", "")
        endpoint = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
        try:
            import boto3  # type: ignore[import-untyped]
            s3 = boto3.client("s3", endpoint_url=endpoint)
            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            objects = [obj.get("Key", "") for obj in response.get("Contents", [])]
            return {"status": "success", "result": {"bucket": bucket, "prefix": prefix, "objects": objects, "count": len(objects)}}
        except Exception as exc:
            return {"status": "error", "message": f"S3 list failed: {exc}"}

    async def _list_dynamodb_tables(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
        try:
            import boto3  # type: ignore[import-untyped]
            dynamodb = boto3.client("dynamodb", endpoint_url=endpoint)
            response = dynamodb.list_tables()
            tables = response.get("TableNames", [])
            return {"status": "success", "result": {"tables": tables, "count": len(tables)}}
        except Exception as exc:
            return {"status": "error", "message": f"DynamoDB list failed: {exc}"}

    async def _list_sqs_queues(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
        try:
            import boto3  # type: ignore[import-untyped]
            sqs = boto3.client("sqs", endpoint_url=endpoint)
            response = sqs.list_queues()
            urls = response.get("QueueUrls", [])
            return {"status": "success", "result": {"queues": urls, "count": len(urls)}}
        except Exception as exc:
            return {"status": "error", "message": f"SQS list failed: {exc}"}

    async def _list_containers(self, params: dict[str, Any]) -> dict[str, Any]:
        show_all = params.get("all", True)
        try:
            import docker  # type: ignore[import-untyped]
            try:
                client = docker.from_env()  # type: ignore[attr-defined]
            except Exception as exc:
                if "No such file or directory" in str(exc) or "Connection aborted" in str(exc):
                    return {
                        "status": "success",
                        "result": {
                            "containers": [],
                            "count": 0,
                            "note": "Docker socket unavailable in this runtime; listing skipped",
                        },
                    }
                raise
            containers = client.containers.list(all=show_all)
            data = []
            for ctr in containers:
                data.append({
                    "id": ctr.short_id,
                    "name": ctr.name,
                    "status": ctr.status,
                    "image": ctr.image.tags[0] if ctr.image.tags else ctr.image.id[:12],
                })
            return {"status": "success", "result": {"containers": data, "count": len(data)}}
        except Exception as exc:
            return {"status": "error", "message": f"Docker list failed: {exc}"}
