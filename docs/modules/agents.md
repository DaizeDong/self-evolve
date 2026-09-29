# Agent calls and independent review

The shared model interface is documented in [runtime.md](runtime.md).
`tools.sie.agents.invoke` performs an agent task through installed llmcall in a
disposable private cwd. Its `ok` and `result` keys remain available, alongside
actual `provider`, normalized `family`, `attempts` and an error when unavailable.
Legacy family/model/tools/effort/timeout arguments are compatibility inputs; they
do not create a second routing policy or prove which model actually answered.

`cross_check` collects per-call results and reports `heterogeneous` only when at
least two successful results come from known, different actual families.
`cross_check_verdicts` uses judge mode for text decisions and returns `agree=None`
with `insufficient_independence` when the providers cannot establish independence.
Alias names alone never count as separate judges.
The full loop halts with an explicit `insufficient_independence` reason when
dual review lacks that evidence; it cannot treat two aliases as a dual rejection.

Reflection and proposal tasks use agent mode. Structured responses are validated
before they become findings or patches. Missing files, malformed JSON, empty
responses, running-state responses and backend errors remain unavailable.
Proposals retain their backend metadata and pass through the deterministic patch
gate. The model does not decide acceptance.

Empty proposal batches keep their list interface and expose `backend_outcomes`
and `diagnostics`. The builtin fallback preserves those outcomes. The loop
records them in its private run directory before evaluating the next stage.
Parallel reflection outcomes are recorded before aggregation or serial fallback,
so a failed backend remains distinguishable from a successful empty reflection.
Evidence write failures stop the caller.

Present `group`, `groups_refused` and `crossed` policy fields survive object
normalization, child serialization and score evidence, including null and false.
They describe routing policy and do not establish model-family independence.

`preflight_dual` inspects local capability without making a live request. Runtime
independence is measured only after results return; it cannot be established by
a CLI version probe. The disabled `workflows/*.js` files are compatibility stops,
not alternative launchers.

Focused coverage lives in `tests/test_agents.py`, `tests/test_llm_contract.py`,
`tests/test_caller_outcomes.py`
and the packaged-child tests. Offline fixtures do not prove live model readiness
or improvement quality. Use frozen candidates, independent reviews and measured
evaluation evidence for those claims.
