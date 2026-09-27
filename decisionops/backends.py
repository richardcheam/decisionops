"""Lazy backend adapters and offline model resolution."""

import os
import re
import time
from pathlib import Path
from typing import Callable

from . import DESCRIPTIONS, LABELS

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
                    scores = pipeline(text, list(LABELS), batch_size=1, classification_type="single-label", return_hierarchical=True)[0]
                    mapped = canonicalize_gliclass_scores(scores)
                    return {"selected_class": max(mapped, key=mapped.get), "scores": mapped, "confidence": None, "answer_confidence": None}
                self._predict = predict
            else:
                import laya
                agent = laya.load(path, device="cpu")

                def predict(text: str) -> dict:
                    result = agent.predict(text, {"incident": {"type": "choice", "instructions": "Which category best describes the service condition?", "criteria": DESCRIPTIONS}})
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


def canonicalize_gliclass_scores(scores: dict) -> dict[str, float]:
    if set(scores) != set(LABELS):
        raise ValueError("GLiClass score labels do not match canonical labels")
    return {label: float(scores[label]) for label in LABELS}


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _as_mapping(value):
    return value if isinstance(value, dict) else vars(value) if hasattr(value, "__dict__") else {}


def normalize_laya_result(result) -> dict:
    """Keep Laya's selected choice and native confidence values distinct."""
    answers = _as_mapping(_get(result, "answers", {}))
    incident = _as_mapping(answers.get("incident", {}))
    selected = incident.get("choice")
    if isinstance(selected, int):
        selected = LABELS[selected] if 0 <= selected < len(LABELS) else None
    if selected not in LABELS:
        selected = None
    scores = incident.get("probabilities")
    if scores is None:
        probabilities = _as_mapping(_get(result, "probabilities", {}))
        scores = probabilities.get("incident") if probabilities else None
    if isinstance(scores, (list, tuple)) and len(scores) == len(LABELS):
        scores = dict(zip(LABELS, map(float, scores), strict=True))
    if isinstance(scores, dict) and set(scores) == set(LABELS):
        scores = {label: float(scores[label]) for label in LABELS}
    else:
        scores = None
    return {
        "selected_class": selected,
        "scores": scores,
        "confidence": incident.get("confidence", _get(result, "confidence")),
        "answer_confidence": incident.get("answer_confidence", _get(result, "answer_confidence")),
        "action_act_probability": _as_mapping(incident.get("action", {})).get("act_probability"),
    }
