"""Fixed v2 shared cross-sectional predictor; no hyperparameter search."""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class ExpandedSpec:
    identity: bool = False
    rank_weight: float = 0.0
    heads: tuple[str, ...] = ("mu20",)
    asset_dim: int = 84

    def __post_init__(self):
        if self.asset_dim != 84 or self.heads != ("mu20",) or self.rank_weight not in (0.0, .3):
            raise ValueError("fixed v2 schema and ranking weights required")

    @property
    def parameters(self):
        return (self.asset_dim + (8 if self.identity else 0) + 1) * 128 + 129 * 64 + 2 * (128 + 64) + 18 * 32 + 161 * 64 + 65 + (72 if self.identity else 0)


class ExpandedPredictor(nn.Module):
    def __init__(self, spec: ExpandedSpec):
        super().__init__()
        self.spec = spec
        if spec.identity:
            self.identity = nn.Embedding(9, 8)
        self.asset_encoder = nn.Sequential(nn.Linear(84 + (8 if spec.identity else 0), 128),
            nn.LayerNorm(128), nn.GELU(), nn.Dropout(.1), nn.Linear(128, 64),
            nn.LayerNorm(64), nn.GELU(), nn.Dropout(.1))
        self.market_encoder = nn.Sequential(nn.Linear(17, 32), nn.GELU())
        self.output = nn.Sequential(nn.Linear(160, 64), nn.GELU(), nn.Linear(64, 1))

    def forward(self, assets, market, asset_ids=None):
        if self.spec.identity:
            ids = torch.arange(9, device=assets.device) if asset_ids is None else asset_ids
            identity = self.identity(ids)[None].expand(assets.shape[0], -1, -1)
            assets = torch.cat((assets, identity), -1)
        encoded = self.asset_encoder(assets)
        pooled = encoded.mean(1, keepdim=True).expand_as(encoded)
        context = self.market_encoder(market)[:, None].expand(-1, 9, -1)
        return {"mu20": self.output(torch.cat((encoded, pooled, context), -1)).squeeze(-1)}
