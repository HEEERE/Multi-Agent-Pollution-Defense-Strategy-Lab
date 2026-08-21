"""Offline research code (Phase 0.5 scale pre-experiment and friends).

This package is deliberately import-isolated from the online runtime: no module
under ``app.research`` may be imported by ``app.api``, ``app.services``,
``app.agents``, ``app.defense`` or any other online path. The isolation is
asserted by ``tests/test_research_isolation.py``.
"""
