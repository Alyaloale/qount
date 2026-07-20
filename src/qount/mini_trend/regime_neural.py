"""Fixed small-GRU discovery model for the MiniTrend regime dataset."""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from qount.artifacts import write_research_json_artifact
from qount.mini_trend.regime_ml import FEATURE_NAMES, REGIME_LABELS
from qount.mini_trend.regime_ml import _metrics, _normalize_probabilities
from qount.models import utc_now
from qount.settings import Settings


REGIME_NEURAL_VERSION = "mini_trend_regime_neural_discovery_v0.1"


@dataclass(frozen=True)
class RegimeGRUConfig:
    sequence_length: int = 60
    hidden_size: int = 32
    num_layers: int = 1
    batch_size: int = 64
    maximum_epochs: int = 80
    early_stopping_patience: int = 10
    learning_rate: float = 0.001
    weight_decay: float = 0.001
    label_smoothing: float = 0.05
    validation_fraction: float = 0.20
    seed: int = 20260718
    trial_count: int = 1

    @property
    def contract_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "config": asdict(self),
                    "features": list(FEATURE_NAMES),
                    "labels": list(REGIME_LABELS),
                    "architecture": "GRU -> LayerNorm -> Linear(3)",
                    "split": "expanding annual test; tail validation; label-end purge",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def build_sequence_samples(
    rows: Sequence[Mapping[str, Any]], sequence_length: int
) -> list[dict[str, Any]]:
    import numpy as np

    samples = []
    for index in range(sequence_length - 1, len(rows)):
        window = rows[index - sequence_length + 1 : index + 1]
        first = dt.date.fromisoformat(window[0]["decision_date"])
        last = dt.date.fromisoformat(window[-1]["decision_date"])
        if (last - first).days != sequence_length - 1:
            continue
        samples.append(
            {
                "decision_date": rows[index]["decision_date"],
                "label_end_date": rows[index]["label_end_date"],
                "label": rows[index]["label"],
                "values": np.asarray(
                    [
                        [float(row["features"][name]) for name in FEATURE_NAMES]
                        for row in window
                    ],
                    dtype=np.float32,
                ),
            }
        )
    return samples


def _state_hash(torch, model) -> str:
    blob = io.BytesIO()
    torch.save(model.state_dict(), blob)
    return hashlib.sha256(blob.getvalue()).hexdigest()


def _constant_probabilities(
    train_labels: Sequence[str], count: int
) -> list[list[float]]:
    distribution = [train_labels.count(label) / len(train_labels) for label in REGIME_LABELS]
    return [list(distribution) for _ in range(count)]


