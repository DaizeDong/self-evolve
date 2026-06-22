#!/usr/bin/env node
/**
 * review-fanout.js — 评审 fanout subagent（真 Claude）
 *
 * 调用契约:
 *   args   : --run <dir> --idx <n>
 *   stdin  : JSON { proposal: <object>, history: [...] }
 *   stdout : JSON { reviewer: <idx>, verdict: "accept"|"reject"|"abstain", notes: [...] }
 *   exit 0 : 成功; exit 非0 : 失败（caller 视为 reviewer 弃权）
 *
 * 并行起评审 subagent，各自独立给 verdict；编排层汇总（多数表决）。
 * 注: 评审仅作辅助参考；采纳/拒绝的最终裁决仍由确定性 acceptor 做（铁律1）。
 * Claude 调用经 _claude_launch（cc 优先, claude fallback）。
 */

'use strict';

const fs = require('fs');
const { launchClaude } = require('./_claude_launch');

const args = process.argv.slice(2);
let idx = 0;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--run' && args[i + 1]) { i++; }
  else if (args[i] === '--idx' && args[i + 1]) { idx = Number(args[++i]); }
}

let raw = '';
try { raw = fs.readFileSync(0, 'utf-8'); } catch (_) { raw = '{}'; }
let input = {};
try { input = JSON.parse(raw || '{}'); } catch (_) { input = {}; }

const proposal = input.proposal || {};

const prompt =
  'You are reviewer #' + idx + ' giving an independent verdict on a proposed change ' +
  'in a self-improvement loop. Judge whether the change is a genuine improvement and ' +
  'not a regression or reward-hack. Your verdict is advisory; a deterministic acceptor ' +
  'makes the final call. ' +
  'Return ONLY JSON: {"verdict":"accept"|"reject"|"abstain","notes":["<note>", ...]}.\n\n' +
  'PROPOSAL:\n' + JSON.stringify(proposal, null, 2) + '\n';

const out = launchClaude(['--allowed-tools', 'WebSearch', '--model', 'sonnet'], prompt);
if (!out.ok) {
  process.stdout.write(JSON.stringify({ reviewer: idx, verdict: 'abstain', notes: [] }));
  process.exit(0);  // 降级: 弃权, 不拖垮 fanout
}

let verdict = 'abstain';
let notes = [];
try {
  const obj = JSON.parse(out.result.slice(out.result.indexOf('{'), out.result.lastIndexOf('}') + 1));
  if (['accept', 'reject', 'abstain'].includes(obj.verdict)) { verdict = obj.verdict; }
  if (Array.isArray(obj.notes)) { notes = obj.notes.filter(n => typeof n === 'string').slice(0, 5); }
} catch (_) { /* 降级保持 abstain */ }

process.stdout.write(JSON.stringify({ reviewer: idx, verdict, notes }));
process.exit(0);
