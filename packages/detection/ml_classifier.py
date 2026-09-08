"""
Layer 2: Supervised Behavioral Machine Learning Classifier.
Classifies sessions into HUMAN, TRADITIONAL_AUTOMATION, AGENTIC_AI, or UNCERTAIN
using extracted kinematics and agentic behavior signals.

Actor Classes:
  HUMAN                  — organic human browser interaction
  TRADITIONAL_AUTOMATION — deterministic scripted automation (Playwright, Selenium)
  AGENTIC_AI             — goal-driven adaptive browser agent
"""

import math
import random
from typing import Dict, Any, List, Tuple, Optional

# Standard feature keys used in training and inference
FEATURE_NAMES = [
    # Mouse kinematics
    "straightness_ratio",
    "mean_velocity",
    "velocity_std",
    "acceleration_std",
    "jerk_mean",
    "micro_corrections",
    "direction_changes",
    "pause_time_ratio",
    # Keyboard timing
    "key_latency_cv",
    "key_uniformity_score",
    # Scroll / interaction
    "scroll_velocity_std",
    "scroll_discrete_jump_ratio",
    "interaction_density",
    "first_action_delay_ms",
    # Agentic agency profile signals
    "planning_pause_ratio",
    "nav_segment_count",
    "action_interval_variance",
    "adaptation_score",
    "interaction_diversity_score",
    # Environment (lowest weight — supporting only)
    "webdriver_flag",
]

# Actor class labels — updated terminology
CLASS_LABELS = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]

# Legacy label mapping for backward compatibility
LEGACY_LABEL_MAP = {
    "BOT": "TRADITIONAL_AUTOMATION",
    "AI_AGENT": "AGENTIC_AI",
}


def normalize_label(label: str) -> str:
    """Maps legacy labels to current terminology."""
    return LEGACY_LABEL_MAP.get(label, label)


