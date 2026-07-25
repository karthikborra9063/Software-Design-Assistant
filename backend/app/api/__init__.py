"""HTTP layer (Flask blueprints).

Each feature area gets its own blueprint: health (now), then auth, projects, and chat.
Blueprints are registered on the app in `create_app`.
"""
