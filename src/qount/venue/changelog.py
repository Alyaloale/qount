"""Changelog diff utility for venue capability provenance."""

from __future__ import annotations

from qount.venue.contracts import ChangelogDiff


def diff_changelog(
    *,
    venue: str,
    previous_source_hash: str,
    current_source_hash: str,
    previous_observed_at: str,
    current_observed_at: str,
) -> ChangelogDiff:
    """Create a ChangelogDiff between two changelog observations.

    If the source hashes differ, text_changed and review_required
    are both True.  The diff is an immutable artifact.
    """
    return ChangelogDiff.create(
        venue=venue,
        previous_source_hash=previous_source_hash,
        current_source_hash=current_source_hash,
        previous_observed_at=previous_observed_at,
        current_observed_at=current_observed_at,
    )
