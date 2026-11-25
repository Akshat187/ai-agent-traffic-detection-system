"""
Active Learning & Drift-Gated Retrain Pipeline for SentinelTrace.

Merges verified analyst label overrides from the `session_feedback` table into
the training dataset, evaluates the candidate model against the current
production model on the persistent benchmark suite, and only promotes the new
artifact to models/behavioral_v1.2.joblib if Macro-F1 >= baseline and
ECE <= baseline.
"""

import json
import pickle
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from packages.core.features import extract_all_features
from packages.database.db import SessionLocal, init_db
from packages.database.models import SessionFeedback, SessionRecord
from packages.detection.ml_classifier import BehavioralClassifier, compute_ece
from packages.version import MODEL_VERSION
from scripts.train_model import load_labeled_dataset, visitor_grouped_split, _save_artifact


def _load_artifact(path: Path) -> Any:
    try:
        import joblib
        return joblib.load(path)
    except ImportError:
        with open(path, "rb") as fp:
            return pickle.load(fp)


def _load_feedback_samples(clf: BehavioralClassifier) -> List[Tuple[List[float], str, str]]:
    """Loads analyst-verified session overrides from session_feedback."""
    init_db()
    db = SessionLocal()
    feedback_samples: List[Tuple[List[float], str, str]] = []
    try:
        rows = db.query(SessionFeedback).order_by(SessionFeedback.created_at.desc()).all()
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


def retrain_with_regression_gate(model_path: Path) -> bool:
    """Retrains with analyst feedback and promotes only if Macro-F1 & ECE do not regress."""
    probe = BehavioralClassifier()
    base_samples = load_labeled_dataset(BASE_DIR / "data" / "benchmarks")
    fb_samples = _load_feedback_samples(probe)
    print(f"Loaded {len(base_samples)} base samples + {len(fb_samples)} analyst feedback overrides.")

    all_samples = base_samples + fb_samples
    X_train, y_train, X_val, y_val = visitor_grouped_split(all_samples)

    candidate = BehavioralClassifier()
    metrics = candidate.train(X_train, y_train)
    if X_val and y_val:
        candidate.calibrate(X_val, y_val)

    cand_f1, cand_ece = _evaluate_classifier_on_benchmarks(candidate)

    if model_path.exists():
        artifact = _load_artifact(model_path)
        current = artifact["classifier"] if isinstance(artifact, dict) else artifact
        base_f1, base_ece = _evaluate_classifier_on_benchmarks(current)
    else:
        base_f1, base_ece = 0.0, 1.0

    print(f"Baseline : Macro-F1={base_f1:.4f}, ECE={base_ece:.4f}")
    print(f"Candidate: Macro-F1={cand_f1:.4f}, ECE={cand_ece:.4f}")

    if cand_f1 >= base_f1 and cand_ece <= base_ece + 1e-6:
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
        return True
    else:
        print("REJECTED candidate model: failed regression gate (Macro-F1 or ECE regressed).")
        return False


if __name__ == "__main__":
    retrain_with_regression_gate(BASE_DIR / "models" / "behavioral_v1.2.joblib")
