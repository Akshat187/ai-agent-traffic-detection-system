"""
Active-Learning Model Retrain & Hot-Reload Endpoint for SentinelTrace.
"""

import pickle
from pathlib import Path
from fastapi import APIRouter, Depends

from apps.api.dependencies import get_detection_engine
from packages.detection.engine import DecisionEngine
from packages.detection.ml_classifier import BehavioralClassifier
from packages.version import MODEL_VERSION

router = APIRouter(prefix="/api/v1/model", tags=["Model"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


@router.post("/retrain")
def trigger_model_retrain(engine: DecisionEngine = Depends(get_detection_engine)):
    """
    Runs scripts/retrain_model.py regression-gated training and hot-reloads
    the updated classifier into the running DecisionEngine without restarting Uvicorn.
    """
    from scripts.retrain_model import retrain_with_regression_gate

    model_path = BASE_DIR / "models" / "behavioral_v1.2.joblib"
    result = retrain_with_regression_gate(model_path, return_details=True)
    promoted = bool(result.get("promoted")) if isinstance(result, dict) else bool(result)

    if promoted and model_path.exists():
        try:
            try:
                import joblib
                artifact = joblib.load(model_path)
            except ImportError:
                with open(model_path, "rb") as fp:
                    artifact = pickle.load(fp)
            new_clf = artifact["classifier"] if isinstance(artifact, dict) else artifact
            if isinstance(new_clf, BehavioralClassifier):
                engine.ml = new_clf
        except Exception:
            pass

    if isinstance(result, dict):
        return {**result, "model_version": MODEL_VERSION, "hot_reloaded": promoted}
    return {"promoted": promoted, "model_version": MODEL_VERSION, "hot_reloaded": promoted}
