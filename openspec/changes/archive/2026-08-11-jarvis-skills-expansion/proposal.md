# Proposal: Expansión de Skills (Obsidian, OS Control & DevSecOps)

## Intent
Expand the operational capabilities of `jarvis-os` through three new skills: Obsidian vault management, macOS system control, and DevSecOps automation. These skills enable deeper integration between the Flutter client, voice interface, and backend services.

## Scope
- **In scope:**
  - `skill-obsidian`: CRUD operations on Obsidian vault notes via `jarvis_os/vault/`
  - `skill-os-control`: Real-time resource monitoring (CPU, RAM, disk) and controlled command execution via `gentle-orchestrator`
  - `skill-devsecops`: LocalStack S3/DynamoDB/SQS management and Docker infrastructure automation
  - New REST endpoints in `gentle-orchestrator` for skill invocation
  - Flutter UI integration for skill discovery and execution

- **Out of scope:**
  - Remote/external Obsidian sync
  - Unrestricted shell access from mobile client
  - Cloud provider integrations beyond LocalStack

## Approach
1. Define skill plugin architecture in `jarvis_os/skills/` with standardized interfaces
2. Implement `skill-obsidian` extending existing vault modules
3. Implement `skill-os-control` with macOS-safe command sandbox
4. Implement `skill-devsecops` wrapping LocalStack and Docker APIs
5. Expose skills via `POST /v1/skills/{skill_name}/execute` on orchestrator
6. Integrate skill execution into Flutter UI chat flow

## Tradeoffs
- **Chosen:** REST over gRPC for skill endpoints; simpler mobile integration
- **Chosen:** macOS-first OS control; Linux/Windows support deferred
- **Chosen:** LocalStack as primary cloud target; real AWS deferred to future phase
- **Deferred:** Plugin hot-reload; skills are statically loaded at startup

## Rollback
- Remove new skill modules from `jarvis_os/skills/`
- Revert orchestrator endpoints to pre-skill state
- Remove skill-related UI components from Flutter client
