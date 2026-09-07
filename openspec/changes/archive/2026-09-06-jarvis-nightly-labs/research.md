# Research Report — jarvis-nightly-labs

**Date**: 2026-09-06
**Phase**: propose (sdd-research)
**Status**:done — all 6 areas validated against codebase

---

## 1. Scheduler Patterns

**Finding**: No existing scheduler exists. `jarvis_os/core/` directory does not exist.

**Background task patterns found** (candidates to follow):

| Pattern | File | Mechanism |
|---|---|---|
| `asyncio.create_task()` loops | `jarvis_os/hud/tui.py:99` | `_render_loop()` at configurable interval |
| `asyncio.create_task()` loops | `jarvis_os/hud/websocket_server.py:85` | `_serve_loop()` background task |
| `asyncio.create_task()` loops | `jarvis_os/voice_bridge/server.py:71` | `_cleanup_loop()` for expired sessions |
| `asyncio.create_task()` loops | `jarvis_os/opencode_adapter/client.py:138` | `_heartbeat_loop()` + `_receive_loop()` |
| `asyncio.create_task()` fire-and-forget | `jarvis_os/orchestrator_impl/pipeline.py:134` | TTS streaming post-execution |

**Decision**: Follow the HUD TUI render loop pattern (`jarvis_os/hud/tui.py:94-102`) — an `asyncio.create_task()` based periodic loop with configurable interval from config. Use the same `start()`/`stop()` lifecycle from `HudWebSocketServer`.

---

## 2. Local LLM Engines

**Finding**: No local LLM engine code exists. No `jarvis_os/engines/` directory. Zero llama.cpp, Ollama, GGUF references in source code.

**Config pattern**: `jarvis_os/config.py` uses pydantic-settings `BaseSettings` with `env_prefix`, env file loading, and `@lru_cache` singleton via `get_settings()`.

**Decision**: Create new `LLMSettings` class following `VoicePipelineSettings` pattern (config.py:19-53). Use Ollama as primary engine (HTTP API, no binary deps), fallback to llama.cpp via Python bindings. Config prefix: `LLM_`.

---

## 3. Obsidian Vault Structure

**Key files**:

| File | Purpose |
|---|---|
| `jarvis_os/vault/indexer.py` | `VaultIndexer` — incremental/full index of Zettelkasten notes |
| `jarvis_os/vault/models.py` | `VaultNote`, `NoteFrontmatter`, `IndexEntry` with `tags: list[str]` |
| `jarvis_os/vault/search.py` | `VaultSearch` — full-text search with `tags` filter |
| `jarvis_os/vault/stats.py` | `VaultStatsComputer` — aggregate per-tag stats |
| `jarvis_os/vault/links.py` | `extract_wikilinks()`, `resolve_links()`, `backlinks_for()` |

**Tag-based search** (critical for `#idea`, `#todo`, `#research`):

```python
from jarvis_os.vault.search import VaultSearch
search = VaultSearch(vault_root=Path("/app/vault"))
results = await search.search("*", tags=["idea", "todo", "research"])
```

`VaultStatsComputer` already computes `notes_by_tag` (stats.py:98): `dict(tag_counter.most_common(50))` — directly usable for nightly scan.

**Decision**: Use `VaultSearch.search(tags=...)` for nightly tag scanning. Use `VaultStatsComputer` for aggregate metrics in reports.

---

## 4. Skill Pattern

**`BaseSkill` ABC** (`jarvis_os/skills/base.py`):

```python
class BaseSkill(ABC):
    def __init__(self, name, version, permissions)
    async def load(self) -> None
    async def unload(self) -> None
    @abstractmethod
    async def execute(self, operation, parameters, context) -> dict
    @abstractmethod
    def get_schema(self) -> dict
```

**Implementation pattern** (from `jarvis_os/skills/obsidian/plugin.py`):

1. Subclass `BaseSkill` with name, version, permissions
2. `execute()` dispatches on `operation` string to private methods
3. Each method returns `{"status": "success"|"error", "result": {...}}`
4. `get_schema()` returns operations dict

**Registration** (`orchestrator.py:138-130`):
```python
await plugin_registry.register(NightlyLabsSkill())
```

**REST exposure**: `POST /api/v1/skills/skill-nightly-labs/execute` (automatic via skills router).

**Decision**: Use `BaseSkill` plugin pattern (simpler for Python-native skills). Register in orchestrator lifespan.

---

## 5. Flutter Widget Patterns

**State management**: Riverpod (not Provider, not Bloc).

**Provider definitions** (`jarvis_ui/lib/providers/jarvis_providers.dart`):
```dart
final jarvisApiServiceProvider = Provider<JarvisApiService>((ref) => JarvisApiService());
final orchestratorHealthProvider = FutureProvider<Map<String, dynamic>>((ref) async {...});
final chatMessagesProvider = StateProvider<List<Map<String, dynamic>>>((ref) => const []);
```

**HUD event state** (`jarvis_ui/lib/providers/hud_event_providers.dart`):
- `HudEventNotifier extends StateNotifier<HudState>`
- `HudState` with: connectionState, events, skillStatus, vaultPath, etc.
- Derived providers: `hudConnectionStateProvider`, `currentSkillExecutionProvider`, `vaultUpdateProvider`

**Widget structure** (`jarvis_ui/lib/screens/home_screen.dart`):
- `HomeScreen extends ConsumerWidget`
- Layout: Column with health pills → vital signs → memory log → chat → input
- Private `_build*` methods returning Container widgets

**Decision**: Create `nightly_provider.dart` with `NightlyState` + `NightlyNotifier`. Create `NightlyMorningBriefing` ConsumerWidget following existing `_build*` pattern.

---

## 6. Orchestrator API Patterns

**Framework**: FastAPI with uvicorn.

**Endpoint pattern** (`orchestrator.py:207-289`):
```python
@app.post("/v1/audio/session/open")
async def audio_session_open(payload: dict[str, Any]) -> JSONResponse:
    ...
    return JSONResponse({...})
```

**Key patterns**:
1. Endpoints are `@app.post()` / `@app.get()` directly on `app`
2. Return `JSONResponse` with consistent payload shape
3. Skills router mounted: `app.include_router(skills_router)`
4. Lifespan context manager handles startup/shutdown

**Pipeline event bus** (`pipeline.py:84-96`):
```python
def add_event_listener(self, listener) -> None
async def _emit(self, event) -> None
```

**Decision**: Add `POST /v1/nightly/scheduler/toggle` endpoint following existing pattern. Nightly skill registers via plugin system and is callable via skills router.

---

## Integration Matrix

| Component | Pattern to Follow | Target File |
|---|---|---|
| Scheduler | `asyncio.create_task()` loop like HUD TUI | Create `jarvis_os/core/scheduler.py` |
| LLM Engine | New `LLMSettings` in config.py | `jarvis_os/config.py` |
| Vault tag query | `VaultSearch.search(tags=...)` | `jarvis_os/vault/search.py` |
| Skill | Subclass `BaseSkill`, register in lifespan | Create `jarvis_os/skills/nightly_labs/plugin.py` |
| Flutter widget | `ConsumerWidget` + Riverpod providers | Create `jarvis_ui/lib/providers/nightly_provider.dart` |
| REST endpoint | `@app.post("/v1/nightly/...")` | `jarvis_os/orchestrator.py` |
| Morning Briefing | `_build*` method in HomeScreen | `jarvis_ui/lib/screens/home_screen.dart` |
