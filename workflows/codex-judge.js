#!/usr/bin/env node
'use strict';
const { launch } = require('./_agent_launch');
const fs = require('fs');
const args = process.argv.slice(2), opts = {};
let noBrowser = false, noPlaywright = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--no-browser') noBrowser = true;
  else if (args[i] === '--no-playwright') noPlaywright = true;
  else if (['--model','--effort','--tools'].includes(args[i]) && args[i+1]) opts[args[i++].slice(2)] = args[i];
  else { process.stderr.write('unsupported judge flag\n'); process.exit(2); }
}
if (opts.tools !== 'web_search' || ('codex' === 'codex' && (!noBrowser || !noPlaywright))) {
  process.stderr.write('judge requires WebSearch only; browser/playwright forbidden\n'); process.exit(2);
}
const out = launch('codex', opts, fs.readFileSync(0, 'utf8'));
if (!out.ok) { process.stderr.write(JSON.stringify(out) + '\n'); process.exit(1); }
process.stdout.write(out.result);
