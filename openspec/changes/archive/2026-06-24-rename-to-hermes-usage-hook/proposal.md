## Summary

Rename the project from hermes-codex-usage-hook to hermes-usage-hook so the name reflects that the hook now serves multiple providers (Codex, MiniMax, and any future registry entry), not Codex alone.

## Motivation

The repo started as a Codex-only usage hook, but the footer hook now detects the provider from each reply's model and fetches that provider's usage (Codex, MiniMax, extensible via the usage.py registry). The "codex" token in the project name, the User-Agent strings, the stderr log prefix, and the GitHub repository name/description are all now misleading. The GitHub description is doubly stale: it names only Codex and still says usage is reported "at the end of each conversation", which described the removed on_session_end notifier rather than the current per-reply footer.

This is a pure identity rename. The Codex provider module (codex_usage.py) keeps its name because it is the Codex provider implementation, not the project name.

## Proposed Solution

- Update the stderr log prefix emitted on footer-hook failure from the old project name to the new one, in hooks/footer_hook.py, and update the provider-detection spec scenario that documents that prefix.
- Update the outbound User-Agent header in codex_usage.py and minimax_usage.py to the new project name.
- Update README.md: the H1 title, the clone and cd commands, the deployed footer plugin filename (drop the codex token), and the troubleshooting reference to the log prefix.
- Rename the GitHub repository and update its description via the gh CLI; the rename also updates the local origin remote URL.

## Non-Goals

- Not renaming codex_usage.py or minimax_usage.py module files; those are provider module names, not the project name, and renaming them would break imports and provider semantics.
- Not changing any runtime behavior, provider-detection logic, or usage output beyond the literal log-prefix string.
- Not renaming the local working-directory folder in this session; that is left as a manual follow-up step for the user because changing the working directory mid-session breaks absolute paths.

## Alternatives Considered

- Keep the name and only update the description: rejected, the name itself is the most visible stale Codex reference.
- Leave the log prefix as the old name to avoid touching a spec: rejected, it would leave the failure log inconsistent with the new name; routing the change through a spec delta is the project's required discipline for modifying documented behavior.

## Impact

- Affected specs: provider-detection (modified)
- Affected code:
  - Modified:
    - hooks/footer_hook.py
    - codex_usage.py
    - minimax_usage.py
    - README.md
  - New: (none)
  - Removed: (none)
- External (ops, not version-controlled): GitHub repository name and description, local origin remote URL (updated by the rename), and the local working-directory folder (manual user follow-up).
