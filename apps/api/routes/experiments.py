"""
Experiment Lab API — runs REAL ablation experiments on labeled sessions.

All metrics are computed from actual training and evaluation — never hardcoded.
If insufficient data exists, returns a clear error with the minimum required samples.

Six feature-set experiments:
  A. browser_only       — webdriver flag only
  B. mouse_only         — mouse kinematics, no browser/keyboard
  C. keyboard_only      — keystroke timing, no mouse/browser
  D. scroll_click_only  — scroll/click patterns
  E. behavioral_all     — all behavioral features, no webdriver flag
  F. combined           — all features including webdriver flag
"""

import time
import uuid
import hashlib
from typing import Dict, Any, List, Tuple, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from packages.database.db import get_db
from packages.database.models import SessionRecord, FeatureRecord
from packages.detection.ml_classifier import BehavioralClassifier, CLASS_LABELS
from apps.api.config import settings

router = APIRouter(prefix="/api/v1/experiments", tags=["Experiments"])

# ─── Feature Set Definitions ─────────────────────────────────────────────────
FEATURE_SETS = {
    "browser_only": [
        "webdriver_flag",
    ],
    "mouse_only": [
        "straightness_ratio", "mean_velocity", "velocity_std",
        "acceleration_std", "jerk_mean", "micro_corrections",
        "direction_changes", "pause_time_ratio",
    ],
    "keyboard_only": [
        "key_latency_cv", "key_uniformity_score",
        "key_mean_latency", "key_latency_std",
    ],
    "scroll_click_only": [
        "scroll_velocity_std", "scroll_discrete_jump_ratio",
        "interaction_density", "first_action_delay_ms",
    ],
    "behavioral_all": [
        "straightness_ratio", "mean_velocity", "velocity_std",
        "acceleration_std", "jerk_mean", "micro_corrections",
        "direction_changes", "pause_time_ratio",
        "key_latency_cv", "key_uniformity_score",
        "key_mean_latency", "key_latency_std",
        "scroll_velocity_std", "scroll_discrete_jump_ratio",
        "interaction_density", "first_action_delay_ms",
    ],
    "combined": [
        "straightness_ratio", "mean_velocity", "velocity_std",
        "acceleration_std", "jerk_mean", "micro_corrections",
        "direction_changes", "pause_time_ratio",
        "key_latency_cv", "key_uniformity_score",
        "key_mean_latency", "key_latency_std",
        "scroll_velocity_std", "scroll_discrete_jump_ratio",
        "interaction_density", "first_action_delay_ms",
        "webdriver_flag",
    ],
}

EXPERIMENT_DESCRIPTIONS = {
    "browser_only":     "Exp A: Browser signals only (webdriver flag). Tests single-signal baseline.",
    "mouse_only":       "Exp B: Mouse kinematics only. Straightness, velocity, micro-corrections.",
    "keyboard_only":    "Exp C: Keystroke timing only. Interval CV, hold duration.",
    "scroll_click_only":"Exp D: Scroll/click patterns only. Jump ratio, density.",
    "behavioral_all":   "Exp E: All behavioral features, no browser fingerprint.",
    "combined":         "Exp F: Combined — all behavioral + browser fingerprint.",
}


def _feature_record_to_dict(feat: FeatureRecord) -> Dict[str, float]:
    """Map ORM FeatureRecord to a flat feature dict."""
    return {
        "straightness_ratio":       feat.mouse_straightness_ratio or 1.0,
        "mean_velocity":            feat.mouse_mean_velocity or 0.0,
        "velocity_std":             feat.mouse_velocity_std or 0.0,
        "acceleration_std":         feat.mouse_acceleration_std or 0.0,
        "jerk_mean":                feat.mouse_jerk_mean or 0.0,
        "micro_corrections":        feat.mouse_micro_corrections or 0,
        "direction_changes":        feat.mouse_direction_changes or 0,
        "pause_time_ratio":         feat.mouse_pause_ratio or 0.0,
        "key_latency_cv":           feat.key_latency_cv or 0.0,
        "key_uniformity_score":     1.0 - (feat.key_latency_cv or 0.0),
        "key_mean_latency":         feat.key_mean_latency or 0.0,
        "key_latency_std":          feat.key_latency_std or 0.0,
        "scroll_velocity_std":      feat.scroll_velocity_std or 0.0,
        "scroll_discrete_jump_ratio": feat.scroll_discrete_jump_ratio or 0.0,
        "interaction_density":      feat.interaction_density or 0.0,
        "first_action_delay_ms":    feat.interaction_first_action_delay or 0.0,
        "webdriver_flag":           1.0 if feat.webdriver_flag else 0.0,
    }


