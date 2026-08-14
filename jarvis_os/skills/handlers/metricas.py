"""Skill handler: metricas (system metrics collection).

Usage::

    result = metricas.run({"action": "report", "output_format": "markdown"})
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute the metricas skill.

    Args:
        input_data: Skill input matching ``.skills/metricas.md`` schema.

    Returns:
        A dict with ``success`` and ``data`` per the output schema.
    """
    action = input_data.get("action", "report")
    output_format = input_data.get("output_format", "markdown")
    interval_seconds = int(input_data.get("interval_seconds", 60))
    duration_seconds = int(input_data.get("duration_seconds", 300))
    include_containers = input_data.get("include_containers", [])
    vault_path = Path(input_data.get("context", {}).get("vault_path", "/app/vault"))

    try:
        if action == "docker_stats":
            data = _collect_docker_stats(include_containers)
        elif action == "host_stats":
            data = _collect_host_stats()
        elif action == "collect":
            data = _collect_continuous(interval_seconds, duration_seconds, include_containers)
        elif action == "report":
            docker = _collect_docker_stats(include_containers)
            host = _collect_host_stats()
            data = {"docker": docker, "host": host, "timestamp": _now_iso()}
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

        vault_changes: list[dict[str, Any]] = []
        if action in {"report", "collect"} and output_format == "markdown":
            md = _format_markdown(data)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            out_path = vault_path / "wiki" / f"metricas_{today}.md"
            try:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if out_path.exists():
                    existing = out_path.read_text(encoding="utf-8")
                    if "## Docker — Contenedores" not in existing:
                        out_path.write_text(existing + "\n\n" + md, encoding="utf-8")
                    else:
                        out_path.write_text(md, encoding="utf-8")
                else:
                    fm = _frontmatter("metricas_" + today, ["metricas", "system", "docker", "host"], vault_path)
                    out_path.write_text(fm + "\n\n" + md, encoding="utf-8")
                vault_changes.append(
                    {
                        "path": str(out_path.relative_to(vault_path)),
                        "operation": "CREATE",
                        "content": md,
                        "frontmatter": {"id": "metricas_" + today, "tags": ["metricas", "system", "docker", "host"]},
                    }
                )
            except Exception as exc:
                logger.warning("Vault write failed: %s", exc)

        return {"success": True, "data": data, "vault_changes": vault_changes}
    except Exception as exc:
        logger.exception("metricas skill failed")
        return {"success": False, "error": str(exc)}


