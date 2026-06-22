#!/usr/bin/env node
/**
 * reflect-fanout.js — 单个独立 MARS 反思 subagent
 *
 * 调用契约:
 *   stdin  : JSON { history: [...] }   (history trace, read-only)
 *   stdout : JSON { reflector: <idx>, findings: [...] }
 *   exit 0 : 成功; exit 非0 : 失败（run_reflections_parallel 返回空 findings）
 *
 * 铁律2: 只读历史 trace，绝不写 trace，绝不读其他反思草稿。
 * 独立性: 每个 reflector 进程互不通信，输出前对方进程不可见。
 * 此桩版本输出空 findings，保证编排管线可端到端跑通；
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

// Read history from stdin (read-only trace — Iron Law 2)
let raw = '';
try {
  raw = fs.readFileSync(0, 'utf-8');
} catch (_) {
  raw = '{}';
}

const input = JSON.parse(raw || '{}');
void input;          // history consumed read-only; no trace writes

// Stub: real implementation injects a Claude subagent call here.
// Output contract: { reflector: <idx>, findings: [<string>, ...] }
const out = { reflector: idx, findings: [] };

process.stdout.write(JSON.stringify(out));
process.exit(0);