def _group_split(
    sessions: List[SessionRecord],
    feat_map: Dict[str, Dict],
    test_fraction: float = 0.25,
    seed: int = 42,
) -> Tuple[List, List, List, List]:
    """
    Visitor-grouped train/test split.
    All sessions from the same visitor_id stay in the same fold,
    preventing leakage of correlated sessions across train/test boundary.
    """
    import random
    rng = random.Random(seed)

    # Group by visitor_id
    visitor_sessions: Dict[str, List] = {}
    for s in sessions:
        vid = s.visitor_id or s.session_id
        visitor_sessions.setdefault(vid, []).append(s)

    visitor_ids = list(visitor_sessions.keys())
    rng.shuffle(visitor_ids)
    n_test = max(1, int(len(visitor_ids) * test_fraction))
    test_visitors  = set(visitor_ids[:n_test])
    train_visitors = set(visitor_ids[n_test:])

    X_train, y_train, X_test, y_test = [], [], [], []
    for vid, sess_list in visitor_sessions.items():
        for s in sess_list:
            if s.session_id not in feat_map:
                continue
            fvec = feat_map[s.session_id]
            label = s.ground_truth_label
            if vid in train_visitors:
                X_train.append(fvec)
                y_train.append(label)
            else:
                X_test.append(fvec)
                y_test.append(label)

    return X_train, y_train, X_test, y_test


