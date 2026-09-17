"""Which source connectors this build ships.

Mnemify's tree carries eight harvester plugins, but the released build
exposes **three**: Notion, Confluence and Obsidian. That is a *release
scope* decision, not a code-quality one — the other five (Jira, Slack,
GitHub, Gmail, Calendar) are complete, tested, and stay in the tree. They
are hidden because shipping them would mean supporting five more credential
flows (two of them OAuth) in a tool a user installs with one command, and
because the Google client libraries alone add ~100 MB to the venv.

What "enabled" gates:

* ``harvester.registry._ensure_plugins_registered()`` imports only enabled
  plugin packages, so ``registered_source_types()`` lists only those and
  ``create_plugin("jira", …)`` raises a clean "unknown source type".
* ``GET /api/connections`` filters its output, so a leftover ``sources.jira``
  block in someone's ``mnemify.yaml`` cannot surface a card in the UI.

What it does **not** gate: the plugin code itself. Importing
``src.harvester.jira`` directly still works and its tests still run — that
is how the disabled connectors stay alive rather than bit-rotting.

Dev override: ``MNEMIFY_SOURCES=notion,jira,slack`` (comma-separated) turns
any subset back on for the current process. Unrecognised names are kept as
given — the registry simply tries to import ``src.harvester.<name>`` and
silently skips it if there is no such package.
"""

from __future__ import annotations

import os

SOURCES_ENV = "MNEMIFY_SOURCES"

#: Connectors the shipped build exposes.
ENABLED_SOURCES: tuple[str, ...] = ("notion", "confluence", "obsidian")

#: Present in the tree, deliberately not exposed. Listed for documentation
#: and so ``MNEMIFY_SOURCES`` users know what names are available.
EXPERIMENTAL_SOURCES: tuple[str, ...] = (
    "jira",
    "slack",
    "github",
    "gmail",
    "calendar",
)


def enabled_sources() -> tuple[str, ...]:
    """The enabled connector names, honouring ``MNEMIFY_SOURCES``.

    Read at call time (never cached) so a test or a dev shell can flip the
    set without import-order surprises — the same rule ``src.paths`` follows.
    """
    override = os.environ.get(SOURCES_ENV)
    if override is None:
        return ENABLED_SOURCES
    names = tuple(part.strip() for part in override.split(",") if part.strip())
    # An empty/whitespace-only override is a typo, not "disable everything".
    return names or ENABLED_SOURCES


def is_enabled(name: str) -> bool:
    return name in enabled_sources()
