"""Expanding past-only annual folds; purge actual label intervals, not calendar days."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .labels import Labels


@dataclass(frozen=True)
class Fold:
    fold_id: str
    train_rows: np.ndarray
    validation_rows: np.ndarray
    test_rows: np.ndarray  # all execution days; no removal of tail-label or embargo days
    test_label_rows: dict[int, np.ndarray]
    validation_start: str
    test_start: str
    test_end: str
    embargo_sessions: int

    def contract(self) -> dict:
        return {"fold_id": self.fold_id, "train_rows": self.train_rows.tolist(),
                "validation_rows": self.validation_rows.tolist(), "test_rows": self.test_rows.tolist(),
                "test_label_rows": {str(h): r.tolist() for h, r in self.test_label_rows.items()},
                "validation_start": self.validation_start, "test_start": self.test_start,
                "test_end": self.test_end, "embargo_sessions": self.embargo_sessions,
                "train_targets_start": "2015-01-01", "holdout_role": "discovery"}


def expanding_folds(dates: tuple[str, ...], labels: Labels, ready: np.ndarray,
                    *, embargo_sessions: int = 5) -> list[Fold]:
    if embargo_sessions < 0 or np.shape(ready) != (len(dates),):
        raise ValueError("valid embargo and date-level feature availability required")
    days = np.asarray(dates)
    longest = max(labels.end_rows)
    ends = labels.end_rows[longest]
    # All assets share the decision date; no same-date asset train/test split.
    complete = labels.available[f"mu{longest}"].all(axis=1) & ready
    folds = []
    for year in range(2020, 2027):
        validation_start, test_start = f"{year-1}-01-01", f"{year}-01-01"
        va, te = np.searchsorted(days, [validation_start, test_start])
        test = np.flatnonzero((days >= test_start) & (days < f"{year+1}-01-01"))
        if not test.size:
            continue
        train = np.flatnonzero((days >= "2015-01-01") & (days < validation_start) & complete
                               & (ends >= 0) & (ends < va - embargo_sessions))
        validation = np.flatnonzero((days >= validation_start) & (days < test_start) & complete
                                    & (ends >= 0) & (ends < te - embargo_sessions))
        test_labels = {h: test[ready[test] & labels.available[f"mu{h}"][test].all(axis=1)]
                       for h in labels.end_rows}
        if not train.size or not validation.size:
            raise ValueError(f"WF{year}: no eligible train/validation samples")
        folds.append(Fold(f"WF{year}", train, validation, test, test_labels,
                          validation_start, test_start, dates[test[-1]], embargo_sessions))
    return folds
