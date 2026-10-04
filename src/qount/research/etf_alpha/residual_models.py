"""Registered 161-parameter shared residual predictor, with no identity channel."""
import torch
from torch import nn


class ResidualPredictor(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(8,16),nn.GELU(),nn.Dropout(.1),nn.Linear(16,1))
        if sum(p.numel() for p in self.parameters()) != 161:
            raise AssertionError("registered residual model parameter count changed")

    def forward(self,assets):
        if assets.ndim != 3 or assets.shape[1:] != (8,8):
            raise ValueError("eight residual assets and eight causal features required")
        return self.layers(assets).squeeze(-1)
