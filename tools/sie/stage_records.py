"""Project model-stage evidence for storage without changing caller results."""
import copy
import json


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated model response key")
        result[key] = value
    return result


def _matches(outcome, expected):
    if not isinstance(outcome, dict) or outcome.get("ok") is not True or outcome.get("error"):
        return False
    text = outcome.get("result")
    if not isinstance(text, str):
        return False
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text.removeprefix("```json\n").removesuffix("\n```")
    try:
        return json.loads(text, object_pairs_hook=_unique_object) == expected
    except ValueError:
        return False


def _proposal_backend(proposal):
    if not isinstance(proposal, dict):
        return None
    expected = {key: proposal.get(key) for key in ("file_rel", "new_content")}
    if not all(isinstance(value, str) and value.strip() for value in expected.values()):
        return None
    backend = proposal.get("backend")
    return backend if _matches(backend, expected) else None


def _mark_parsed(outcome):
    outcome.pop("result", None)
    outcome["result_storage"] = "parsed"


def compact_record(filename: str, record: dict) -> dict:
    """Omit successful raw responses only when their exact parsed content is retained.

    Accept whole JSON or one exact JSON fence, without duplicate object keys.
    Preserve failed, unmatched and extra-field responses. Only recognized stage
    fields are projected; nested attempts and opaque metadata remain intact.
    """
    projected = copy.deepcopy(record)
    outcomes = projected.get("backend_outcomes", [])
    if not isinstance(outcomes, list):
        outcomes = []
    if filename in {"reflections.jsonl", "reflector-outcomes.jsonl"}:
        for outcome in outcomes:
            findings = outcome.get("findings") if isinstance(outcome, dict) else None
            if (isinstance(findings, list)
                    and all(isinstance(item, str) and item.strip() for item in findings)
                    and _matches(outcome, {"findings": findings})):
                _mark_parsed(outcome)
    elif filename == "proposals.jsonl":
        proposals = record.get("proposals", [])
        if not isinstance(proposals, list):
            return projected
        # Compare outcomes to unchanged originals, even when input objects alias.
        successful = []
        for proposal in proposals:
            backend = _proposal_backend(proposal)
            if backend is not None:
                successful.append(backend)
        for proposal in projected.get("proposals", []):
            backend = _proposal_backend(proposal)
            if backend is not None:
                _mark_parsed(backend)
        for outcome in outcomes:
            if outcome in successful:
                _mark_parsed(outcome)
    return projected