class SimpleDecisionTree:
    """Lightweight interpretable decision tree classifier with Gini impurity feature rankings."""

    def __init__(self, max_depth: int = 5, min_samples_split: int = 4):
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.tree = None
        self.feature_importances_ = []

    def fit(self, X: List[List[float]], y: List[str]):
        if not X or not y:
            return self
        data = [X[i] + [y[i]] for i in range(len(X))]
        n_features = len(X[0])
        self.feature_importances_ = [0.0] * n_features
        total_samples = len(data)
        self.tree = self._build_tree(data, depth=0, total_samples=total_samples)
        tot = sum(self.feature_importances_)
        if tot > 0:
            self.feature_importances_ = [v / tot for v in self.feature_importances_]
        return self

    def _entropy(self, labels: List[str]) -> float:
        if not labels:
            return 0.0
        counts = {}
        for l in labels:
            counts[l] = counts.get(l, 0) + 1
        ent = 0.0
        n = len(labels)
        for c in counts.values():
            p = c / n
            ent -= p * math.log2(p)
        return ent

    def _split(self, data: List[List[Any]], feature_idx: int, threshold: float):
        left, right = [], []
        for row in data:
            if row[feature_idx] <= threshold:
                left.append(row)
            else:
                right.append(row)
        return left, right

    def _best_split(self, data: List[List[Any]]):
        labels = [row[-1] for row in data]
        base_entropy = self._entropy(labels)
        best_gain = 0.0
        best_crit = None
        n_features = len(data[0]) - 1

        for feat in range(n_features):
            vals = sorted(list(set(row[feat] for row in data)))
            # Sample thresholds for speed if too many distinct values
            if len(vals) > 20:
                step = max(1, len(vals) // 20)
                sampled_vals = [vals[i] for i in range(0, len(vals), step)]
            else:
                sampled_vals = vals

            for i in range(len(sampled_vals) - 1):
                thresh = (sampled_vals[i] + sampled_vals[i + 1]) / 2.0
                left, right = self._split(data, feat, thresh)
                if not left or not right:
                    continue
                p_left = len(left) / len(data)
                p_right = len(right) / len(data)
                info_gain = base_entropy - (p_left * self._entropy([r[-1] for r in left]) +
                                            p_right * self._entropy([r[-1] for r in right]))
                if info_gain > best_gain:
                    best_gain = info_gain
                    best_crit = (feat, thresh, left, right, info_gain)

        return best_crit

    def _build_tree(self, data: List[List[Any]], depth: int, total_samples: int):
        labels = [row[-1] for row in data]
        counts = {}
        for l in labels:
            counts[l] = counts.get(l, 0) + 1
        majority = max(counts, key=counts.get) if counts else "HUMAN"

        # Base conditions
        if depth >= self.max_depth or len(set(labels)) == 1 or len(data) < self.min_samples_split:
            probs = {lbl: counts.get(lbl, 0) / len(labels) for lbl in CLASS_LABELS}
            return {"leaf": True, "label": majority, "probs": probs, "samples": len(data)}

        split = self._best_split(data)
        if not split:
            probs = {lbl: counts.get(lbl, 0) / len(labels) for lbl in CLASS_LABELS}
            return {"leaf": True, "label": majority, "probs": probs, "samples": len(data)}

        feat, thresh, left, right, gain = split
        if feat < len(self.feature_importances_):
            self.feature_importances_[feat] += (len(data) / total_samples) * gain

        return {
            "leaf": False,
            "feature": feat,
            "threshold": thresh,
            "left": self._build_tree(left, depth + 1, total_samples),
            "right": self._build_tree(right, depth + 1, total_samples)
        }

    def predict_one(self, x: List[float]) -> Tuple[str, Dict[str, float]]:
        curr = self.tree
        if not curr:
            return "UNCERTAIN", {l: 0.33 for l in CLASS_LABELS}

        while not curr.get("leaf", False):
            feat = curr["feature"]
            thresh = curr["threshold"]
            if x[feat] <= thresh:
                curr = curr["left"]
            else:
                curr = curr["right"]

        return curr["label"], curr["probs"]



class BehavioralClassifier:
    """Supervised Behavioral Classifier with Feature Importance and Confidence Scoring.

    Distinguishes three actor classes:
      - HUMAN: organic interaction with natural motor variability
      - TRADITIONAL_AUTOMATION: deterministic scripted execution
      - AGENTIC_AI: goal-driven adaptive browser behavior

    Note: webdriver_flag is treated as a supporting environmental signal,
    not as a primary classification criterion.
    """

    def __init__(self, model_type: str = "random_forest"):
        self.model_type = model_type
        self.feature_names = FEATURE_NAMES
        self.sklearn_model = None
        self.native_trees: List[SimpleDecisionTree] = []
        self.is_trained = False
        self.metrics = {}

    def extract_feature_vector(self, features: Dict[str, Any]) -> List[float]:
        return [float(features.get(k, 0.0)) for k in self.feature_names]

    def train(self, X: List[List[float]], y: List[str], model_name: str = "RandomForest"):
        """Train behavioral classifier on labeled dataset.
        Labels should be HUMAN, TRADITIONAL_AUTOMATION, or AGENTIC_AI.
        Legacy labels (BOT, AI_AGENT) are automatically normalized.
        """
        if not X or len(X) < 6:
            return {"error": "Dataset too small for training"}

        # Normalize legacy labels
        y = [normalize_label(lbl) for lbl in y]

        # Try training scikit-learn model
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.linear_model import LogisticRegression
            from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix
            from sklearn.model_selection import train_test_split

            if model_name == "LogisticRegression":
                clf = LogisticRegression(max_iter=1000, random_state=42)
            else:
                clf = RandomForestClassifier(n_estimators=30, max_depth=6, random_state=42)

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y if len(set(y)) > 1 else None)
            clf.fit(X_train, y_train)
            y_pred = clf.predict(X_test)

            acc = float(accuracy_score(y_test, y_pred))
            p, r, f1, _ = precision_recall_fscore_support(y_test, y_pred, average="macro", zero_division=0)
            cm = confusion_matrix(y_test, y_pred, labels=CLASS_LABELS).tolist()

            importances = []
            if hasattr(clf, "feature_importances_"):
                importances = [{"feature": k, "importance": round(float(v), 4)} for k, v in zip(self.feature_names, clf.feature_importances_)]
                importances.sort(key=lambda x: x["importance"], reverse=True)

            self.sklearn_model = clf
            self.is_trained = True
            self.metrics = {
                "accuracy": round(acc, 4),
                "precision": round(float(p), 4),
                "recall": round(float(r), 4),
                "f1": round(float(f1), 4),
                "confusion_matrix": cm,
                "feature_importance": importances,
                "model_name": model_name
            }
            return self.metrics
        except Exception:
            # Native Python Ensemble fallback — metrics computed from real hold-out
            rng_native = random.Random(42)
            n = len(X)
            indices = list(range(n))
            rng_native.shuffle(indices)
            split = max(1, int(n * 0.75))
            train_idx = indices[:split]
            test_idx  = indices[split:]

            X_tr = [X[i] for i in train_idx]
            y_tr = [y[i] for i in train_idx]
            X_te = [X[i] for i in test_idx] if test_idx else X_tr
            y_te = [y[i] for i in test_idx] if test_idx else y_tr

            self.native_trees = []
            for _ in range(7):
                sample_idx = [rng_native.randint(0, len(X_tr) - 1) for _ in range(len(X_tr))]
                X_s = [X_tr[i] for i in sample_idx]
                y_s = [y_tr[i] for i in sample_idx]
                dt = SimpleDecisionTree(max_depth=5).fit(X_s, y_s)
                self.native_trees.append(dt)

            y_pred_te = []
            for xv in X_te:
                votes = {c: 0 for c in CLASS_LABELS}
                for dt in self.native_trees:
                    lbl, _ = dt.predict_one(xv)
                    votes[lbl] = votes.get(lbl, 0) + 1
                y_pred_te.append(max(votes, key=votes.get))

            correct = sum(1 for t, p in zip(y_te, y_pred_te) if t == p)
            acc = correct / len(y_te) if y_te else 0.0

            prec_sum = recall_sum = f1_sum = 0.0
            for lbl in CLASS_LABELS:
                tp = sum(1 for t, p in zip(y_te, y_pred_te) if t == lbl and p == lbl)
                fp = sum(1 for t, p in zip(y_te, y_pred_te) if t != lbl and p == lbl)
                fn = sum(1 for t, p in zip(y_te, y_pred_te) if t == lbl and p != lbl)
                prec   = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                f1_v   = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0.0
                prec_sum += prec; recall_sum += recall; f1_sum += f1_v

            n_cls = len(CLASS_LABELS)
            
            # Compute real confusion matrix from hold-out predictions
            cm_dict = {l1: {l2: 0 for l2 in CLASS_LABELS} for l1 in CLASS_LABELS}
            for t, p in zip(y_te, y_pred_te):
                if t in cm_dict and p in cm_dict[t]:
                    cm_dict[t][p] += 1
            cm_list = [[cm_dict[r][c] for c in CLASS_LABELS] for r in CLASS_LABELS]

            # Aggregate feature importances across all native trees
            n_feats = len(self.feature_names)
            feat_imp_sum = [0.0] * n_feats
            for dt in self.native_trees:
                for idx, imp in enumerate(dt.feature_importances_):
                    if idx < n_feats:
                        feat_imp_sum[idx] += imp
            tot_imp = sum(feat_imp_sum)
            if tot_imp > 0:
                feat_imp_sum = [v / tot_imp for v in feat_imp_sum]
            else:
                feat_imp_sum = [1.0 / max(1, n_feats)] * n_feats

            importances = [
                {"feature": k, "importance": round(float(v), 4)}
                for k, v in zip(self.feature_names, feat_imp_sum)
            ]
            importances.sort(key=lambda x: x["importance"], reverse=True)

            self.is_trained = True
            self.metrics = {
                "accuracy":  round(acc, 4),
                "precision": round(prec_sum / n_cls, 4),
                "recall":    round(recall_sum / n_cls, 4),
                "f1":        round(f1_sum / n_cls, 4),
                "confusion_matrix": cm_list,
                "feature_importance": importances,
                "model_name": f"NativeEnsemble({model_name})",
                "note": "Native Python ensemble — real holdout metrics.",
            }
            return self.metrics

    def predict(self, features: Dict[str, Any]) -> Tuple[str, float, Dict[str, float]]:
        """
        Returns (predicted_class, confidence_score 0-100, probability_distribution).
        Output is one of: HUMAN, TRADITIONAL_AUTOMATION, AGENTIC_AI
        """
        vec = self.extract_feature_vector(features)

        # Scikit-learn model inference if available
        if self.sklearn_model:
            try:
                probs = self.sklearn_model.predict_proba([vec])[0]
                classes = list(self.sklearn_model.classes_)
                prob_dict = {c: float(probs[classes.index(c)]) if c in classes else 0.0 for c in CLASS_LABELS}
                top_class = max(prob_dict, key=prob_dict.get)
                conf = prob_dict[top_class] * 100.0
                return top_class, round(conf, 2), prob_dict
            except Exception:
                pass

        # Native Ensemble Inference
        if self.native_trees:
            accum_probs = {c: 0.0 for c in CLASS_LABELS}
            for dt in self.native_trees:
                _, p = dt.predict_one(vec)
                for c in CLASS_LABELS:
                    accum_probs[c] += p.get(c, 0.0)
            n_trees = len(self.native_trees)
            prob_dict = {c: round(accum_probs[c] / n_trees, 4) for c in CLASS_LABELS}
            top_class = max(prob_dict, key=prob_dict.get)
            conf = prob_dict[top_class] * 100.0
            return top_class, round(conf, 2), prob_dict

        # Calibrated heuristic fallback if untrained
        straightness = features.get("straightness_ratio", 0.8)
        micro_c = features.get("micro_corrections", 0)
        key_cv = features.get("key_latency_cv", 0.4)
        key_hold = features.get("key_mean_hold_time", 60.0)
        key_count = features.get("key_event_count", 0)
        planning_pause = features.get("planning_pause_ratio", 0.0)
        adaptation = features.get("adaptation_score", 0.0)
        nav_segments = features.get("nav_segment_count", 0)

        # 1. Agentic AI profile check
        if (planning_pause > 0.25 and nav_segments >= 2) or (adaptation > 0.35 and planning_pause > 0.15):
            return "AGENTIC_AI", 84.0, {
                "HUMAN": 0.10, "TRADITIONAL_AUTOMATION": 0.06, "AGENTIC_AI": 0.84
            }

        # 2. Traditional Automation check (uniform keystrokes, short hold times, rigid lines)
        if (key_count >= 4 and (key_cv < 0.18 or (0 < key_hold < 35.0))) or (straightness > 0.94 and (key_cv < 0.22 or micro_c <= 2)):
            return "TRADITIONAL_AUTOMATION", 86.0, {
                "HUMAN": 0.08, "TRADITIONAL_AUTOMATION": 0.86, "AGENTIC_AI": 0.06
            }

        # 3. Organic Human behavior
        if micro_c >= 3 and straightness < 0.88 and (key_count < 4 or (key_cv >= 0.25 and key_hold >= 40.0)):
            return "HUMAN", 88.0, {
                "HUMAN": 0.88, "TRADITIONAL_AUTOMATION": 0.06, "AGENTIC_AI": 0.06
            }

        return "HUMAN", 65.0, {
            "HUMAN": 0.65, "TRADITIONAL_AUTOMATION": 0.20, "AGENTIC_AI": 0.15
        }

    # ── Ablation experiment helpers ────────────────────────────────────────────

    def train_on_vectors(
        self,
        X: List[List[float]],
        y: List[str],
        feature_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Trains directly on pre-projected feature vectors (used by experiments.py).
        """
        orig_names = self.feature_names
        if feature_names:
            self.feature_names = feature_names
        result = self.train(X, y, model_name="RandomForest")
        if feature_names:
            self.feature_names = orig_names
        return result

    def predict_vector(self, x: List[float]) -> Tuple[str, float, Dict[str, float]]:
        """
        Predicts directly from a pre-projected float vector (used by experiments.py).
        """
        if self.sklearn_model:
            try:
                probs = self.sklearn_model.predict_proba([x])[0]
                classes = list(self.sklearn_model.classes_)
                prob_dict = {c: float(probs[classes.index(c)]) if c in classes else 0.0
                             for c in CLASS_LABELS}
                top_class = max(prob_dict, key=prob_dict.get)
                conf = prob_dict[top_class] * 100.0
                return top_class, round(conf, 2), prob_dict
            except Exception:
                pass

        if self.native_trees:
            accum = {c: 0.0 for c in CLASS_LABELS}
            for dt in self.native_trees:
                _, p = dt.predict_one(x)
                for c in CLASS_LABELS:
                    accum[c] += p.get(c, 0.0)
            n = len(self.native_trees)
            prob_dict = {c: round(accum[c] / n, 4) for c in CLASS_LABELS}
            top_class = max(prob_dict, key=prob_dict.get)
            return top_class, round(prob_dict[top_class] * 100.0, 2), prob_dict

        return "UNCERTAIN", 33.0, {c: 0.33 for c in CLASS_LABELS}

    def get_feature_importance(
        self, feature_names: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Returns feature importance from trained sklearn model, or empty list for native."""
        if self.sklearn_model and hasattr(self.sklearn_model, "feature_importances_"):
            names = feature_names or self.feature_names
            pairs = list(zip(names, self.sklearn_model.feature_importances_))
            pairs.sort(key=lambda x: x[1], reverse=True)
            return [{"feature": k, "importance": round(float(v), 5)} for k, v in pairs]
        return self.metrics.get("feature_importance", [])
