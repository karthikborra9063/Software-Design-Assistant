"""Service layer — business logic, kept separate from the HTTP (blueprint) layer.

Blueprints parse/validate the request and shape the response; services do the actual work
(auth, indexing, retrieval, ...). This keeps routes thin and logic unit-testable.
"""
