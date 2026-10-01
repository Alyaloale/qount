"""Permutation-equivariant GRU trader (design §3.1–§3.2).

Per-asset inputs (12): 4 factor ranks, 4 PIT z-scored raw values, current weight, distance
to the single cap, tradable flag, log1p(ADV capacity = 5%·ADV / equity).  A shared 2-layer
MLP φ encodes each asset; mean ⊕ max pooling plus market (6) and account (6) state feed a
GRU; a linear head emits Δ_t (4) and (g, τ, b, κ).  Assets are never identified by position,
so the 9-asset US and 8-asset CN accounts share the architecture (trained separately).

Outputs are bounded and differentiable: α = softmax(log prior + tanh(·)) (each factor within
e^{±1} of the prior), g ∈ [0, 1], τ ∈ [0.03, 1] (log-scale sigmoid), b ∈ [0, 0.10],
κ ∈ [0.05, 1].  The head is initialized so that at step 0 α = prior, g ≈ 1, τ ≈ 0.2
(the fixed-scorer τ), b ≈ 0.02, κ ≈ 0.5.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import nn

from .scorer import PRIOR_ALPHA
from .universe import Account

ASSET_IN = 12
MARKET_IN = 6
ACCOUNT_IN = 6
TAU_MIN, TAU_MAX = 0.03, 1.0
BAND_MAX = 0.10
KAPPA_MIN = 0.05
DELTA_SCALE = 1.0
INIT = {"g": 0.97, "tau": 0.2, "band": 0.02, "kappa": 0.5}


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


@dataclass(frozen=True)
class PolicyConfig:
    d_phi: int = 32
    hidden: int = 64
    layers: int = 1


@dataclass
class Action:
    alpha: torch.Tensor  # (B, 4)
    gross: torch.Tensor  # (B,)
    tau: torch.Tensor
    band: torch.Tensor
    kappa: torch.Tensor


class Trader(nn.Module):
    def __init__(self, cfg: PolicyConfig = PolicyConfig()):
        super().__init__()
        self.cfg = cfg
        d = cfg.d_phi
        self.phi = nn.Sequential(nn.Linear(ASSET_IN, d), nn.SiLU(), nn.Linear(d, d), nn.SiLU())
        self.gru = nn.GRU(2 * d + MARKET_IN + ACCOUNT_IN, cfg.hidden, num_layers=cfg.layers, batch_first=True)
        self.head = nn.Linear(cfg.hidden, 8)
        self.register_buffer("log_prior", torch.log(torch.as_tensor(PRIOR_ALPHA, dtype=torch.float32)))
        with torch.no_grad():
            self.head.weight.mul_(0.01)
            self.head.bias.zero_()
            tau_u = math.log(INIT["tau"] / TAU_MIN) / math.log(TAU_MAX / TAU_MIN)
            self.head.bias[4:] = torch.tensor([_logit(INIT["g"]), _logit(tau_u), _logit(INIT["band"] / BAND_MAX),
                                               _logit((INIT["kappa"] - KAPPA_MIN) / (1 - KAPPA_MIN))])

    def initial_state(self, B: int, device=None, dtype=torch.float32) -> torch.Tensor:
        return torch.zeros(self.cfg.layers, B, self.cfg.hidden, device=device, dtype=dtype)

    def forward(self, asset: torch.Tensor, market: torch.Tensor, account: torch.Tensor,
                h: torch.Tensor) -> tuple[Action, torch.Tensor]:
        """One day: asset (B, n, 12), market (B, 6), account (B, 6), h (L, B, H)."""
        e = self.phi(asset)
        x = torch.cat([e.mean(dim=1), e.amax(dim=1), market, account], dim=-1)
        y, h = self.gru(x[:, None, :], h)
        o = self.head(y[:, 0])
        alpha = torch.softmax(self.log_prior + DELTA_SCALE * torch.tanh(o[:, :4]), dim=-1)
        tau = TAU_MIN * (TAU_MAX / TAU_MIN) ** torch.sigmoid(o[:, 5])
        act = Action(
            alpha=alpha,
            gross=torch.sigmoid(o[:, 4]),
            tau=tau,
            band=BAND_MAX * torch.sigmoid(o[:, 6]),
            kappa=KAPPA_MIN + (1 - KAPPA_MIN) * torch.sigmoid(o[:, 7]),
        )
        return act, h


def construct(ranks: torch.Tensor, sigma: torch.Tensor, eligible: torch.Tensor, act: Action,
              account: Account) -> torch.Tensor:
    """Batched :func:`scorer.construct_weights`: w ∝ exp(S/τ)/σ over eligible assets, × g,
    then single and group caps (excess to cash).  ranks (B, n, 4), sigma/eligible (B, n)."""
    score = (ranks * act.alpha[:, None, :]).sum(dim=-1)
    z = score / act.tau[:, None]
    neg = torch.finfo(z.dtype).min / 4
    z = torch.where(eligible, z, torch.full_like(z, neg))
    zmax = z.amax(dim=1, keepdim=True)
    raw = torch.where(eligible, torch.exp(z - zmax) / sigma.clamp_min(1e-12), torch.zeros_like(z))
    total = raw.sum(dim=1, keepdim=True)
    w = act.gross[:, None] * raw / total.clamp_min(1e-30)
    w = torch.clamp_max(w, account.single_cap)
    for g in account.group_indices():
        idx = list(g)
        s = w[:, idx].sum(dim=1, keepdim=True)
        w = w.clone()
        w[:, idx] = w[:, idx] * torch.where(s > account.group_cap, account.group_cap / s.clamp_min(1e-30), torch.ones_like(s))
    return w


def kl_to_prior(alpha: torch.Tensor, log_prior: torch.Tensor) -> torch.Tensor:
    return (alpha * (torch.log(alpha.clamp_min(1e-12)) - log_prior)).sum(dim=-1)


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
