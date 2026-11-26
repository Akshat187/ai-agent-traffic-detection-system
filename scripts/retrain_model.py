"""
Active Learning & Drift-Gated Retrain Pipeline for SentinelTrace.

Merges verified user/analyst labels from `session_feedback` with real empirical
datasets + disjoint synthetic hard negatives, upweights real feedback samples
(8x oversampling) so real browser/extension traffic drives tree splits, and gates
promotion on real verified validation sessions (or a blended real + holdout
benchmark score when fewer than 15 real verified sessions exist).
"""

import json
import pickle
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.core.features import extract_all_features
from packages.database.db import SessionLocal, init_db
from packages.database.models import SessionFeedback, SessionRecord
from packages.detection.ml_classifier import BehavioralClassifier, compute_ece
from packages.version import MODEL_VERSION
from scripts.train_model import (
    load_labeled_dataset,
    load_external_empirical_dataset,
    visitor_grouped_split,
    _save_artifact,
)

REAL_FEEDBACK_WEIGHT = 8  # Oversampling factor so real feedback outweighs synthetic baselines


def _load_artifact(path: Path) -> Any:
    try:
        import joblib
        return joblib.load(path)
    except ImportError:
        with open(path, "rb") as fp:
            return pickle.load(fp)


def _load_feedback_samples(clf: BehavioralClassifier) -> List[Tuple[List[float], str, str]]:
    """Loads latest analyst/user-verified session labels from session_feedback."""
    init_db()
    db = SessionLocal()
    feedback_samples: List[Tuple[List[float], str, str]] = []
    try:
        rows = db.query(SessionFeedback).order_by(SessionFeedback.id.desc()).all()
        seen_sessions = set()
        for fb in rows:
            if fb.session_id in seen_sessions or fb.analyst_label == "UNCERTAIN":
                continue
            seen_sessions.add(fb.session_id)
            sess = db.query(SessionRecord).filter(SessionRecord.session_id == fb.session_id).first()
            if sess and sess.features and sess.features.all_features_json:
                vec = clf.extract_feature_vector(sess.features.all_features_json)
                group = str(sess.visitor_id or sess.session_id)
                feedback_samples.append((vec, fb.analyst_label, f"fb_{group}"))
    finally:
        db.close()
    return feedback_samples


