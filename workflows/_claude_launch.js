#!/usr/bin/env node
'use strict';
// Obsolete provider launcher. Python wrappers use installed llmcall policy.
const message = 'This launcher is disabled. Use tools.sie Python APIs through llmcall.';
if (require.main === module) {
  process.stderr.write(message + '\n');
  process.exitCode = 2;
}
function disabled() { return { ok: false, result: '', error: message }; }
module.exports = { launch: disabled, launchClaude: disabled };
