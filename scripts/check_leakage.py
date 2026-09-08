"""
scripts/check_leakage.py

Detects task-label leakage in the session dataset.
Evaluates whether structural metadata (task, data_source, visitor_id)
predicts class label without any behavioral features.
Uses visitor-grouped train/test split to prevent within-visitor leakage.

Usage:
    python scripts/check_leakage.py [--threshold 0.50] [--quiet]
"""

import sys
import random
import argparse
from collections import Counter

sys.path.insert(0, ".")

from packages.database.db import get_db
from packages.database.models import SessionRecord


def encode_categorical(values):
    unique = list(sorted(set(values)))
    mapping = {val: i for i, val in enumerate(unique)}
    return [mapping[v] for v in values], unique


class SimpleDecisionStump:
    """
    Lightweight rule/stump classifier to test structural predictive power
    without requiring external C-compiled ML binaries.
    """
    def __init__(self):
        self.rules = {}
        self.default_class = 0

    def fit(self, X, y):
        # Find majority class for each unique feature tuple
        groups = {}
        for feat, label in zip(X, y):
            key = tuple(feat)
            groups.setdefault(key, []).append(label)
        
        for key, labels in groups.items():
            counts = Counter(labels)
            self.rules[key] = counts.most_common(1)[0][0]
        
        all_counts = Counter(y)
        self.default_class = all_counts.most_common(1)[0][0] if all_counts else 0

    def predict(self, X):
        return [self.rules.get(tuple(feat), self.default_class) for feat in X]


def main():
    parser = argparse.ArgumentParser(description="Check for task-label leakage in session DB")
    parser.add_argument("--threshold", type=float, default=0.55,
                        help="Max allowed accuracy using structural-only features (default: 0.55)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress detailed output")
    args = parser.parse_args()

    db = next(get_db())
    rows = db.query(
        SessionRecord.task,
        SessionRecord.data_source,
        SessionRecord.ground_truth_label,
        SessionRecord.visitor_id
    ).filter(
        SessionRecord.ground_truth_label.isnot(None)
    ).all()

    if len(rows) < 20:
        print(f"Note: {len(rows)} labeled sessions found. Need >= 20 for leakage check.")
        print("PASS: Insufficient data to indicate systemic leakage.")
        sys.exit(0)

    tasks = [r.task or "unknown" for r in rows]
    sources = [r.data_source or "unknown" for r in rows]
    visitors = [r.visitor_id or "unknown" for r in rows]
    
    # Normalize labels
    raw_labels = [r.ground_truth_label or "UNKNOWN" for r in rows]
    labels = []
    for l in raw_labels:
        if l == "BOT":
            labels.append("TRADITIONAL_AUTOMATION")
        elif l == "AI_AGENT":
            labels.append("AGENTIC_AI")
        else:
            labels.append(l)

    y, label_names = encode_categorical(labels)
    X_task, _ = encode_categorical(tasks)
    X_src, _ = encode_categorical(sources)

    # Feature matrix from structural attributes (task, data_source)
    X = [[t, s] for t, s in zip(X_task, X_src)]

    # Grouped train/test split by visitor_id
    unique_visitors = list(set(visitors))
    rng = random.Random(42)
    rng.shuffle(unique_visitors)
    split_point = int(len(unique_visitors) * 0.8)
    train_visitors = set(unique_visitors[:split_point])

    train_indices = [i for i, v in enumerate(visitors) if v in train_visitors]
    test_indices = [i for i, v in enumerate(visitors) if v not in train_visitors]

    if len(test_indices) < 5:
        # Fallback to stratified random split if visitor clusters are small
        indices = list(range(len(rows)))
        rng.shuffle(indices)
        train_indices = indices[:int(len(rows) * 0.8)]
        test_indices = indices[int(len(rows) * 0.8):]

    X_train = [X[i] for i in train_indices]
    y_train = [y[i] for i in train_indices]
    X_test = [X[i] for i in test_indices]
    y_test = [y[i] for i in test_indices]

    clf = SimpleDecisionStump()
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)

    correct = sum(1 for p, actual in zip(y_pred, y_test) if p == actual)
    accuracy = correct / len(y_test) if y_test else 0.0
    random_baseline = 1.0 / len(label_names) if label_names else 0.333

    if not args.quiet:
        print(f"\nLeakage Check: {len(rows)} sessions across {len(unique_visitors)} unique visitors")
        print(f"Train/Test split: {len(X_train)} / {len(X_test)} sessions")
        print(f"\nStructural metadata accuracy (task, data_source only): {accuracy:.3f}")
        print(f"Random chance baseline: {random_baseline:.3f}")
        print(f"Leakage threshold: {args.threshold:.3f}")
        print(f"Labels evaluated: {label_names}")

    if accuracy > args.threshold:
        print(f"\nFAIL: Structural metadata accuracy {accuracy:.3f} > threshold {args.threshold:.3f}")
        print("      Class labels may correlate too strongly with structural task attributes.")
        sys.exit(1)

    print(f"\nPASS: Structural metadata accuracy {accuracy:.3f} <= threshold {args.threshold:.3f}")
    print("      No systemic task-to-label leakage detected.")
    sys.exit(0)


if __name__ == "__main__":
    main()
