"""Small shared predictors. Torch is confined to the research compute path."""
from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

HEADS = ("mu5", "mu20", "mu60", "sigma20", "p_up", "q10")


@dataclass(frozen=True)
class ModelSpec:
    asset_dim: int = 38
    heads: tuple[str, ...] = ("mu20",)
    market: str = "none"
    market_dim: int = 17
    sequence: int = 60

    def __post_init__(self):
        if self.asset_dim not in (3, 38) or self.market not in ("none", "mlp", "gru"):
            raise ValueError("unsupported frozen model configuration")
        if "mu20" not in self.heads or len(set(self.heads)) != len(self.heads):
            raise ValueError("unique heads including mu20 required")
        if not set(self.heads).issubset(HEADS) or self.market_dim != 17 or self.sequence != 60:
            raise ValueError("unsupported head or market schema")

    @property
    def parameters(self) -> int:
        inputs = self.asset_dim + (16 if self.market != "none" else 0)
        count = (inputs + 1) * 64 + 65 * 32 + 33 * 32 + 2 * (64 + 32 + 32)
        count += 33 * len(self.heads)
        if self.market == "mlp":
            count += 18 * 160 + 161 * 16 + 32
        elif self.market == "gru":
            count += 3 * 32 * 17 + 3 * 32 * 32 + 6 * 32 + 33 * 16 + 32
        return count


class SharedPredictor(nn.Module):
    def __init__(self, spec: ModelSpec):
        super().__init__()
        self.spec = spec
        if spec.market == "gru":
            self.market_encoder = nn.GRU(17, 32, num_layers=1, batch_first=True)
            self.market_projection = nn.Linear(32, 16)
        elif spec.market == "mlp":
            self.market_encoder = nn.Sequential(nn.Linear(17, 160), nn.GELU())
            self.market_projection = nn.Linear(160, 16)
        if spec.market != "none":
            self.market_input_dropout = nn.Dropout(0.1)
            self.market_output = nn.Sequential(nn.LayerNorm(16), nn.Dropout(0.1))
        widths = (spec.asset_dim + (16 if spec.market != "none" else 0), 64, 32, 32)
        layers = []
        for index, (a, b) in enumerate(zip(widths, widths[1:])):
            layers.extend((nn.Linear(a, b), nn.LayerNorm(b), nn.GELU()))
            if index < 2:
                layers.append(nn.Dropout(0.1))
        self.asset_encoder = nn.Sequential(*layers)
        self.heads = nn.ModuleDict({name: nn.Linear(32, 1) for name in spec.heads})
        if sum(p.numel() for p in self.parameters()) != spec.parameters:
            raise AssertionError("model parameters differ from the frozen architecture")

    def forward(self, assets, market=None):
        if assets.ndim != 3 or assets.shape[-1] != self.spec.asset_dim:
            raise ValueError("assets must have shape (dates, assets, features)")
        if self.spec.market != "none":
            if market is None or market.shape != (len(assets), self.spec.sequence, 17):
                raise ValueError("complete trailing market windows required")
            if self.spec.market == "gru":
                # Omitting h_0 resets the state independently for every window.
                _, hidden = self.market_encoder(self.market_input_dropout(market))
                context = hidden[-1]
            else:
                context = self.market_encoder(self.market_input_dropout(market[:, -1]))
            embedding = self.market_output(self.market_projection(context))
            shared = embedding[:, None, :].expand(-1, assets.shape[1], -1)
            assets = torch.cat((assets, shared), dim=-1)
        latent = self.asset_encoder(assets)
        return {name: layer(latent).squeeze(-1) for name, layer in self.heads.items()}

    def initialize_head_biases(self, biases: dict[str, float]) -> None:
        """Auxiliary intercepts use train-only statistics, never validation."""
        with torch.no_grad():
            for name, layer in self.heads.items():
                layer.bias.fill_(biases.get(name, 0.0))


def adamw(model: SharedPredictor, *, lr=3e-4, decay=1e-4, betas=(0.9, 0.999), eps=1e-8):
    matrices, vectors = [], []
    for parameter in model.parameters():
        (matrices if parameter.ndim >= 2 else vectors).append(parameter)
    return torch.optim.AdamW(
        [{"params": matrices, "weight_decay": decay}, {"params": vectors, "weight_decay": 0.0}],
        lr=lr, betas=betas, eps=eps,
    )