def _train_fold(
    train_samples: Sequence[Mapping[str, Any]],
    test_samples: Sequence[Mapping[str, Any]],
    config: RegimeGRUConfig,
    *,
    seed: int,
    requested_device: str,
) -> tuple[dict[str, Any], list[list[float]]]:
    import numpy as np
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.set_num_threads(min(os.cpu_count() or 1, 8))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.use_deterministic_algorithms(True)

    validation_index = max(int(len(train_samples) * (1.0 - config.validation_fraction)), 1)
    validation_start = train_samples[validation_index]["decision_date"]
    train_core = [
        sample for sample in train_samples if sample["label_end_date"] < validation_start
    ]
    validation = [
        sample for sample in train_samples if sample["decision_date"] >= validation_start
    ]
    if not train_core or not validation:
        raise ValueError("insufficient purged train/validation samples")

    train_values = np.asarray([sample["values"] for sample in train_core], dtype=np.float32)
    validation_values = np.asarray([sample["values"] for sample in validation], dtype=np.float32)
    test_values = np.asarray([sample["values"] for sample in test_samples], dtype=np.float32)
    mean = train_values.reshape(-1, train_values.shape[-1]).mean(axis=0)
    std = train_values.reshape(-1, train_values.shape[-1]).std(axis=0)
    std = np.where(std > 1e-8, std, 1.0)
    train_values = (train_values - mean) / std
    validation_values = (validation_values - mean) / std
    test_values = (test_values - mean) / std
    train_labels = np.asarray(
        [REGIME_LABELS.index(sample["label"]) for sample in train_core], dtype=np.int64
    )
    validation_labels = np.asarray(
        [REGIME_LABELS.index(sample["label"]) for sample in validation], dtype=np.int64
    )

    class GRUClassifier(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.gru = nn.GRU(
                input_size=len(FEATURE_NAMES),
                hidden_size=config.hidden_size,
                num_layers=config.num_layers,
                batch_first=True,
            )
            self.norm = nn.LayerNorm(config.hidden_size)
            self.output = nn.Linear(config.hidden_size, len(REGIME_LABELS))

        def forward(self, values):
            encoded, _ = self.gru(values)
            return self.output(self.norm(encoded[:, -1, :]))

    device = torch.device(
        "cuda"
        if requested_device == "auto" and torch.cuda.is_available()
        else requested_device
    )
    model = GRUClassifier().to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    loss_function = nn.CrossEntropyLoss(label_smoothing=config.label_smoothing)
    loader = DataLoader(
        TensorDataset(torch.from_numpy(train_values), torch.from_numpy(train_labels)),
        batch_size=config.batch_size,
        shuffle=False,
    )
    validation_x = torch.from_numpy(validation_values).to(device)
    validation_y = torch.from_numpy(validation_labels).to(device)
    best_loss = math.inf
    best_state = None
    best_epoch = 0
    patience = 0
    started = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    for epoch in range(1, config.maximum_epochs + 1):
        model.train()
        for values, labels in loader:
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(values.to(device)), labels.to(device))
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            validation_loss = float(loss_function(model(validation_x), validation_y).item())
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {
                key: value.detach().cpu().clone() for key, value in model.state_dict().items()
            }
            patience = 0
        else:
            patience += 1
            if patience >= config.early_stopping_patience:
                break
    if best_state is None:
        raise RuntimeError("GRU training produced no checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        probabilities = torch.softmax(model(torch.from_numpy(test_values).to(device)), dim=1)
        probability_rows = probabilities.detach().cpu().numpy().tolist()
    elapsed = time.perf_counter() - started
    peak_memory = (
        int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
    )
    return (
        {
            "device": str(device),
            "device_name": (
                torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu"
            ),
            "torch_version": torch.__version__,
            "torch_cuda_version": torch.version.cuda,
            "train_rows_before_validation_purge": len(train_samples),
            "train_rows": len(train_core),
            "validation_rows": len(validation),
            "validation_start_date": validation_start,
            "train_last_label_end_date": max(sample["label_end_date"] for sample in train_core),
            "validation_purge_check_passed": max(
                sample["label_end_date"] for sample in train_core
            )
            < validation_start,
            "best_epoch": best_epoch,
            "epochs_run": epoch,
            "best_validation_loss": best_loss,
            "model_state_hash": _state_hash(torch, model),
            "elapsed_seconds": elapsed,
            "peak_gpu_memory_bytes": peak_memory,
        },
        _normalize_probabilities(probability_rows),
    )


def run_regime_gru_walk_forward(
    dataset: Mapping[str, Any],
    config: RegimeGRUConfig | None = None,
    *,
    requested_device: str = "auto",
) -> dict[str, Any]:
    config = config or RegimeGRUConfig()
    rows = list(dataset["rows"])
    samples = build_sequence_samples(rows, config.sequence_length)
    folds = []
    test_years = tuple(int(year) for year in dataset["contract"]["test_years"])
    for test_year in test_years:
        test_start = dt.date(test_year, 1, 1)
        test_end = dt.date(test_year, 12, 31)
        train = [
            sample
            for sample in samples
            if dt.date.fromisoformat(sample["label_end_date"]) < test_start
        ]
        test = [
            sample
            for sample in samples
            if test_start <= dt.date.fromisoformat(sample["decision_date"]) <= test_end
        ]
        if not train or not test:
            continue
        training, probabilities = _train_fold(
            train,
            test,
            config,
            seed=config.seed + test_year,
            requested_device=requested_device,
        )
        actual = [sample["label"] for sample in test]
        metrics = _metrics(actual, probabilities)
        baseline = _metrics(actual, _constant_probabilities([row["label"] for row in train], len(test)))
        metrics["log_loss_improvement_vs_constant"] = baseline["log_loss"] - metrics["log_loss"]
        metrics["brier_improvement_vs_constant"] = (
            baseline["multiclass_brier"] - metrics["multiclass_brier"]
        )
        folds.append(
            {
                "test_year": test_year,
                "test_rows": len(test),
                "test_first_date": test[0]["decision_date"],
                "test_last_date": test[-1]["decision_date"],
                "constant_baseline": baseline,
                "training": training,
                "gru": metrics,
            }
        )
    model_rows = [fold["gru"] for fold in folds]
    return {
        "schema_version": REGIME_NEURAL_VERSION,
        "artifact_type": "mini_trend_regime_gru_walk_forward",
        "created_at": utc_now().isoformat(),
        "meta": {
            "research_only": True,
            "holdout_role": "consumed_historical_discovery_pool",
            "paper_or_live_allowed": False,
        },
        "dataset_contract_hash": dataset["contract"]["contract_hash"],
        "dataset_data_hash": dataset["data_hash"],
        "contract": {**asdict(config), "contract_hash": config.contract_hash},
        "folds": folds,
        "aggregate": {
            "fold_count": len(folds),
            "mean_balanced_accuracy": statistics_mean(
                [row["balanced_accuracy"] for row in model_rows]
            ),
            "mean_macro_f1": statistics_mean([row["macro_f1"] for row in model_rows]),
            "mean_log_loss_improvement_vs_constant": statistics_mean(
                [row["log_loss_improvement_vs_constant"] for row in model_rows]
            ),
            "mean_brier_improvement_vs_constant": statistics_mean(
                [row["brier_improvement_vs_constant"] for row in model_rows]
            ),
            "positive_brier_improvement_fold_count": sum(
                row["brier_improvement_vs_constant"] > 0 for row in model_rows
            ),
            "positive_log_loss_improvement_fold_count": sum(
                row["log_loss_improvement_vs_constant"] > 0 for row in model_rows
            ),
            "total_elapsed_seconds": sum(
                fold["training"]["elapsed_seconds"] for fold in folds
            ),
            "maximum_peak_gpu_memory_bytes": max(
                (fold["training"]["peak_gpu_memory_bytes"] for fold in folds),
                default=0,
            ),
        },
        "diagnostics": {
            "all_validation_purge_checks_passed": bool(folds)
            and all(fold["training"]["validation_purge_check_passed"] for fold in folds),
            "trial_count": config.trial_count,
            "verdict": "gru_discovery_evaluated" if folds else "insufficient_gru_folds",
            "paper_or_live_allowed": False,
        },
    }


def statistics_mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def write_regime_neural_artifact(
    settings: Settings,
    payload: dict[str, Any],
    *,
    explicit_path: str | None = None,
) -> dict[str, Any]:
    return write_research_json_artifact(
        settings,
        payload,
        kind="mini-trend-regime-neural-discovery",
        path_key="artifact_path",
        default_filename="mini_trend_regime_neural_discovery.json",
        explicit_path=explicit_path,
    )
