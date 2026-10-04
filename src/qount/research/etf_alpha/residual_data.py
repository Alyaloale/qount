"""Causal R3 residual targets, purged inner/final slots and complete null controls."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .diagnostics import lagged_beta
from .training_data import TrainingData

FEATURES = ("return5", "return20", "return60", "return120", "rv20", "rv60", "drawdown252", "ma_distance200")
RIDGES = ("R3-ridge-residual", "R3-ridge-residual-time-shuffle")
NEURALS = ("R3-mlp-residual", "R3-mlp-residual-time-shuffle", "R3-mlp-residual-time-and-asset-shuffle")
REAL = (RIDGES[0], NEURALS[0])
BASELINES = ("zero_residual_reconstruction", "asset_train_mean", "momentum120", "cash")
FAMILIES = (*RIDGES, *NEURALS, *BASELINES)


@dataclass(frozen=True)
class Slot:
    name: str
    year: int
    kind: str
    train_rows: np.ndarray
    checkpoint_rows: np.ndarray
    evaluation_rows: np.ndarray
    evaluation_label_rows: np.ndarray

    def contract(self):
        return {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in asdict(self).items()}


def build_slots(data: TrainingData, beta, *, features=FEATURES):
    """Only 20-day labels purge; inner IC tails are known before the next year."""
    columns = [data.names.index(k) for k in features]
    ready = data.available[:, :, columns].all((1, 2)) & np.isfinite(beta).all(1)
    complete = ready & data.masks["mu20"].all(1)
    days, ends = np.asarray(data.dates), data.end_rows[20]
    lower = days >= "2015-01-01"

    def labelled(first, last, boundary):
        edge = int(np.searchsorted(days, boundary))
        return np.flatnonzero(lower & (days >= first) & (days < last) & complete & (ends >= 0) & (ends < edge-5))

    slots = []
    for kind, years in (("inner", range(2017, 2026)), ("final", range(2020, 2027))):
        for year in years:
            start, end = f"{year}-01-01", f"{year+1}-01-01"
            evaluation = np.flatnonzero((days >= start) & (days < end))
            if not len(evaluation) or not ready[evaluation].all():
                raise ValueError("complete evaluation execution calendar and causal features required")
            if kind == "inner":
                checkpoint_start = f"{year-1}-01-01"
                train = labelled("2015-01-01", checkpoint_start, checkpoint_start)
                checkpoint = labelled(checkpoint_start, start, start)
                labels = labelled(start, end, end)
            else:
                train = labelled("2015-01-01", start, start)
                checkpoint, labels = np.array([],dtype=int), np.array([],dtype=int)
            if len(train) < 120 or kind == "inner" and (not len(checkpoint) or not len(labels)):
                raise ValueError("insufficient causal training/checkpoint/evaluation labels")
            slots.append(Slot(f"{kind}_{year}",year,kind,train,checkpoint,evaluation,labels))
    return slots


@dataclass(frozen=True)
class ResidualTransform:
    means: np.ndarray
    kappa: np.ndarray
    scale: float
    spy: int

    def residual(self, data, rows, realised_cash, beta):
        excess = data.targets["mu20"][rows] - realised_cash[rows,None]
        value = excess-self.means-beta[rows]*(excess[:,self.spy]-self.means[self.spy])[:,None]-self.kappa
        value[:,self.spy] = 0.
        return value

    def reconstruct(self, forecast_cash, market_prediction, beta, residual):
        base = forecast_cash[:,None]+self.means+self.kappa+beta*(market_prediction-forecast_cash-self.means[self.spy])[:,None]
        result = base+residual
        result[:,self.spy] = market_prediction
        return result

    def contract(self):
        return {"means":self.means.tolist(),"kappa":self.kappa.tolist(),"scale":self.scale,"spy":self.spy}


def target_context(data, panel):
    beta = lagged_beta(panel)
    spy = data.symbols.index("SPY")
    beta[np.isfinite(beta[:,spy]),spy] = 1.
    realised = np.full(len(data.dates),np.nan)
    start,end = data.start_rows,data.end_rows[20]
    valid = (start>=0)&(end>=0)
    realised[valid] = panel.cash_open[end[valid]]/panel.cash_open[start[valid]]-1
    forecast = np.full(len(data.dates),np.nan)
    forecast[20:] = panel.cash_close[20:]/panel.cash_close[:-20]-1
    return beta,realised,forecast


def fit_transform(data, rows, realised_cash, beta):
    """Preprocessing statistics only; no Ridge or neural fitting occurs here."""
    spy = data.symbols.index("SPY")
    excess = data.targets["mu20"][rows]-realised_cash[rows,None]
    if not np.isfinite(excess).all() or not np.isfinite(beta[rows]).all():
        raise ValueError("complete past-only residual training observations required")
    means = excess.mean(0)
    uncentered = excess-means-beta[rows]*(excess[:,spy]-means[spy])[:,None]
    kappa = uncentered.mean(0)
    kappa[spy] = 0.
    indices = [i for i in range(len(data.symbols)) if i != spy]
    residual = (uncentered-kappa)[:,indices]
    scale = max(float(residual.std(ddof=1)),1e-6)
    return ResidualTransform(means,kappa,scale,spy)


def prepare_slot(data, panel, raw, slot, context):
    beta,realised,forecast = context
    transform = fit_transform(data,slot.train_rows,realised,beta)
    columns = [data.names.index(k) for k in FEATURES]
    learned = [i for i in range(len(data.symbols)) if i != transform.spy]
    momentum = raw[:,:,data.names.index("return120")]/6
    values = {}
    for name,rows in (("train",slot.train_rows),("checkpoint",slot.checkpoint_rows),("evaluation",slot.evaluation_rows)):
        values[f"{name}_rows"] = rows
        values[f"{name}_x"] = data.assets[rows][:,learned][:,:,columns].astype(np.float32)
        if name != "evaluation":
            y = transform.residual(data,rows,realised,beta)[:,learned]/transform.scale
            values[f"{name}_y"] = y.astype(np.float32)
            values[f"{name}_mask"] = np.isfinite(y)
    rows = slot.evaluation_rows
    zero = np.zeros((len(rows),len(data.symbols)))
    values["evaluation_base"] = transform.reconstruct(forecast[rows],momentum[rows,transform.spy],beta[rows],zero)
    values["evaluation_asset_train_mean"] = np.broadcast_to(transform.means+forecast[rows,None],zero.shape).copy()
    values["evaluation_momentum120"] = momentum[rows].copy()
    values["evaluation_cash"] = np.broadcast_to(forecast[rows,None],zero.shape).copy()
    values["learned_columns"] = np.asarray(learned)
    values["scale"] = np.asarray(transform.scale)
    if slot.kind == "inner":
        label_mask = np.isin(rows,slot.evaluation_label_rows)
        y = transform.residual(data,rows,realised,beta)[:,learned]/transform.scale
        mask = data.masks["mu20"][rows][:,learned]&label_mask[:,None]&np.isfinite(y)
        values["evaluation_y"] = np.where(mask,y,0).astype(np.float32)
        values["evaluation_mask"] = mask
    if any(not np.isfinite(v).all() for k,v in values.items() if k.endswith(("_x","_base","_y"))):
        raise ValueError("nonfinite residual preparation")
    return values,transform


def null_permutation(length, seed, *, block=60, minimum_shift=1):
    """Permute intact date chunks, excluding registered near-date label pairs."""
    if length < 2*block or block != 60 or not 1<=minimum_shift<=block:
        raise ValueError("two complete registered date blocks required")
    chunks = [np.arange(i,min(i+block,length)) for i in range(0,length,block)]
    rng = np.random.default_rng(seed)
    for _ in range(1000):
        result = np.concatenate([chunks[i] for i in rng.permutation(len(chunks))])
        if np.all(np.abs(result-np.arange(length))>=minimum_shift):
            return result
    raise ValueError("could not construct the registered separated-date null control")


def shuffled_labels(y,mask,seed,*,asset_shuffle=False,minimum_shift=1):
    permutation = null_permutation(len(y),seed,minimum_shift=minimum_shift)
    target,available = y[permutation].copy(),mask[permutation].copy()
    asset_permutations = []
    if asset_shuffle:
        rng = np.random.default_rng(seed+20261003)
        for first in range(0,len(target),60):
            columns = rng.permutation(target.shape[1])
            target[first:first+60] = target[first:first+60][:,columns]
            available[first:first+60] = available[first:first+60][:,columns]
            asset_permutations.append(columns.tolist())
    return target,available,{"date_permutation":permutation.tolist(),"unchanged_date_pairs":0,
                             "minimum_date_shift":int(np.abs(permutation-np.arange(len(y))).min()),
                             "minimum_shift_required":minimum_shift,"asset_permutations":asset_permutations}


def epoch_schedule(year,inner_fits,seeds):
    """Future receipts cannot enter an earlier outer fit's fixed epoch count."""
    result = {}
    for family in NEURALS:
        result[family] = {}
        for seed in seeds:
            receipts = [inner_fits[f"inner_{y}"][family][str(seed)] for y in range(year-3,year)]
            if any(r["status"] != "complete" or not 0<=r["best_epoch"]<80 for r in receipts):
                raise ValueError("three complete past checkpoint receipts required")
            result[family][str(seed)] = max(1,min(80,int(np.median([r["best_epoch"]+1 for r in receipts]))))
    return result
