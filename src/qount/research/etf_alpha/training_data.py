"""Frozen input loading, causal windows and train-only target transforms."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import math
from pathlib import Path

import numpy as np

from .artifacts import read_json, sha256, verify_files
from .splits import Fold

TARGETS = ("mu5", "mu20", "mu60", "sigma20", "p_up", "q10")


@dataclass
class TrainingData:
    dates: tuple[str, ...]
    symbols: tuple[str, ...]
    names: tuple[str, ...]
    assets: np.ndarray
    available: np.ndarray
    market: np.ndarray
    market_available: np.ndarray
    targets: dict[str, np.ndarray]
    masks: dict[str, np.ndarray]
    start_rows: np.ndarray
    end_rows: dict[int, np.ndarray]

    def validate(self):
        T, n = len(self.dates), len(self.symbols)
        if not T or tuple(sorted(set(self.dates))) != self.dates or len(set(self.symbols)) != n:
            raise ValueError("sorted unique dates and unique assets required")
        for day in self.dates:
            dt.date.fromisoformat(day)
        if len(self.names) != 38 or len(set(self.names)) != 38:
            raise ValueError("the frozen 38-feature schema is required")
        for values, mask, shape in (
            (self.assets, self.available, (T, n, 38)),
            (self.market, self.market_available, (T, 17)),
            *((self.targets[k], self.masks[k], (T, n)) for k in TARGETS),
        ):
            if values.shape != shape or mask.shape != shape or mask.dtype != np.bool_:
                raise ValueError("array shape or availability mask mismatch")
            if not np.isfinite(values[mask]).all() or np.isinf(values).any():
                raise ValueError("nonfinite available observation")
        starts = np.arange(T) + 1
        starts[starts >= T] = -1
        if not np.array_equal(self.start_rows, starts):
            raise ValueError("next-open entry interval mismatch")
        for horizon in (5, 20, 60):
            expected = np.arange(T) + horizon + 1
            expected[expected >= T] = -1
            if not np.array_equal(self.end_rows[horizon], expected):
                raise ValueError("next-open label end interval mismatch")
            if self.masks[f"mu{horizon}"][expected < 0].any():
                raise ValueError("unrealised tail labels must be unavailable")
        valid = self.masks["sigma20"]
        if (self.targets["sigma20"][valid] < 0).any():
            raise ValueError("realised volatility cannot be negative")
        valid = self.masks["p_up"]
        if not self.masks["mu20"][valid].all() or not np.array_equal(
            self.targets["p_up"][valid], (self.targets["mu20"][valid] > 0).astype(float)
        ):
            raise ValueError("direction labels disagree with mu20")
        valid = self.masks["q10"]
        if not self.masks["mu20"][valid].all() or not np.array_equal(
            self.targets["q10"][valid], self.targets["mu20"][valid]
        ):
            raise ValueError("pinball target must be the realised mu20, not a sample quantile")

    def windows(self, rows: np.ndarray, sequence=60) -> np.ndarray:
        rows = np.asarray(rows)
        if rows.dtype.kind not in "iu" or rows.ndim != 1 or not len(rows):
            raise ValueError("nonempty integer decision rows required")
        indices = rows[:, None] + np.arange(1 - sequence, 1)
        if indices.min() < 0 or indices.max() >= len(self.dates):
            raise ValueError("insufficient past context for market window")
        if not self.market_available[indices].all() or not np.isfinite(self.market[indices]).all():
            raise ValueError("market context is incomplete; no padding or future imputation")
        return indices

    def validate_fold(self, fold: Fold) -> dict:
        va, te = np.searchsorted(self.dates, [fold.validation_start, fold.test_start])
        partitions = (fold.train_rows, fold.validation_rows, fold.test_rows)
        for rows in partitions:
            if rows.dtype.kind not in "iu" or rows.ndim != 1 or not len(rows):
                raise ValueError("fold rows must be nonempty integer arrays")
            if rows.min() < 0 or rows.max() >= len(self.dates) or np.any(np.diff(rows) <= 0):
                raise ValueError("fold rows must be sorted, unique and in bounds")
        if set(fold.train_rows) & set(fold.validation_rows) or set(fold.validation_rows) & set(fold.test_rows):
            raise ValueError("overlapping fold partitions")
        if fold.embargo_sessions != 5:
            raise ValueError("the frozen five-session embargo is required")
        dates = np.asarray(self.dates)
        if np.any(dates[fold.train_rows] < "2015-01-01") or fold.train_rows.max() >= va:
            raise ValueError("training targets must precede validation and start in 2015")
        if fold.validation_rows.min() < va or fold.validation_rows.max() >= te:
            raise ValueError("validation decision dates are outside their partition")
        if fold.test_rows.min() < te or dates[fold.test_rows[-1]] != fold.test_end:
            raise ValueError("test execution interval mismatch")
        ends = self.end_rows[60]
        for rows, boundary in ((fold.train_rows, va), (fold.validation_rows, te)):
            if not self.available[rows].all() or not self.masks["mu60"][rows].all():
                raise ValueError("common feature and longest-label availability required")
            if np.any(ends[rows] < 0) or np.any(ends[rows] >= boundary - 5):
                raise ValueError("label overlaps the next partition or embargo")
            self.windows(rows)
        return {"train_dates": len(fold.train_rows), "validation_dates": len(fold.validation_rows),
                "test_execution_dates": len(fold.test_rows)}


def load_training_data(root: Path, expected_sha256: str) -> TrainingData:
    if sha256(root / "manifest.json") != expected_sha256:
        raise ValueError("frozen dataset manifest mismatch")
    manifest = read_json(root / "manifest.json")
    required = {"panel.npz", "features.npz", "labels.npz", "dataset-contract.json", "source-manifest.json", "calendar.csv"}
    if not required.issubset(manifest["files"]):
        raise ValueError("dataset manifest omits required inputs")
    verify_files(root, manifest["files"])
    with np.load(root / "panel.npz", allow_pickle=False) as panel, np.load(
        root / "features.npz", allow_pickle=False
    ) as features, np.load(root / "labels.npz", allow_pickle=False) as labels:
        data = TrainingData(
            tuple(panel["dates"].tolist()), tuple(panel["symbols"].tolist()), tuple(features["names"].tolist()),
            features["normalized"].copy(), features["available"].copy(),
            features["market_normalized"].copy(), features["market_available"].copy(),
            {k: labels[k].copy() for k in TARGETS}, {k: labels[f"available_{k}"].copy() for k in TARGETS},
            labels["start_rows"].copy(), {h: labels[f"end_rows_{h}"].copy() for h in (5, 20, 60)},
        )
    data.validate()
    return data


def load_folds(path: Path, dataset_contract: dict) -> list[Fold]:
    if sha256(path) != dataset_contract["contracts"]["fold-contract.json"]:
        raise ValueError("fold contract does not match the frozen dataset")
    contract = read_json(path)
    if contract["embargo_sessions"] != 5:
        raise ValueError("fold embargo mismatch")
    folds = []
    for item in contract["folds"]:
        folds.append(Fold(item["fold_id"], np.asarray(item["train_rows"]), np.asarray(item["validation_rows"]),
                          np.asarray(item["test_rows"]),
                          {int(k): np.asarray(v) for k, v in item["test_label_rows"].items()},
                          item["validation_start"], item["test_start"], item["test_end"], item["embargo_sessions"]))
    if len({f.fold_id for f in folds}) != len(folds):
        raise ValueError("duplicate fold IDs")
    return folds


@dataclass(frozen=True)
class TargetScales:
    stats: dict[str, dict[str, float]]
    initial_biases: dict[str, float]

    def transform(self, head: str, values: np.ndarray) -> np.ndarray:
        if head == "p_up":
            return values.copy()
        if head == "sigma20":
            values = np.log(np.maximum(values, 1e-6))
        scale = self.stats["mu20" if head == "q10" else head]
        return (values - scale["mean"]) / scale["std"]

    def inverse(self, head: str, values: np.ndarray) -> np.ndarray:
        scale = self.stats["mu20" if head == "q10" else head]
        return values * scale["std"] + scale["mean"]


def fit_target_scales(data: TrainingData, train_rows: np.ndarray, heads: tuple[str, ...]) -> TargetScales:
    stats, biases = {}, {}
    needed = (set(heads) - {"p_up", "q10"}) | {"mu20"}
    for head in sorted(needed):
        values = data.targets[head][train_rows][data.masks[head][train_rows]]
        if len(values) < 2:
            raise ValueError(f"{head}: insufficient train-only target observations")
        if head == "sigma20":
            values = np.log(np.maximum(values, 1e-6))
        stats[head] = {"mean": float(values.mean()), "std": max(float(values.std(ddof=1)), 1e-6)}
    if "sigma20" in heads:
        level = max(math.exp(stats["sigma20"]["mean"]) - 1e-6, 1e-12)
        biases["sigma20"] = level + math.log(-math.expm1(-level))
    if "p_up" in heads:
        values = data.targets["p_up"][train_rows][data.masks["p_up"][train_rows]]
        if not len(values):
            raise ValueError("p_up: no training observations")
        p = float(np.clip(values.mean(), 1e-4, 1 - 1e-4))
        biases["p_up"] = math.log(p / (1 - p))
    if "q10" in heads:
        values = data.targets["mu20"][train_rows][data.masks["mu20"][train_rows]]
        biases["q10"] = float((np.quantile(values, 0.1) - stats["mu20"]["mean"]) / stats["mu20"]["std"])
    return TargetScales(stats, biases)


@dataclass
class Partition:
    rows: np.ndarray
    assets: np.ndarray
    market: np.ndarray | None
    targets: dict[str, np.ndarray]
    masks: dict[str, np.ndarray]


def prepare_partition(data: TrainingData, rows: np.ndarray, scales: TargetScales,
                      heads: tuple[str, ...], columns: tuple[int, ...], *, market=False) -> Partition:
    if not data.available[rows].all():
        raise ValueError("all configurations must use the same complete feature dates")
    indices = data.windows(rows)
    return Partition(rows.copy(), np.asarray(data.assets[rows][:, :, columns], dtype=np.float32).copy(),
                     np.asarray(data.market[indices], dtype=np.float32).copy() if market else None,
                     {k: np.asarray(scales.transform(k, data.targets[k][rows]), dtype=np.float32) for k in heads},
                     {k: data.masks[k][rows].copy() for k in heads})
