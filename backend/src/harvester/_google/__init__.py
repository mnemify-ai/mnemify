"""Internal shared infra for Google-provider source plugins.

Not a source plugin itself — the plugin registry never imports this
package. It exists so Gmail, Drive, Calendar, etc. can share one
Mnemify-owned OAuth client and the same auth plumbing instead of
each shipping its own. Each consumer plugin imports from
:mod:`src.harvester._google.oauth` with its own scope list and token
path.
"""
