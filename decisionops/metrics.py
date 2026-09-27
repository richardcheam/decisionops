"""Small transparent classification metrics; no model fitting or thresholds."""

import math
from collections import defaultdict


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_classifications(rows: list[dict], labels: tuple[str, ...]) -> dict:
    matrix = {label: {column: 0 for column in (*labels, "abstain")} for label in labels}
    correct = covered = total = 0
    for row in rows:
        expected = row["expected_label"]
        if expected not in labels:
            continue
        selected = row["selected_class"]
        column = selected if selected in labels else "abstain"
        matrix[expected][column] += 1
        total += 1
        covered += column != "abstain"
        correct += selected == expected
    return {
        "count": total,
        "correct": correct,
        "accuracy": correct / total if total else None,
        "coverage": covered / total if total else None,
        "confusion_matrix": matrix,
    }


def summarize_challenge_and_review(rows: list[dict], labels: tuple[str, ...]) -> dict:
    """Report labeled challenge quality and review disposition separately."""
    challenge = [row for row in rows if "challenge" in row.get("tags", [])]
    labeled = [row for row in challenge if not row.get("needs_review") and row.get("expected_label") in labels]
    correct = sum(row.get("selected_class") == row["expected_label"] for row in labeled)
    review = [row for row in challenge if row.get("needs_review")]
    abstentions = sum(row.get("selected_class") is None for row in review)
    forced_by_class = {label: sum(row.get("selected_class") == label for row in review) for label in labels}
    forced = len(review) - abstentions
    return {
        "labeled_challenge": {
            "count": len(labeled), "correct": correct,
            "accuracy": correct / len(labeled) if labeled else None,
        },
        "review_cases": {
            "count": len(review), "abstentions": abstentions,
            "forced_predictions": forced, "forced_by_class": forced_by_class,
        },
    }
