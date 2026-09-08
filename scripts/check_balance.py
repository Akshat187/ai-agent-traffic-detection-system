"""
scripts/check_balance.py

Verifies class/task balance in the sessions database.
Prints a (class, task) count grid and exits non-zero if any
cell is more than 3x any other non-zero cell.

Usage:
    python scripts/check_balance.py [--threshold N] [--quiet]
"""

import sys
import math
import argparse

# Add project root to path so we can import packages
sys.path.insert(0, ".")

from packages.database.db import get_db
from packages.database.models import SessionRecord


VALID_CLASSES = ["HUMAN", "TRADITIONAL_AUTOMATION", "AGENTIC_AI"]
VALID_TASKS   = ["shopping", "travel", "forum"]


def calculate_chi2(contingency_table):
    """
    Computes chi-squared statistic and approximate p-value from a 2D contingency grid.
    Works with pure python / math so no heavy C compiler dependency is required.
    """
    row_sums = [sum(row) for row in contingency_table]
    col_sums = [sum(contingency_table[r][c] for r in range(len(contingency_table))) for c in range(len(contingency_table[0]))]
    total = sum(row_sums)
    if total == 0:
        return 0.0, 1.0

    chi2 = 0.0
    for r in range(len(contingency_table)):
        for c in range(len(contingency_table[0])):
            expected = (row_sums[r] * col_sums[c]) / total if total > 0 else 0.0
            observed = contingency_table[r][c]
            if expected > 0:
                chi2 += ((observed - expected) ** 2) / expected

    dof = (len(row_sums) - 1) * (len(col_sums) - 1)
    
    # Try scipy if installed
    try:
        from scipy.stats import chi2 as scipy_chi2
        p_value = 1.0 - scipy_chi2.cdf(chi2, dof)
    except Exception:
        # Wilson-Hilferty transformation approximation for chi2 survival function
        if dof > 0 and chi2 > 0:
            z = math.pow(chi2 / dof, 1/3) - (1 - 2/(9*dof))
            z /= math.sqrt(2/(9*dof))
            # Standard normal CDF approximation
            p_value = 0.5 * math.erfc(z / math.sqrt(2))
        else:
            p_value = 1.0

    return chi2, max(0.0, min(1.0, p_value))


def main():
    parser = argparse.ArgumentParser(description="Check class/task balance in session DB")
    parser.add_argument("--threshold", type=float, default=3.0,
                        help="Max ratio of largest to smallest non-zero cell (default: 3.0)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress table output; only print summary and errors")
    args = parser.parse_args()

    db = next(get_db())

    # Query ground truth or predicted label counts
    rows = db.query(
        SessionRecord.ground_truth_label,
        SessionRecord.task
    ).all()

    # Build count grid
    grid = {}
    for cls in VALID_CLASSES:
        for task in VALID_TASKS:
            grid[(cls, task)] = 0

    unknown_rows = []
    for row in rows:
        cls = row.ground_truth_label or "UNKNOWN"
        task = row.task or "UNKNOWN"
        # Map legacy aliases
        if cls == "BOT":
            cls = "TRADITIONAL_AUTOMATION"
        elif cls == "AI_AGENT":
            cls = "AGENTIC_AI"

        key = (cls, task)
        if key in grid:
            grid[key] += 1
        else:
            unknown_rows.append(key)

    total = sum(grid.values())

    if total == 0:
        print("ERROR: No sessions found in database.")
        sys.exit(2)

    # Print table
    if not args.quiet:
        col_width = max(len(t) for t in VALID_TASKS) + 4
        cls_width = max(len(c) for c in VALID_CLASSES) + 4

        header = " " * cls_width + "".join(t.ljust(col_width) for t in VALID_TASKS) + "  TOTAL"
        print("\n" + "=" * len(header))
        print("  SESSION CLASS / TASK BALANCE")
        print("=" * len(header))
        print(header)
        print("-" * len(header))

        for cls in VALID_CLASSES:
            row_total = sum(grid[(cls, t)] for t in VALID_TASKS)
            cells = "".join(str(grid[(cls, t)]).ljust(col_width) for t in VALID_TASKS)
            print(f"{cls.ljust(cls_width)}{cells}  {row_total}")

        print("-" * len(header))
        col_totals = "".join(
            str(sum(grid[(c, t)] for c in VALID_CLASSES)).ljust(col_width)
            for t in VALID_TASKS
        )
        print(f"{'TOTAL'.ljust(cls_width)}{col_totals}  {total}")
        print("=" * len(header))

        # Per-class distribution
        print("\nClass distribution:")
        for cls in VALID_CLASSES:
            cls_total = sum(grid[(cls, t)] for t in VALID_TASKS)
            pct = 100 * cls_total / total if total > 0 else 0
            print(f"  {cls}: {cls_total} ({pct:.1f}%)")

        if unknown_rows:
            print(f"\nNote: {len(unknown_rows)} rows with unrecognized class/task combinations")

    # Balance check
    non_zero = [v for v in grid.values() if v > 0]
    if not non_zero:
        print("ERROR: All cells are zero.")
        sys.exit(2)

    max_cell = max(non_zero)
    min_cell = min(non_zero)
    ratio = max_cell / min_cell if min_cell > 0 else float("inf")

    print(f"\nBalance ratio (max/min non-zero): {ratio:.2f}  (threshold: {args.threshold:.1f})")

    # Chi-squared test for class-task independence (leakage proxy)
    contingency = [
        [grid[(cls, t)] for t in VALID_TASKS]
        for cls in VALID_CLASSES
    ]
    min_cell_val = min(min(row) for row in contingency)
    if min_cell_val >= 1:
        chi2, p_val = calculate_chi2(contingency)
        print(f"Chi-squared statistic: {chi2:.2f}, p-value (class | task): {p_val:.4f}  "
              f"(p < 0.05 indicates potential task-label correlation)")
    else:
        print("Chi-squared: some cells have 0 counts (more balanced data needed for asymptotic test)")

    if ratio > args.threshold:
        print(f"\nFAIL: Balance ratio {ratio:.2f} exceeds threshold {args.threshold:.1f}")
        print("      Reseed the database with balanced data before running experiments.")
        sys.exit(1)

    print(f"\nPASS: Balance ratio {ratio:.2f} is within acceptable range.")
    sys.exit(0)


if __name__ == "__main__":
    main()
