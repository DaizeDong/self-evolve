#!/usr/bin/env node
/**
 * review-fanout.js — 评审 fanout subagent
 *
 * 调用契约:
 *   stdin  : JSON { proposal: <object>, history: [...] }
 *   stdout : JSON { reviewer: <idx>, verdict: "accept"|"reject"|"abstain", notes: [...] }
 *   exit 0 : 成功; exit 非0 : 失败（caller 视为 reviewer 弃权）
 *
 * 设计: 并行起评审 subagent，各自独立给出 verdict；
 * 编排层（review-fanout 调用方）汇总 N 条 verdict（多数表决或加权）。
 * 此桩版本输出 abstain，保证管线可端到端跑通；
 * 编排层可替换为真实 Claude subagent 调用而不改调用接口。
 */

'use strict';

const fs = require('fs');

const args = process.argv.slice(2);

// Parse --run <dir> and --idx <n>
let runDir = '';
let idx = 0;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--run' && args[i + 1]) { runDir = args[++i]; }
  else if (args[i] === '--idx' && args[i + 1]) { idx = Number(args[++i]); }
}

// Read proposal + history from stdin
let raw = '';
try {
  raw = fs.readFileSync(0, 'utf-8');
} catch (_) {
  raw = '{}';
}

const input = JSON.parse(raw || '{}');
void input;          // read-only; no side effects

// Stub: real implementation injects a Claude subagent call here.
// Output contract: { reviewer: <idx>, verdict: "accept"|"reject"|"abstain", notes: [<string>, ...] }
const out = { reviewer: idx, verdict: 'abstain', notes: [] };

process.stdout.write(JSON.stringify(out));
process.exit(0);