def _collect_docker_stats(include_containers: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.ID}}\t{{.Status}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines = result.stdout.strip().splitlines()
        containers = []
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 9:
                continue
            name = parts[0]
            if include_containers and name not in include_containers:
                continue
            containers.append(
                {
                    "name": name,
                    "id": parts[1],
                    "status": parts[2],
                    "cpu_percent": _to_float(parts[3]),
                    "memory_usage_mb": _to_mb(parts[4]),
                    "memory_limit_mb": _to_mb_limit(parts[4]),
                    "memory_percent": _to_float(parts[5]),
                    "net_io_mb": _to_mb_pair(parts[6]),
                    "block_io_mb": _to_mb_pair(parts[7]),
                    "pids": int(parts[8]),
                }
            )
        return {
            "containers_total": len(lines),
            "containers_running": len(containers),
            "containers_stopped": len(lines) - len(containers),
            "images_count": _int_safe(_sh("docker images -q | wc -l")),
            "networks_count": _int_safe(_sh("docker network ls -q | wc -l")),
            "volumes_count": _int_safe(_sh("docker volume ls -q | wc -l")),
            "containers": containers,
        }
    except Exception as exc:
        logger.warning("docker_stats failed: %s", exc)
        return {"containers_total": 0, "containers_running": 0, "containers_stopped": 0, "images_count": 0, "networks_count": 0, "volumes_count": 0, "containers": []}


def _collect_host_stats() -> dict[str, Any]:
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        load1, load5, load15 = psutil.getloadavg()
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        disk_io = psutil.disk_io_counters()
        net_io = psutil.net_io_counters(pernic=True)
        interfaces = []
        for name, stats in net_io.items():
            interfaces.append(
                {
                    "name": name,
                    "bytes_sent_mb": round(stats.bytes_sent / (1024 * 1024), 1),
                    "bytes_recv_mb": round(stats.bytes_recv / (1024 * 1024), 1),
                    "packets_sent": stats.packets_sent,
                    "packets_in": stats.packets_recv,
                }
            )
        return {
            "cpu_percent": cpu_percent,
            "cpu_count": cpu_count,
            "load_average": [load1, load5, load15],
            "memory_total_gb": round(mem.total / (1024 ** 3), 1),
            "memory_used_gb": round(mem.used / (1024 ** 3), 1),
            "memory_percent": mem.percent,
            "swap_total_gb": round(swap.total / (1024 ** 3), 1),
            "swap_used_gb": round(swap.used / (1024 ** 3), 1),
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "disk_used_gb": round(disk.used / (1024 ** 3), 1),
            "disk_percent": disk.percent,
            "disk_io_read_mb_s": round((disk_io.read_bytes / (1024 ** 2)) / max(time.time() - psutil.boot_time(), 1), 1) if disk_io else 0,
            "disk_io_write_mb_s": round((disk_io.write_bytes / (1024 ** 2)) / max(time.time() - psutil.boot_time(), 1), 1) if disk_io else 0,
            "network_interfaces": interfaces,
        }
    except Exception as exc:
        logger.warning("host_stats failed (psutil): %s", exc)
        return {}


def _collect_continuous(interval: int, duration: int, include_containers: list[str]) -> dict[str, Any]:
    samples = []
    count = max(1, duration // interval)
    for _ in range(count):
        samples.append(
            {
                "timestamp": _now_iso(),
                "docker": _collect_docker_stats(include_containers),
                "host": _collect_host_stats(),
            }
        )
        time.sleep(interval)
    return {"samples": samples, "aggregated": _aggregate(samples)}


def _aggregate(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}
    return {"sample_count": len(samples)}


def _format_markdown(data: dict[str, Any]) -> str:
    lines = ["# Métricas del Sistema", ""]
    docker = data.get("docker", {})
    host = data.get("host", {})
    if docker:
        lines.append("## Docker")
        for c in docker.get("containers", []):
            lines.append(f"- **{c['name']}**: CPU {c.get('cpu_percent', 0)}%, RAM {c.get('memory_percent', 0)}%")
    if host:
        lines.append("## Host")
        lines.append(f"- CPU: {host.get('cpu_percent', 0)}%")
        lines.append(f"- RAM: {host.get('memory_percent', 0)}%")
        lines.append(f"- Disco: {host.get('disk_percent', 0)}%")
    return "\n".join(lines)


def _frontmatter(note_id: str, tags: list[str], vault_path: Path) -> str:
    ts = _now_iso()
    return "\n".join([
        "---",
        f"id: {note_id}",
        f"tags: {tags}",
        f"created: \"{ts}\"",
        f"modified: \"{ts}\"",
        "source: \"skill.metricas\"",
        "---",
        "",
    ])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sh(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, timeout=5).strip()
    except Exception:
        return "0"


def _to_float(val: str) -> float:
    try:
        return float(val.replace("%", "").strip())
    except Exception:
        return 0.0


def _to_mb(val: str) -> float:
    try:
        num, unit = val.strip().split()
        num = float(num)
        if unit.lower().startswith("g"):
            return round(num * 1024, 1)
        if unit.lower().startswith("k"):
            return round(num / 1024, 1)
        return round(num, 1)
    except Exception:
        return 0.0


def _to_mb_limit(val: str) -> float:
    try:
        return _to_mb(val.split("/")[-1].strip())
    except Exception:
        return 0.0


def _to_mb_pair(val: str) -> list[float]:
    try:
        parts = val.strip().split("/")
        return [_to_mb(parts[0]), _to_mb(parts[1])]
    except Exception:
        return [0.0, 0.0]


def _int_safe(val: str) -> int:
    try:
        return int(val)
    except Exception:
        return 0
