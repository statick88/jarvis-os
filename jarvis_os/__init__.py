"""
JARVIS-OS — Personal OS orchestrated by voice and Markdown.

Modules:
- config: Pydantic-settings configuration management
- voice_bridge: gRPC voice pipeline client with streaming
- opencode_adapter: WebSocket/HTTP adapter for OpenCode agent orchestration
- floci_client: AWS S3 + SQS client for FLOCI media pipeline
- vault: Zettelkasten vault indexer, linker, search, and validator
- skills: Skill loader, executor, and registry
- hud: Terminal TUI and WebSocket server for real-time HUD
"""
