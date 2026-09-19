"""The base of vernier's exception hierarchy.

Specific errors live beside the code that raises them; they all inherit from
this one so a caller can catch everything vernier raises with a single except
clause without also catching bugs in its own code.
"""

from __future__ import annotations


class VernierError(Exception):
    """Base class for every error vernier raises."""
