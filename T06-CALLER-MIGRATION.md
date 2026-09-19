# Caller migration

Calls use one llmcall request with inherited model, effort and routing defaults.
Explicit user selections remain constraints. Timeouts, uncertain effects and
invalid outputs never cause a second business model call. Synthetic tests do
not certify production capabilities.

Python callers use llmcall directly. Proposers retain JS prompt/redaction and
validation codecs (--prepare / --validate); those modes never run models.
Source allowlists, truth stripping and artifact anchor-count gates remain.
Legacy JS entrypoints call the JSON CLI once. Family-only requests filter the
inherited chain through `ModelSelection.family`; matching gateway aliases remain
candidates in configured order. Only an explicitly supplied `chain` restricts
routes. Provider-reported family identity is still required. Default model and
effort pins are removed. Deterministic help/status/replay and builtin execution
do not load llmcall or probe a provider. Deployment needs the additive family
selection API staged in RUN/artifacts/T06-repair/llmcall-api, Python >= 3.11, and verified
read-only / WebSearch-only capabilities. SIE_PYTHON selects the interpreter for
legacy JS workers. No provider CLI fallback remains.

The optional runtime is imported and its exports validated only at model use.
Missing or incompatible packages return `dependency_unavailable`. The installed
contract package is also the default test dependency; the root review runner
can explicitly select the staged contract definitions for fake-only verification.

Failures retain outcome, effects, review state, identity, attempts/evidence and
call ID through judges, cross-checks and reflection aggregation. Proposer results
remain lists, with additive `model_result` and `fallback` attributes. Run records
keep these diagnostics in `proposals.jsonl` and alongside serial reflection
fallbacks in `reflections.jsonl`. No diagnostic authorizes replay or widens access.
