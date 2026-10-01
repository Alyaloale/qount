"""Market generators (design §7).

- ``specs`` / ``params``: regimes, per-asset mapping, world parameters and priors.
- ``structural``: four-layer structural family for training (§7.1).
- ``plausibility``: economic rejection sampling (§7.2).
- ``stylized``: stylized-fact gates (§7.3); ``calibration`` combines §7.2 and §7.3.
- ``bootstrap``: regime-conditional block bootstrap acceptance family (§7.4).
- ``analytic``: AR(1)/HMM subfamily with exact Kalman/HMM Bayes benchmark and regret (§8.1).
"""
