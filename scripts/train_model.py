"""
Model Training & Serialization Script for SentinelTrace Layer-2 BehavioralClassifier.

Loads labeled session traces from data/benchmarks/ (supplemented with synthetic
seeds if needed), performs a visitor-grouped train/validation split to prevent
leakage, fits the BehavioralClassifier with temperature scaling T, and persists
the serialized artifact to models/behavioral_v1.2.joblib.
"""

import argparse
import json
import pickle
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.core.features import extract_all_features
from packages.detection.ml_classifier import BehavioralClassifier
from packages.generators.seed_data import generate_synthetic_session
from packages.version import MODEL_VERSION


def _save_artifact(artifact: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import joblib
        joblib.dump(artifact, output_path)
    except ImportError:
        with open(output_path, "wb") as fp:
            pickle.dump(artifact, fp)


def load_labeled_dataset(benchmark_dir: Path = None) -> List[Tuple[List[float], str, str]]:
    """
    Loads training samples from disjoint procedural seeds (NOT data/benchmarks/,
    which is reserved as a strict zero-leakage holdout test set).
    """
    clf = BehavioralClassifier()
    samples: List[Tuple[List[float], str, str]] = []

    rng = random.Random(202601)
    subtypes = {
        "HUMAN": ["organic_mouse", "keyboard_focused", "prompt_typing"],
        "TRADITIONAL_AUTOMATION": ["deterministic", "randomized", "evasive", "headless_dom"],
        "AGENTIC_AI": ["trajectory_agent", "dom_agent", "hybrid_agent"],
    }
    for cls, st_list in subtypes.items():
        for task in ["shopping", "travel", "forum"]:
            for st in st_list:
                for i in range(12):
                    s = generate_synthetic_session(
                        cls, task, index=i, subtype=st, seed=rng.randint(1000000, 9999999)
                    )
                    feats = extract_all_features(s)
                    vec = clf.extract_feature_vector(feats)
                    visitor_group = f"train_synth_{cls}_{st}_{i}"
                    samples.append((vec, cls, visitor_group))

    return samples


def visitor_grouped_split(
    samples: List[Tuple[List[float], str, str]],
    val_ratio: float = 0.25,
    seed: int = 42,
) -> Tuple[List[List[float]], List[str], List[List[float]], List[str]]:
    """Splits samples by visitor_group so no visitor spans train and validation."""
    rng = random.Random(seed)
    groups: Dict[str, List[Tuple[List[float], str]]] = {}
    for vec, label, group in samples:
        groups.setdefault(group, []).append((vec, label))

    group_keys = sorted(groups.keys())
    rng.shuffle(group_keys)
    split_idx = max(1, int(len(group_keys) * (1.0 - val_ratio)))
    train_keys = set(group_keys[:split_idx])

    X_train, y_train, X_val, y_val = [], [], [], []
    for key in group_keys:
        target_X, target_y = (X_train, y_train) if key in train_keys else (X_val, y_val)
        for vec, label in groups[key]:
            target_X.append(vec)
            target_y.append(label)

    return X_train, y_train, X_val, y_val


def load_external_empirical_dataset(clf: BehavioralClassifier) -> List[Tuple[List[float], str, str]]:
    """Loads real empirical datasets from data/external/ (Balabit, HF Keystrokes, HF Lumos)."""
    ext_samples: List[Tuple[List[float], str, str]] = []
    try:
        from scripts.download_and_train import (
            download_balabit_human_data,
            download_huggingface_keystrokes,
            download_huggingface_web_agent_traces,
        )
        for loader in (
            download_balabit_human_data,
            download_huggingface_keystrokes,
            download_huggingface_web_agent_traces,
        ):
            for s in loader():
                try:
                    lbl = s.get("ground_truth_label")
                    if lbl not in ("HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"):
                        continue
                    feats = extract_all_features(s)
                    vec = clf.extract_feature_vector(feats)
                    group = str(s.get("visitor_id") or s.get("session_id"))
                    ext_samples.append((vec, lbl, group))
                except Exception:
                    continue
    except Exception:
        pass
    return ext_samples


def train_and_persist(output_path: Path) -> Dict[str, Any]:
    probe = BehavioralClassifier()
    samples = load_labeled_dataset(BASE_DIR / "data" / "benchmarks")
    ext_samples = load_external_empirical_dataset(probe)
    if ext_samples:
        print(f"Merged {len(ext_samples)} real empirical samples from data/external/.")
        samples.extend(ext_samples)
    X_train, y_train, X_val, y_val = visitor_grouped_split(samples)

    clf = BehavioralClassifier()
    metrics = clf.train(X_train, y_train)
    if X_val and y_val:
        clf.calibrate(X_val, y_val)

    artifact = {
        "classifier": clf,
        "model_version": MODEL_VERSION,
        "temperature": clf.temperature,
        "metrics": metrics,
        "calibration_metrics": clf.calibration_metrics,
        "train_size": len(X_train),
        "val_size": len(X_val),
    }
    _save_artifact(artifact, output_path)
    print(f"Trained BehavioralClassifier ({MODEL_VERSION}) saved to {output_path}")
    print(
        f"Train={len(X_train)}, Val={len(X_val)}, "
        f"Accuracy={metrics.get('accuracy')}, F1={metrics.get('f1')}, T={clf.temperature:.3f}"
    )
    return artifact


def main():
    parser = argparse.ArgumentParser(description="Train and serialize SentinelTrace Layer-2 classifier.")
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE_DIR / "models" / "behavioral_v1.2.joblib",
        help="Destination path for serialized model artifact.",
    )
    args = parser.parse_args()
    train_and_persist(args.output)


if __name__ == "__main__":
    main()
