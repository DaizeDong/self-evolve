#!/usr/bin/env node
/**
 * codex-judge.js — 禁 browser/playwright 执行点
 *
 * 调用契约:
 *   stdin  : judge prompt (UTF-8 text)
 *   stdout : codex 输出的原始内容（含 JSON span_scores）
 *   exit 0 : 成功; exit 非0 : 失败（invoke_codex_judge 将其视为 available=False）
 *
 * 约束（judge_codex.py 侧也强制拼装这些 flags，双重锁定）:
 *   --no-browser     : 禁止 browser 工具
 *   --no-playwright  : 禁止 playwright 工具
 *   --tools web_search : 仅允许 web_search
 *   --model <id>     : 指定模型（默认 gpt-5.5，当下最强）
 *   --effort <level> : 指定 effort（默认 xhigh）
 *
 * 本文件是 invoke_codex_judge 中 --no-browser/--no-playwright 约束的实际执行点。
 * judge_codex.py 拼装这些 flag 并通过 subprocess 传入；本脚本解析后以相同约束调用 codex CLI。
 */

'use strict';

const { execFileSync } = require('child_process');
const readline = require('readline');

// ── CLI flag 解析 ──────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let model = 'gpt-5.5';
let effort = 'xhigh';
let noBrowser = false;
let noPlaywright = false;
let tools = null;

for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--model' && args[i + 1]) { model = args[++i]; }
  else if (a === '--effort' && args[i + 1]) { effort = args[++i]; }
  else if (a === '--no-browser') { noBrowser = true; }
  else if (a === '--no-playwright') { noPlaywright = true; }
  else if (a === '--tools' && args[i + 1]) { tools = args[++i]; }
  else {
    process.stderr.write(`Unknown flag: ${a}\n`);
    process.exit(2);
  }
}

// 约束校验：本脚本只在禁 browser+playwright、只用 web_search 时运行
if (!noBrowser || !noPlaywright) {
  process.stderr.write('codex-judge.js: --no-browser and --no-playwright are required\n');
  process.exit(2);
}
if (!tools || tools !== 'web_search') {
  process.stderr.write('codex-judge.js: --tools web_search is required\n');
  process.exit(2);
}

// ── 读取 stdin prompt ──────────────────────────────────────────────────────
let prompt = '';
const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', line => { prompt += line + '\n'; });
rl.on('close', () => {
  if (!prompt.trim()) {
    process.stderr.write('codex-judge.js: empty prompt from stdin\n');
    process.exit(1);
  }
  runCodex(prompt.trim());
});

// ── codex CLI 调用 ─────────────────────────────────────────────────────────
function runCodex(promptText) {
  // codex CLI 调用；--no-browser/--no-playwright 已在此层强制检查，
  // codex 本身的 approval-mode=full-auto 确保无交互；
  // 工具约束通过 --allowed-tools 传递（codex CLI 实际支持的 flag 名）。
  const codexArgs = [
    '--model', model,
    '--approval-mode', 'full-auto',
    '--allowed-tools', 'web_search',
    '--quiet',
    promptText,
  ];

  let stdout = '';
  let exitCode = 0;
  try {
    stdout = execFileSync('codex', codexArgs, {
      encoding: 'utf8',
      maxBuffer: 8 * 1024 * 1024,
      timeout: 590000,  // 略低于 invoke_codex_judge 的 600s，让 Python 侧 TimeoutExpired 先触发
    });
  } catch (err) {
    // execFileSync 失败（非0退出/超时/ENOENT）
    process.stderr.write(`codex error: ${err.message}\n`);
    exitCode = err.status || 1;
    if (!exitCode) exitCode = 1;
  }

  if (exitCode !== 0 || !stdout.trim()) {
    process.exit(exitCode || 1);
  }

  process.stdout.write(stdout);
  process.exit(0);
}