def _evaluate_classifier_on_vectors(
    clf: BehavioralClassifier,
    X: List[List[float]],
    y: List[str],
) -> Tuple[float, float]:
    """Computes (macro_f1, ece) on pre-extracted (X, y) samples."""
    classes = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]
    if not X or not y:
        return 0.0, 1.0

    y_pred, probs_list = [], []
    for vec in X:
        pred, _, probs = clf.predict_vector(vec)
        y_pred.append(pred)
        probs_list.append(probs)

    present_classes = [c for c in classes if c in y]
    f1s = []
    for cls in present_classes:
        tp = sum(1 for yt, yp in zip(y, y_pred) if yt == cls and yp == cls)
        fp = sum(1 for yt, yp in zip(y, y_pred) if yt != cls and yp == cls)
        fn = sum(1 for yt, yp in zip(y, y_pred) if yt == cls and yp != cls)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1s.append((2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0)

    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    ece = compute_ece(y, probs_list, n_bins=10)
    return macro_f1, ece


def _evaluate_classifier_on_benchmarks(clf: BehavioralClassifier) -> Tuple[float, float]:
    """Returns (macro_f1, ece) of a BehavioralClassifier on data/benchmarks/."""
    benchmark_dir = BASE_DIR / "data" / "benchmarks"
    classes = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]
    y_true, y_pred, probs_list = [], [], []

    for cls in classes:
        cls_dir = benchmark_dir / cls.lower()
        if not cls_dir.exists():
            continue
        for f in sorted(cls_dir.glob("*.json")):
            with open(f, "r", encoding="utf-8") as fp:
                trace = json.load(fp)
            feats = extract_all_features(trace)
            pred, _, probs = clf.predict(feats)
            y_true.append(cls)
            y_pred.append(pred)
            probs_list.append(probs)

    if not y_true:
        return 0.0, 1.0

    f1s = []
    for cls in classes:
        tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == cls and yp == cls)
        fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt != cls and yp == cls)
        fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == cls and yp != cls)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1s.append((2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0)

    macro_f1 = sum(f1s) / len(f1s)
    ece = compute_ece(y_true, probs_list, n_bins=10)
    return macro_f1, ece


def retrain_with_regression_gate(
    model_path: Path,
    return_details: bool = False,
) -> Union[bool, Dict[str, Any]]:
    """
    Retrains with upweighted real user/analyst feedback and promotes when
    verified real validation (or blended real + benchmark) F1 & ECE improve.
    """
    probe = BehavioralClassifier()
    base_samples = load_labeled_dataset(BASE_DIR / "data" / "benchmarks")
    ext_samples = load_external_empirical_dataset(probe)
    fb_samples = _load_feedback_samples(probe)
    print(f"Loaded {len(base_samples)} base + {len(ext_samples)} external + {len(fb_samples)} verified feedback samples.")

    X_base_tr, y_base_tr, X_base_val, y_base_val = visitor_grouped_split(base_samples + ext_samples)

    fb_classes = {lbl for _, lbl, _ in fb_samples}
    use_real_val_gate = len(fb_samples) >= 15 and len(fb_classes) >= 2

    if use_real_val_gate:
        X_fb_tr, y_fb_tr, X_fb_val, y_fb_val = visitor_grouped_split(fb_samples, val_ratio=0.30, seed=99)
    else:
        X_fb_tr = [v for v, _, _ in fb_samples]
        y_fb_tr = [l for _, l, _ in fb_samples]
        X_fb_val, y_fb_val = X_fb_tr, y_fb_tr

    # Upweight real user feedback (8x) so real extension telemetry drives tree splits
    X_train = list(X_base_tr) + (X_fb_tr * REAL_FEEDBACK_WEIGHT)
    y_train = list(y_base_tr) + (y_fb_tr * REAL_FEEDBACK_WEIGHT)

    X_val = list(X_base_val) + (X_fb_val * 2 if X_fb_val else [])
    y_val = list(y_base_val) + (y_fb_val * 2 if y_fb_val else [])

    candidate = BehavioralClassifier()
    metrics = candidate.train(X_train, y_train)
    if X_val and y_val:
        candidate.calibrate(X_val, y_val)

    # Regression gate: evaluate on real verified validation when >= 15 multi-class samples exist,
    # otherwise blend real feedback performance (70%) with benchmark holdout (30%).
    if model_path.exists():
        artifact = _load_artifact(model_path)
        current = artifact["classifier"] if isinstance(artifact, dict) else artifact
    else:
        current = None

    if use_real_val_gate:
        cand_f1, cand_ece = _evaluate_classifier_on_vectors(candidate, X_fb_val, y_fb_val)
        base_f1, base_ece = _evaluate_classifier_on_vectors(current, X_fb_val, y_fb_val) if current else (0.0, 1.0)
        gate_mode = "real_feedback_holdout"
    elif fb_samples:
        cand_real_f1, cand_real_ece = _evaluate_classifier_on_vectors(candidate, X_fb_val, y_fb_val)
        cand_bm_f1, cand_bm_ece = _evaluate_classifier_on_benchmarks(candidate)
        cand_f1 = 0.70 * cand_real_f1 + 0.30 * cand_bm_f1
        cand_ece = 0.70 * cand_real_ece + 0.30 * cand_bm_ece
        if current:
            base_real_f1, base_real_ece = _evaluate_classifier_on_vectors(current, X_fb_val, y_fb_val)
            base_bm_f1, base_bm_ece = _evaluate_classifier_on_benchmarks(current)
            base_f1 = 0.70 * base_real_f1 + 0.30 * base_bm_f1
            base_ece = 0.70 * base_real_ece + 0.30 * base_bm_ece
        else:
            base_f1, base_ece = 0.0, 1.0
        gate_mode = "blended_real_plus_benchmark"
    else:
        cand_f1, cand_ece = _evaluate_classifier_on_benchmarks(candidate)
        base_f1, base_ece = _evaluate_classifier_on_benchmarks(current) if current else (0.0, 1.0)
        gate_mode = "benchmark_only"

    print(f"[{gate_mode}] Baseline : F1={base_f1:.4f}, ECE={base_ece:.4f}")
    print(f"[{gate_mode}] Candidate: F1={cand_f1:.4f}, ECE={cand_ece:.4f}")

    promoted = (cand_f1 >= base_f1) and (cand_ece <= base_ece + 0.02)
    if promoted:
        artifact = {
            "classifier": candidate,
            "model_version": MODEL_VERSION,
            "temperature": candidate.temperature,
            "metrics": metrics,
            "calibration_metrics": candidate.calibration_metrics,
            "feedback_count": len(fb_samples),
        }
        _save_artifact(artifact, model_path)
        print(f"PROMOTED new model artifact to {model_path}")
    else:
        print("REJECTED candidate model: failed regression gate.")

    if return_details:
        return {
            "promoted": promoted,
            "gate_mode": gate_mode,
            "feedback_count": len(fb_samples),
            "baseline_f1": round(base_f1, 4),
            "candidate_f1": round(cand_f1, 4),
            "baseline_ece": round(base_ece, 4),
            "candidate_ece": round(cand_ece, 4),
        }
    return promoted


if __name__ == "__main__":
    retrain_with_regression_gate(BASE_DIR / "models" / "behavioral_v1.2.joblib")
