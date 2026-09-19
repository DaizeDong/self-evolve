'use strict';
// Retained module name for existing workers; omitted selection inherits llmcall.
const { launch } = require('./_agent_launch');
function launchClaude(extraArgs, prompt) {
  const opts = {};
  for (let i = 0; i < extraArgs.length; i++) {
    const flag = extraArgs[i], value = extraArgs[++i];
    if (!value) return { ok: false, error: 'missing legacy flag value', result: '' };
    if (flag === '--model') opts.model = value;
    else if (flag === '--effort') opts.effort = value;
    else if (['--allowed-tools', '--allowedTools'].includes(flag) && value === 'WebSearch') opts.tools = 'web_search';
    else return { ok: false, error: 'unsupported legacy flag: ' + flag, result: '' };
  }
  return launch(null, opts, prompt);
}
module.exports = { launchClaude };