def _compute_metrics(y_true: List[str], y_pred: List[str]) -> Dict[str, Any]:
    """Pure-Python metric computation (no sklearn required)."""
    labels = CLASS_LABELS
    # Confusion matrix
    cm = {l: {l2: 0 for l2 in labels} for l in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm:
            cm[t][p] = cm[t].get(p, 0) + 1

    cm_list = [[cm[t].get(p, 0) for p in labels] for t in labels]

    # Per-class P/R/F1
    per_class = {}
    for lbl in labels:
        tp = cm[lbl][lbl]
        fp = sum(cm[other][lbl] for other in labels if other != lbl)
        fn = sum(cm[lbl][other] for other in labels if other != lbl)
        prec   = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1     = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0.0
        per_class[lbl] = {"precision": round(prec, 4), "recall": round(recall, 4), "f1": round(f1, 4)}

    n = len(y_true)
    accuracy       = sum(1 for t, p in zip(y_true, y_pred) if t == p) / n if n > 0 else 0.0
    prec_macro     = sum(v["precision"] for v in per_class.values()) / len(labels)
    recall_macro   = sum(v["recall"]    for v in per_class.values()) / len(labels)
    f1_macro       = sum(v["f1"]        for v in per_class.values()) / len(labels)

    return {
        "accuracy":        round(accuracy, 4),
        "precision_macro": round(prec_macro, 4),
        "recall_macro":    round(recall_macro, 4),
        "f1_macro":        round(f1_macro, 4),
        "per_class":       per_class,
        "confusion_matrix": cm_list,
    }


def _run_single_experiment(
    exp_id: str,
    feature_set: str,
    X_train_full: List[Dict],
    y_train: List[str],
    X_test_full: List[Dict],
    y_test: List[str],
) -> Dict[str, Any]:
    """
    Trains and evaluates a single experiment on the given feature subset.
    Returns fully computed (not hardcoded) metrics.
    """
    feat_keys = FEATURE_SETS.get(feature_set, list(FEATURE_SETS["combined"]))

    # Project to feature subset
    def project(fdict):
        return [fdict.get(k, 0.0) for k in feat_keys]

    X_tr = [project(d) for d in X_train_full]
    X_te = [project(d) for d in X_test_full]

    # Train classifier
    clf = BehavioralClassifier()
    clf.train_on_vectors(X_tr, y_train, feature_names=feat_keys)

    # Predict on test set
    y_pred = [clf.predict_vector(x)[0] for x in X_te]

    metrics = _compute_metrics(y_test, y_pred)

    # Feature importance (if available from the model)
    feat_importance = clf.get_feature_importance(feat_keys)

    return {
        "id":               exp_id,
        "name":             EXPERIMENT_DESCRIPTIONS.get(feature_set, feature_set),
        "feature_set":      feature_set,
        "features_used":    feat_keys,
        "train_size":       len(X_tr),
        "test_size":        len(X_te),
        "accuracy":         metrics["accuracy"],
        "precision_macro":  metrics["precision_macro"],
        "recall_macro":     metrics["recall_macro"],
        "f1_macro":         metrics["f1_macro"],
        "per_class_metrics": metrics["per_class"],
        "confusion_matrix": metrics["confusion_matrix"],
        "feature_importance": feat_importance,
    }


@router.get("/run")
@router.post("/run")
def run_experiments(
    random_seed: int = 42,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Runs six ablation experiments on the labeled session dataset.

    All metrics are COMPUTED from real training/evaluation.
    Returns HTTP 422 if insufficient labeled data is available.

    Uses visitor-grouped train/test split to prevent session leakage.
    """
    min_per_class = settings.MIN_EXPERIMENT_SAMPLES_PER_CLASS

    # ── Load labeled sessions and features ────────────────────────────────────
    sessions = (
        db.query(SessionRecord)
        .filter(SessionRecord.ground_truth_label.isnot(None))
        .all()
    )

    # Count per class
    class_counts: Dict[str, int] = {}
    for s in sessions:
        lbl = s.ground_truth_label
        class_counts[lbl] = class_counts.get(lbl, 0) + 1

    # Minimum data check
    insufficient = [
        lbl for lbl in CLASS_LABELS
        if class_counts.get(lbl, 0) < min_per_class
    ]
    if insufficient:
        raise HTTPException(
            status_code=422,
            detail={
                "error":           "insufficient_labeled_data",
                "message":         (
                    f"Experiments require at least {min_per_class} labeled sessions per class. "
                    f"Classes with insufficient data: {insufficient}. "
                    f"Run POST /api/v1/seed/demo first to generate synthetic demo data."
                ),
                "class_counts":    class_counts,
                "required_per_class": min_per_class,
            }
        )

    # Load feature records
    session_ids = [s.session_id for s in sessions]
    feat_records = (
        db.query(FeatureRecord)
        .filter(FeatureRecord.session_id.in_(session_ids))
        .all()
    )
    feat_map = {f.session_id: _feature_record_to_dict(f) for f in feat_records}

    # Remove sessions with no feature record
    sessions = [s for s in sessions if s.session_id in feat_map]

    total_n = len(sessions)

    # ── Visitor-grouped split ──────────────────────────────────────────────────
    X_train_full, y_train, X_test_full, y_test = _group_split(
        sessions, feat_map, test_fraction=0.25, seed=random_seed
    )

    if len(X_test_full) < 3:
        raise HTTPException(
            status_code=422,
            detail={
                "error":   "test_set_too_small",
                "message": "Not enough sessions for a meaningful test split. Add more labeled sessions.",
                "total_sessions": total_n,
            }
        )

    # ── Run each experiment ────────────────────────────────────────────────────
    experiment_results = []
    for exp_key in ["browser_only", "mouse_only", "keyboard_only",
                    "scroll_click_only", "behavioral_all", "combined"]:
        result = _run_single_experiment(
            exp_id=f"exp_{exp_key}",
            feature_set=exp_key,
            X_train_full=X_train_full,
            y_train=y_train,
            X_test_full=X_test_full,
            y_test=y_test,
        )
        experiment_results.append(result)

    # ── Best experiment feature importance ──────────────────────────────────────
    best_exp = max(experiment_results, key=lambda e: e["f1_macro"])
    combined_exp = next(
        (e for e in experiment_results if e["feature_set"] in ("combined", "behavioral_all") and e.get("feature_importance")),
        best_exp
    )
    feat_importances_to_return = combined_exp.get("feature_importance") or best_exp.get("feature_importance", [])

    # ── Dataset fingerprint (for reproducibility) ──────────────────────────────
    sid_hash = hashlib.md5("".join(sorted(session_ids)).encode()).hexdigest()[:8]

    # ── Persist to ExperimentRecord DB table ──────────────────────────────────
    from packages.database.models import ExperimentRecord
    for exp in experiment_results:
        exp_id = f"{exp['id']}_{sid_hash}_{int(time.time())}"
        rec = ExperimentRecord(
            id=exp_id,
            name=exp["name"],
            description=exp.get("description", ""),
            dataset_version=sid_hash,
            random_seed=random_seed,
            training_config={"feature_set": exp["feature_set"]},
            feature_set=exp["feature_set"],
            model_name="RandomForestClassifier",
            model_version=settings.MODEL_VERSION,
            accuracy=exp["accuracy"],
            precision_macro=exp["precision_macro"],
            recall_macro=exp["recall_macro"],
            f1_macro=exp["f1_macro"],
            per_class_metrics=exp.get("per_class_metrics", {}),
            confusion_matrix=exp.get("confusion_matrix", []),
            feature_importance=exp.get("feature_importance", []),
            sample_size=total_n,
            train_size=len(X_train_full),
            test_size=len(X_test_full),
        )
        db.add(rec)
    try:
        db.commit()
    except Exception:
        db.rollback()

    return {
        "status":               "success",
        "data_provenance":      "real_computed",   # NEVER 'hardcoded'
        "total_sessions":       total_n,
        "train_size":           len(X_train_full),
        "test_size":            len(X_test_full),
        "class_distribution":   class_counts,
        "random_seed":          random_seed,
        "dataset_fingerprint":  sid_hash,
        "split_strategy":       "visitor_grouped",
        "experiments":          experiment_results,
        "best_experiment":      best_exp["id"],
        "feature_importance":   feat_importances_to_return,
        "confusion_matrix":     best_exp["confusion_matrix"],
    }


@router.get("/latest")
def get_latest_experiments(db: Session = Depends(get_db)):
    """Returns latest experiment results or runs benchmark if none stored."""
    from packages.database.models import ExperimentRecord
    records = db.query(ExperimentRecord).order_by(ExperimentRecord.created_at.desc()).limit(6).all()
    if records and len(records) >= 6:
        exp_list = []
        best_rec = max(records, key=lambda r: r.f1_macro or 0)
        combined_rec = next((r for r in records if r.feature_set in ("combined", "behavioral_all") and r.feature_importance), best_rec)
        for r in reversed(records):
            exp_list.append({
                "id": r.id,
                "name": r.name,
                "feature_set": r.feature_set,
                "accuracy": r.accuracy,
                "precision_macro": r.precision_macro,
                "recall_macro": r.recall_macro,
                "f1_macro": r.f1_macro,
                "per_class_metrics": r.per_class_metrics,
                "confusion_matrix": r.confusion_matrix,
                "feature_importance": r.feature_importance,
            })
        return {
            "status": "success",
            "data_provenance": "real_computed",
            "total_sessions": best_rec.sample_size or 0,
            "experiments": exp_list,
            "best_experiment": best_rec.id,
            "feature_importance": combined_rec.feature_importance or best_rec.feature_importance or [],
            "confusion_matrix": best_rec.confusion_matrix or [],
        }
    return run_experiments(random_seed=42, db=db)


@router.get("/history")
def get_experiment_history(db: Session = Depends(get_db)):
    """
    Returns history of all benchmark experiments persisted in the database.
    """
    from packages.database.models import ExperimentRecord
    records = db.query(ExperimentRecord).order_by(ExperimentRecord.created_at.desc()).limit(50).all()
    history = []
    for r in records:
        history.append({
            "id": r.id,
            "name": r.name,
            "feature_set": r.feature_set,
            "accuracy": r.accuracy,
            "f1_macro": r.f1_macro,
            "precision_macro": r.precision_macro,
            "recall_macro": r.recall_macro,
            "sample_size": r.sample_size,
            "dataset_version": r.dataset_version,
            "model_version": r.model_version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"status": "success", "count": len(history), "history": history}

