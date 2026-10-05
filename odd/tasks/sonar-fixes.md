# Feature: sonar-fixes — Cero BLOCKER/CRITICAL, MAJOR verificados

## Objective
Dejar el reporte SonarQube sin BLOCKER ni CRITICAL, y MAJOR S1172 resueltos o justificados con evidencia (sin supresiones).

## Problem
Reporte 2026-10-05 (SonarQube 9.9 local, gate default OK): 1 BLOCKER S3516 (`handlers/bffla_idor.py:47`), ~15 S3776 complejidad, ~10 S1192 duplicados, ~27 S1172 params sin uso. Total 52 BLOCKER/CRITICAL/MAJOR.

## Why
- BLOCKER = release blocker bajo cualquier gate serio; el gate propio del VPS (bugs 0, smells ≤10) hoy no pasaría
- Regla: nunca suprimir reglas ni maquillar métricas; cada fix con tests que lo cubran

## Scope
- **In scope**: BLOCKER, S3776, S1192, S1172 con call-site verificado
- **Out of scope**: cobertura 57.6→80 (hilo propio), hotspots (requieren revisión humana), MINOR/INFO

## Constraints
- Sin `# noqa` ni supresiones; si un param "sin uso" es interfaz, se elimina igual solo si ningún caller lo pasa (verificado), o se usa de verdad
- Refactors de complejidad sin cambio de comportamiento: tests antes y después en verde
- Work-unit commits por sección; rescan Sonar al final de cada sección

## Acceptance Criteria
- [ ] S3516 BLOCKER cerrado con comportamiento corregido + test
- [ ] S3776: toda función ≤15 complejidad (verificado en rescan)
- [ ] S1192: constantes extraídas, sin duplicados ≥3
- [ ] S1172: cero params sin uso o justificación con call-sites (sin supresión)
- [ ] Rescan final: 0 BLOCKER, 0 CRITICAL; MAJOR restantes solo con justificación
- [ ] `pytest` suite completa verde tras cada sección

## Progress & Verification
- Initial: 2026-10-05, 52 issues (1 BLOCKER / ~24 CRITICAL / ~27 MAJOR)

---

## Task List

| ID | Task | Files | Status | Priority |
|----|------|-------|--------|----------|
| S-1 | BLOCKER S3516 + S3776 `handlers/bffla_idor.py:47` | `jarvis_os/skills/handlers/bffla_idor.py` + tests | done (`16dbc4c`, 27 passed) | high |
| S-2 | S3776 `devsecops/bffla_idor.py:257` (20→15) | `jarvis_os/skills/devsecops/bffla_idor.py` + tests | done (`16dbc4c`, 27 passed) | high |
| S-3 | S3776 vault (`indexer:59,287`, `search:48,170`, `graph:54`, `validator:204`) | `jarvis_os/vault/*.py` + tests | pending | high |
| S-4 | S3776 handlers+plugins (`plan:74`, `tendencias:49`, `metricas:20`, `os_control:81`, `intent:71`, `opencode:164`, `voice client:441`) | varios + tests | pending | high |
| S-5 | S3776 `voice_bridge/server.py:371` (134→15, el grande) | `jarvis_os/voice_bridge/server.py` + tests | pending | high |
| S-6 | S1192 duplicados (models ×3, voice models ×3, plan ×2, events, nightly, devsecops, os_control) | varios | pending | medium |
| S-7 | S1172 params sin uso (con call-site verificado cada uno) | varios | pending | medium |
| S-8 | Rescan final + reporte delta | SonarQube local | pending | high |
