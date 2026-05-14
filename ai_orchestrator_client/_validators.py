"""Client-side input validation that mirrors server-side guards.

Mirroring is intentional: the server still validates everything (the
client is untrusted from its perspective), but catching obvious errors
client-side turns opaque HTTP 422 responses into typed exceptions with
helpful messages, before the request leaves the process.

If you change the regex here, also change the server constant — they
must stay byte-identical.
"""
from __future__ import annotations

import re

from ._errors import ProjectNameInvalidError

# Mirrors SAFE_FILENAME in app.py / api/routes.py on the orchestrator.
# Pattern explanation:
#   ^(?!.*\.\.)     — anywhere-in-string negative lookahead for ".."
#                     (blocks path traversal)
#   [a-zA-Z0-9_\-\.]+  — one or more allowed characters
#   $               — full-string match
SAFE_FILENAME_PATTERN = re.compile(r"^(?!.*\.\.)[a-zA-Z0-9_\-\.]+$")

_EXAMPLES_VALID = ("naca0012-baseline", "riblet_sweep_v3", "run.42")
_EXAMPLES_INVALID = ("My Project!", "foo/bar", "../etc/passwd", "")


def validate_project_name(name: str) -> str:
    """Return ``name`` unchanged if valid, else raise ``ProjectNameInvalidError``.

    Valid names match ``^(?!.*\\.\\.)[a-zA-Z0-9_\\-\\.]+$`` — letters,
    digits, underscore, hyphen, dot; no spaces, slashes, ``..``, or
    other punctuation.

    Examples:
        >>> validate_project_name("naca0012-baseline")
        'naca0012-baseline'
        >>> validate_project_name("My Project!")
        Traceback (most recent call last):
            ...
        ai_orchestrator_client._errors.ProjectNameInvalidError: ...
    """
    if not isinstance(name, str) or not SAFE_FILENAME_PATTERN.match(name):
        raise ProjectNameInvalidError(name)
    return name
