"""Lazy backend adapters and offline model resolution."""

import math
import os
import re
import time
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Callable

from . import CANDIDATES, CandidateSpec, LABELS

REPOSITORIES = {
    "gliclass": ("knowledgator/gliclass-small-v1.0", "GLICLASS_REV"),
    "laya": ("convaiinnovations/laya", "LAYA_REV"),
}


def parse_revision_pins(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=([A-Za-z0-9._-]+)", line)
        if not match:
            raise ValueError(f"invalid revision pin line: {line!r}")
        values[match.group(1)] = match.group(2)
    for key in ("GLICLASS_REV", "LAYA_REV"):
        if key not in values:
            raise ValueError(f"missing {key} in model revision file")
    return values


def offline_model_path(download: Callable[..., str], repo_id: str, revision: str) -> Path:
    """Use the cached weight file's directory; intentionally do not resolve its symlink."""
    return Path(download(repo_id=repo_id, filename="model.safetensors", revision=revision, local_files_only=True)).parent


class Backend:
    def __init__(self, name: str, revision_file: Path):
        if name not in (*REPOSITORIES, "rules"):
            raise ValueError(f"unknown backend {name!r}")
        self.name = name
        self.revision_file = revision_file
        self.load_seconds = 0.0
        self._predict = None

    def load(self) -> None:
        started = time.perf_counter()
        if self.name == "rules":
            from .rules import predict_rules
            self._predict = predict_rules
        else:
            os.environ["HF_HUB_OFFLINE"] = "1"
            import torch
            from huggingface_hub import hf_hub_download
            torch.set_num_threads(4)
            pins = parse_revision_pins(self.revision_file)
            repo_id, revision_key = REPOSITORIES[self.name]
            path = offline_model_path(hf_hub_download, repo_id, pins[revision_key])
            if self.name == "gliclass":
                from gliclass import GLiClassModel, ZeroShotClassificationPipeline
                from transformers import AutoTokenizer
                model = GLiClassModel.from_pretrained(path, local_files_only=True)
                model.eval()
                tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
                pipeline = ZeroShotClassificationPipeline(model, tokenizer, classification_type="single-label", device="cpu", progress_bar=False)

                def predict(text: str) -> dict:
                    model_scores = pipeline(text, list(build_gliclass_candidate_labels()), batch_size=1, classification_type="single-label", return_hierarchical=True)[0]
                    mapped = canonicalize_gliclass_scores(model_scores)
                    selected = max(mapped, key=mapped.get)
                    selected, mapped = validate_neural_prediction("gliclass", selected, mapped)
                    return {"selected_class": selected, "scores": mapped, "confidence": None, "answer_confidence": None}
                self._predict = predict
            else:
                import laya
                agent = laya.load(path, device="cpu")

                def predict(text: str) -> dict:
                    result = agent.predict(text, build_laya_question())
                    return normalize_laya_result(result)
                self._predict = predict
        self.load_seconds = time.perf_counter() - started

    def predict(self, text: str) -> dict:
        if self._predict is None:
            raise RuntimeError("backend must be loaded before predict")
        started = time.perf_counter()
        result = self._predict(text)
        result["inference_seconds"] = time.perf_counter() - started
        result["backend"] = self.name
        return result


def canonicalize_named_scores(scores: Mapping[str, float], candidate_ids: Sequence[str], candidate_names: Sequence[str]) -> dict[str, float]:
    """Map a flat model-facing name score map back to stable caller IDs."""
    if len(candidate_ids) != len(candidate_names) or len(set(candidate_ids)) != len(candidate_ids) or len(set(candidate_names)) != len(candidate_names):
        raise InvalidModelOutput("gliclass action candidates must have unique, paired IDs and names")
    if not isinstance(scores, Mapping) or set(scores) != set(candidate_names):
        raise InvalidModelOutput("gliclass returned scores outside the supplied candidate names")
    normalized = {}
    for candidate_id, candidate_name in zip(candidate_ids, candidate_names, strict=True):
        try:
            value = float(scores[candidate_name])
        except (TypeError, ValueError) as exc:
            raise InvalidModelOutput(f"gliclass returned a non-numeric score for {candidate_name!r}") from exc
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise InvalidModelOutput(f"gliclass returned an invalid score for {candidate_name!r}: {value!r}")
        normalized[candidate_id] = value
    return normalized


class GLiClassActionRanker:
    """Reusable offline GLiClass single-label ranker for arbitrary short candidates."""

    def __init__(self, revision_file: Path):
        self.revision_file = revision_file
        self.load_seconds = 0.0
        self._pipeline = None

    def load(self) -> None:
        started = time.perf_counter()
        os.environ["HF_HUB_OFFLINE"] = "1"
        import torch
        from huggingface_hub import hf_hub_download
        from gliclass import GLiClassModel, ZeroShotClassificationPipeline
        from transformers import AutoTokenizer

        torch.set_num_threads(4)
        pins = parse_revision_pins(self.revision_file)
        repository, revision_key = REPOSITORIES["gliclass"]
        path = offline_model_path(hf_hub_download, repository, pins[revision_key])
        model = GLiClassModel.from_pretrained(path, local_files_only=True)
        model.eval()
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self._pipeline = ZeroShotClassificationPipeline(model, tokenizer, classification_type="single-label", device="cpu", progress_bar=False)
        self.load_seconds = time.perf_counter() - started

    def rank(self, text: str, candidates: Sequence[tuple[str, str]]) -> dict[str, float]:
        if self._pipeline is None:
            raise RuntimeError("GLiClass action ranker must be loaded before rank")
        if not candidates:
            raise ValueError("at least one action candidate is required")
        candidate_ids = tuple(item[0] for item in candidates)
        candidate_names = tuple(item[1] for item in candidates)
        returned = self._pipeline(text, list(candidate_names), batch_size=1, classification_type="single-label", return_hierarchical=True)[0]
        scores = canonicalize_named_scores(returned, candidate_ids, candidate_names)
        selected = max(candidate_ids, key=scores.get)
        validation_candidates = tuple(CandidateSpec(candidate_id, name, "") for candidate_id, name in candidates)
        return validate_neural_prediction("gliclass workflow", selected, scores, validation_candidates)[1]


def build_gliclass_candidate_labels(candidates: Sequence[CandidateSpec] = CANDIDATES) -> tuple[str, ...]:
    """Return flat short labels, the tested native format for this checkpoint."""
    return tuple(candidate.name for candidate in candidates)


def build_laya_question(candidates: Sequence[CandidateSpec] = CANDIDATES) -> dict:
    return {"incident": {
        "type": "choice",
        "instructions": "Which category best describes the service condition?",
        "criteria": {candidate.name: candidate.description for candidate in candidates},
    }}


def canonicalize_gliclass_scores(scores: Mapping[str, float], candidates: Sequence[CandidateSpec] = CANDIDATES) -> dict[str, float]:
    model_labels = build_gliclass_candidate_labels(candidates)
    if isinstance(scores, Mapping) and set(scores) == {"incident"} and isinstance(scores["incident"], Mapping):
        scores = scores["incident"]
    if isinstance(scores, Mapping) and set(scores) == {f"incident.{label}" for label in model_labels}:
        scores = {label: scores[f"incident.{label}"] for label in model_labels}
    if set(scores) != set(model_labels):
        raise InvalidModelOutput("gliclass returned unexpected candidate score keys")
    return {candidate.id: float(scores[label]) for candidate, label in zip(candidates, model_labels, strict=True)}


class InvalidModelOutput(ValueError):
    """A neural backend returned a malformed class prediction or score map."""


def validate_neural_prediction(
    backend: str,
    selected_class: str,
    scores: Mapping[str, float],
    candidates: Sequence[CandidateSpec] = CANDIDATES,
) -> tuple[str, dict[str, float]]:
    expected = tuple(candidate.id for candidate in candidates)
    if selected_class not in expected:
        raise InvalidModelOutput(f"{backend} returned unknown selected class {selected_class!r}")
    if not isinstance(scores, Mapping) or set(scores) != set(expected):
        raise InvalidModelOutput(f"{backend} must return scores for exactly {expected}")
    normalized = {}
    for label in expected:
        try:
            score = float(scores[label])
        except (TypeError, ValueError) as exc:
            raise InvalidModelOutput(f"{backend} returned a non-numeric score for {label}") from exc
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise InvalidModelOutput(f"{backend} returned an invalid score for {label}: {score!r}")
        normalized[label] = score
    if abs(sum(normalized.values()) - 1.0) > 0.01:
        raise InvalidModelOutput(f"{backend} score probabilities do not sum to one")
    if normalized[selected_class] + 0.0011 < max(normalized.values()):
        raise InvalidModelOutput(f"{backend} selected class is inconsistent with its largest score")
    return selected_class, normalized


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _as_mapping(value):
    return value if isinstance(value, dict) else vars(value) if hasattr(value, "__dict__") else {}


def normalize_laya_result(result, candidates: Sequence[CandidateSpec] = CANDIDATES) -> dict:
    """Map Laya's named choice to canonical IDs and validate its native distribution."""
    answers = _as_mapping(_get(result, "answers", {}))
    incident = _as_mapping(answers.get("incident", {}))
    raw_choice = incident.get("choice")
    choice_to_id = {candidate.id: candidate.id for candidate in candidates}
    choice_to_id.update({candidate.name: candidate.id for candidate in candidates})
    if isinstance(raw_choice, int) and not isinstance(raw_choice, bool):
        selected = candidates[raw_choice].id if 0 <= raw_choice < len(candidates) else None
    else:
        selected = choice_to_id.get(raw_choice)
    if selected is None:
        raise InvalidModelOutput(f"laya returned unknown selected choice {raw_choice!r}")

    scores = incident.get("probabilities")
    if scores is None:
        probabilities = _as_mapping(_get(result, "probabilities", {}))
        scores = probabilities.get("incident") if probabilities else None
    if isinstance(scores, (list, tuple)) and len(scores) == len(candidates):
        scores = {candidate.id: value for candidate, value in zip(candidates, scores, strict=True)}
    elif isinstance(scores, Mapping):
        by_name = {candidate.name: candidate.id for candidate in candidates}
        if set(scores) == set(by_name):
            scores = {by_name[name]: value for name, value in scores.items()}
    selected, scores = validate_neural_prediction("laya", selected, scores, candidates)

    confidence = incident.get("confidence", _get(result, "confidence"))
    answer_confidence = incident.get("answer_confidence", _get(result, "answer_confidence"))
    action = _as_mapping(incident.get("action", {})).get("act_probability")
    for field, value in (("confidence", confidence), ("answer_confidence", answer_confidence), ("action_act_probability", action)):
        if value is not None:
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise InvalidModelOutput(f"laya returned non-numeric {field}") from exc
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise InvalidModelOutput(f"laya returned invalid {field}: {value!r}")
    return {
        "selected_class": selected, "scores": scores, "confidence": confidence,
        "answer_confidence": answer_confidence, "action_act_probability": action,
    }
