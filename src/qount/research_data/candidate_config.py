"""Frozen candidate strategy configuration shared across R0 scripts.

Only captures signal-generation parameters that must be identical across
runtime, decision, and advancement scripts.  Script-specific parameters
(vol_target, symbol, universe, data_window) are tracked separately in
each bundle's manifest.

The ``config_hash`` binds the configuration for audit: all three R0
scripts must produce the same hash to prove they evaluate the same
candidate strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping

from qount.contracts.hashing import canonical_hash

CANDIDATE_CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CandidateConfig:
    """Immutable, hash-bound strategy configuration for one candidate.

    Fields:
        fast: Fast SMA period (must be positive).
        slow: Slow SMA period (must be > fast).
        regime_sma: Regime filter SMA period (0 = disabled).
        allow_short: Whether short positions are allowed.
        config_hash: SHA-256 over the four strategy fields.
    """

    fast: int
    slow: int
    regime_sma: int
    allow_short: bool
    config_hash: str

    @classmethod
    def create(
        cls,
        *,
        fast: int,
        slow: int,
        regime_sma: int = 0,
        allow_short: bool = False,
    ) -> "CandidateConfig":
        if not isinstance(fast, int) or fast <= 0:
            raise ValueError(f"fast must be a positive integer, got {fast!r}")
        if not isinstance(slow, int) or slow <= 0:
            raise ValueError(f"slow must be a positive integer, got {slow!r}")
        if slow <= fast:
            raise ValueError(f"slow ({slow}) must be > fast ({fast})")
        if not isinstance(regime_sma, int) or regime_sma < 0:
            raise ValueError(f"regime_sma must be >= 0, got {regime_sma!r}")
        if not isinstance(allow_short, bool):
            raise ValueError(f"allow_short must be bool, got {type(allow_short).__name__}")
        core: Mapping[str, Any] = {
            "schema_version": CANDIDATE_CONFIG_SCHEMA_VERSION,
            "fast": fast,
            "slow": slow,
            "regime_sma": regime_sma,
            "allow_short": allow_short,
        }
        return cls(
            fast=fast,
            slow=slow,
            regime_sma=regime_sma,
            allow_short=allow_short,
            config_hash=canonical_hash(core),
        )

    @classmethod
    def default(cls) -> "CandidateConfig":
        """Default config matching run_r0_runtime.py defaults."""
        return cls.create(fast=20, slow=100, regime_sma=0, allow_short=False)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not isinstance(self.fast, int) or self.fast <= 0:
            errors.append("candidate_config_fast_invalid")
        if not isinstance(self.slow, int) or self.slow <= 0:
            errors.append("candidate_config_slow_invalid")
        if isinstance(self.fast, int) and isinstance(self.slow, int) and self.slow <= self.fast:
            errors.append("candidate_config_slow_not_greater_than_fast")
        if not isinstance(self.regime_sma, int) or self.regime_sma < 0:
            errors.append("candidate_config_regime_sma_invalid")
        if not isinstance(self.allow_short, bool):
            errors.append("candidate_config_allow_short_invalid")
        core: Mapping[str, Any] = {
            "schema_version": CANDIDATE_CONFIG_SCHEMA_VERSION,
            "fast": self.fast,
            "slow": self.slow,
            "regime_sma": self.regime_sma,
            "allow_short": self.allow_short,
        }
        if self.config_hash != canonical_hash(core):
            errors.append("candidate_config_hash_invalid")
        return tuple(errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CANDIDATE_CONFIG_SCHEMA_VERSION,
            "fast": self.fast,
            "slow": self.slow,
            "regime_sma": self.regime_sma,
            "allow_short": self.allow_short,
            "config_hash": self.config_hash,
        }

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "CandidateConfig":
        cfg = CandidateConfig(
            fast=int(d["fast"]),
            slow=int(d["slow"]),
            regime_sma=int(d.get("regime_sma", 0)),
            allow_short=bool(d.get("allow_short", False)),
            config_hash=str(d.get("config_hash", "")),
        )
        errors = cfg.validate()
        if errors:
            raise ValueError(f"candidate_config_invalid:{','.join(errors)}")
        return cfg
