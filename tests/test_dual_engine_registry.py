import copy
import unittest
import json
from pathlib import Path
import tempfile
from qount.research.dual_engine_registry import robust_metrics, select_leaders, build_registry, CELLS, DATES
from qount.research.dual_engine_optimization import write_json, file_hash


def version(name, sharpes, cagr=.15, draw=-.2):
    cells = {k: {"first": DATES["g20"][0], "last": DATES["g20"][1], "cash_excess_sharpe": s,
                 "cagr": cagr, "max_drawdown": draw, "annual_turnover": 3.}
             for k, s in zip(sorted(CELLS["g20"]), sharpes, strict=True)}
    return {"version_id": name, "line": "g20", "selection_eligible": True, "robust_metrics": robust_metrics(cells, "g20"), "cells": cells}


def study_fixture(parent, contract_name="contract.json"):
    root = parent / "results"
    root.mkdir()
    if contract_name:
        write_json(root / contract_name, {"study_id": "fixture", "research_only": True, "orders_authorized": False})
    row = version("a", [.9] * 4)
    write_json(root / "results.json", {"research_only": True, "orders_authorized": False,
        "study_id": "fixture", "candidate_trials": 1, "curve_exposures": [{"curve": k} for k in sorted(CELLS["g20"])],
        "source_sha256": {}, "summaries": {"g20": {"a": row["cells"]}}})
    write_json(root / "manifest.json", {"files": {p.name: file_hash(p) for p in root.iterdir()}})
    digest = file_hash(root / "manifest.json")
    (parent / "_verification").mkdir()
    write_json(parent / "_verification/result-verification.json", {"verified": True, "curve_count": 4, "manifest_sha256": digest})
    return root, digest


class RegistryTests(unittest.TestCase):
    def test_old_preregistration_contract_is_bound_to_real_manifest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, digest = study_fixture(base, "preregistration.json")
            result = build_registry([(root, digest)], base / "registry")
            row = result["versions"][0]
            self.assertEqual(row["strategy_contract_path"], str(root / "preregistration.json"))
            self.assertEqual(row["strategy_contract_sha256"], file_hash(root / "preregistration.json"))

    def test_missing_contract_cannot_create_dangling_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, digest = study_fixture(base, None)
            with self.assertRaisesRegex(ValueError, "manifest_bound_contract"):
                build_registry([(root, digest)], base / "registry")
            self.assertFalse((base / "registry").exists())

    def test_metadata_revision_preserves_freeze_and_cannot_reselect(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, digest = study_fixture(base)
            parent = build_registry([(root, digest)], base / "parent")
            revision = build_registry([(root, digest)], base / "revision", parent_registry_root=base / "parent")
            self.assertEqual(revision["selection_frozen_at"], parent["created_at"])
            self.assertEqual(revision["leaders"], parent["leaders"])
            with self.assertRaisesRegex(ValueError, "cannot_change_strategy_or_ranking"):
                build_registry([(root, digest)], base / "invalid", parent_registry_root=base / "parent", selection_exclusions=["fixture/g20/a"])
            self.assertFalse((base / "invalid").exists())
    def test_stress_minimum_beats_best_base_case(self):
        strong_base = version("base", [1.4, 1.2, .7, .5])
        robust = version("robust", [1., .9, .8, .8])
        self.assertEqual(select_leaders([strong_base, robust])["g20"]["leader"], "robust")

    def test_missing_cells_and_different_dates_are_ineligible(self):
        r = version("a", [1.] * 4)
        partial = copy.deepcopy(r["cells"])
        del partial[next(iter(partial))]
        self.assertIsNone(robust_metrics(partial, "g20"))
        partial = copy.deepcopy(r["cells"])
        partial[next(iter(partial))]["first"] = "2018-01-02"
        self.assertIsNone(robust_metrics(partial, "g20"))

    def test_pareto_preserves_low_drawdown_alternative(self):
        a = version("a", [.9] * 4, .2, -.3)
        b = version("b", [.8] * 4, .15, -.1)
        dominated = version("c", [.7] * 4, .1, -.4)
        result = select_leaders([dominated, b, a])["g20"]
        self.assertEqual(result["pareto"], ["a", "b"])
        self.assertEqual(result["leader"], "a")

    def test_excluded_diagnostic_never_wins(self):
        a, b = version("a", [.9] * 4), version("b", [2.] * 4)
        b["selection_eligible"] = False
        self.assertEqual(select_leaders([a, b])["g20"]["leader"], "a")

    def test_ties_stable_and_nonfinite_rejected(self):
        a, b = version("a", [.9] * 4), version("b", [.9] * 4)
        self.assertEqual(select_leaders([b, a])["g20"]["leader"], "a")
        a["cells"]["c20-d1"]["cash_excess_sharpe"] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            robust_metrics(a["cells"], "g20")

    def test_registry_requires_verification_and_preserves_immutable_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "results"
            root.mkdir()
            write_json(root / "contract.json", {"study_id": "fixture", "research_only": True, "orders_authorized": False})
            row = version("a", [.9] * 4)
            write_json(root / "results.json", {"research_only": True, "orders_authorized": False,
                "study_id": "fixture", "candidate_trials": 1, "curve_exposures": [{"curve": k} for k in CELLS["g20"]],
                "source_sha256": {}, "summaries": {"g20": {"a": row["cells"]}}})
            write_json(root / "manifest.json", {"files": {p.name: file_hash(p) for p in root.iterdir()}})
            digest = file_hash(root / "manifest.json")
            verification = parent / "_verification"
            verification.mkdir()
            write_json(verification / "result-verification.json", {"verified": False, "curve_count": 4, "manifest_sha256": digest})
            with self.assertRaisesRegex(ValueError, "independent_verification"):
                build_registry([(root, digest)], parent / "registry")
            write_json(verification / "result-verification.json", {"verified": True, "curve_count": 4, "manifest_sha256": digest})
            result = build_registry([(root, digest)], parent / "registry")
            self.assertEqual(result["candidate_trials"], 1)
            self.assertEqual(result["leaders"]["g20"]["leader"], "fixture/g20/a")
            self.assertTrue((parent / "registry/strategies/fixture/g20/a.json").exists())
            with self.assertRaisesRegex(ValueError, "snapshot_exists"):
                build_registry([(root, digest)], parent / "registry")
            (root / "unexpected.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "inventory_changed"):
                build_registry([(root, digest)], parent / "registry2")
