"""Lazy optional runtime loading and lossless execution diagnostics."""
from dataclasses import asdict, is_dataclass
import importlib


def load_runtime():
    runtime = importlib.import_module('llmcall')
    if not callable(getattr(runtime, 'call', None)):
        raise ImportError('llmcall.call is unavailable')
    # Validate the additive contract before any model call, including old installs.
    runtime.ModelSelection(family='codex')
    runtime.ExecutionRequirements(replay='never_after_start')
    if not hasattr(runtime, 'Result'):
        raise ImportError('llmcall.Result is unavailable')
    return runtime


def metadata(result):
    """Keep execution identity/evidence without copying model text or prompt data."""
    fields = ('error', 'outcome', 'effects', 'review_state', 'review_error', 'call_id',
              'execution_started', 'provider', 'effective_provider', 'effective_model',
              'model_family', 'model_source', 'configured_model', 'requested_model',
              'policy_source', 'selection_reason', 'adapter_family', 'provider_source',
              'attempts', 'evidence')
    values = result if isinstance(result, dict) else vars(result)
    out = {key: values[key] for key in fields if key in values}
    for key in ('error', 'review_error'):
        if isinstance(out.get(key), str):
            out[key] = out[key][:2000]
    if 'attempts' in out:
        out['attempts'] = [asdict(item) if is_dataclass(item) else item for item in out['attempts']]
    return out


class ProposalBatch(list):
    """Legacy list API with optional model-phase diagnostics for run records."""
    def __init__(self, values=(), *, model_result=None, fallback=None):
        super().__init__(values)
        self.model_result = model_result
        self.fallback = fallback
