'use strict';
// Legacy JS worker transport: one structured llmcall request, never a provider CLI.
const { spawnSync } = require('child_process');
function launch(family, opts, prompt) {
  opts = opts || {};
  const fail = (error, details = {}) => ({ ...details, ok: false, result: '', error });
  if (!prompt || !prompt.trim()) return fail('empty prompt');
  if (family && !['claude', 'cc', 'codex'].includes(family)) return fail('unsupported family');
  if (opts.tools && opts.tools !== 'web_search') return fail('unsupported tool constraint');
  const request = {
    prompt, mode: 'agent', timeout: 590,
    selection: opts.model ? { intent: 'exact', model: opts.model } : { intent: 'inherit' },
    requirements: { access: 'read_only', tool_network: opts.tools ? 'required' : 'forbidden',
      required_tools: opts.tools ? ['WebSearch'] : [],
      tool_allowlist: opts.tools ? ['WebSearch'] : [], replay: 'never_after_start' }
  };
  if (family) request.selection.family = family === 'cc' ? 'claude' : family;
  for (const key of ['chain', 'avoid', 'cwd', 'env']) {
    if (opts[key] !== undefined) request[key] = opts[key];
  }
  if (opts.effort) request.effort = opts.effort;
  const child = spawnSync(process.env.SIE_PYTHON || 'python',
    ['-P', '-m', 'llmcall', '--request-json', '--result-json'], {
      input: JSON.stringify(request), encoding: 'utf8', shell: false,
      maxBuffer: 16 * 1024 * 1024
    }); // llmcall owns the deadline and descendant cleanup
  let result;
  const transport = { outcome: 'execution_uncertain', effects: 'possible', execution_started: null,
    review_state: 'unavailable', call_id: null, stderr: String(child.stderr || '').slice(-2000) };
  try { result = JSON.parse(child.stdout); } catch (_) { return fail('invalid Result JSON; no retry', transport); }
  if (!result || typeof result !== 'object' || Array.isArray(result) || typeof result.text !== 'string')
    return fail('invalid Result shape; no retry', transport);
  const details = { ...result };
  delete details.text;
  delete details.data;
  if (child.error || child.status !== 0 || !result.provider || result.error || !result.text.trim()
      || (result.outcome && result.outcome !== 'success'))
    return fail(result.error || 'unsuccessful result; no retry', { ...details, stderr: transport.stderr });
  const expected = family === 'cc' ? 'claude' : family;
  if (expected && (result.model_family !== expected || result.model_source !== 'provider_reported'))
    return fail('requested model family unverified', { ...details, outcome: 'model_unverified' });
  return { ...details, ok: true, result: result.text };
}
module.exports = { launch };
