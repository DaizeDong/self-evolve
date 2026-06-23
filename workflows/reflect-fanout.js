#!/usr/bin/env node
/**
 * reflect-fanout.js — 单个独立 MARS 反思 subagent（真 Claude）
 *
 * 调用契约:
 *   args   : --run <dir> --idx <n>
 *   stdin  : JSON { history: [...] }   (history trace, read-only — 铁律2)
 *   stdout : JSON { reflector: <idx>, findings: [<string>, ...] }
 *   exit 0 : 成功; exit 非0 : 失败（run_reflections_parallel 返回空 findings）
 *
 * 铁律2: 只读历史 trace，绝不写 trace；独立性: reflector 间互不通信。
 * agent 调用经统一 _agent_launch（--family claude|codex → 异质 MARS）。
 */

'use strict';

const fs = require('fs');
const { launch } = require('./_agent_launch');

const args = process.argv.slice(2);
let idx = 0;
let family = 'claude';
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--run' && args[i + 1]) { i++; }          // run_dir: 仅契约占位, 不写
  else if (args[i] === '--idx' && args[i + 1]) { idx = Number(args[++i]); }
  else if (args[i] === '--family' && args[i + 1]) { family = args[++i]; }
}

let raw = '';
try { raw = fs.readFileSync(0, 'utf-8'); } catch (_) { raw = '{}'; }
let history = [];
try { history = (JSON.parse(raw || '{}').history) || []; } catch (_) { history = []; }

// 空历史(首轮) → 无可反思的失败信号；输出空 findings（保持管线可跑通）。
if (!history.length) {
  process.stdout.write(JSON.stringify({ reflector: idx, findings: [], family }));
  process.exit(0);
}

const prompt =
  'You are reflector #' + idx + ' in an independent multi-agent reflection (MARS) ' +
  'over a self-improvement run history. The history is READ-ONLY evidence; you must ' +
  'NOT propose code yet — only diagnose. From the history below, identify concrete, ' +
  'distinct improvement findings (what failed and the direction to fix it). ' +
  'Be specific and reference the actual failures. ' +
  'Return ONLY JSON: {"findings":["<finding 1>","<finding 2>", ...]} (0-5 findings).\n\n' +
  'RUN HISTORY (read-only):\n' + JSON.stringify(history, null, 2) + '\n';

const out = launch(family, { tools: 'web_search', model: family === 'codex' ? undefined : 'sonnet' }, prompt);
if (!out.ok) {
  process.stdout.write(JSON.stringify({ reflector: idx, findings: [], family }));
  process.exit(0);  // 降级: 空 findings, 不让单个 reflector 失败拖垮 fanout
}

let findings = [];
try {
  const obj = JSON.parse(out.result.slice(out.result.indexOf('{'), out.result.lastIndexOf('}') + 1));
  if (Array.isArray(obj.findings)) {
    findings = obj.findings.filter(f => typeof f === 'string' && f.trim()).slice(0, 5);
  }
} catch (_) { findings = []; }

process.stdout.write(JSON.stringify({ reflector: idx, findings, family }));
process.exit(0);
