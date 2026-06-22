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

const { spawnSync } = require('child_process');
const readline = require('readline');
const fs = require('fs');
const os = require('os');
const path = require('path');

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
  // 真实非交互接口: `codex exec`。
  // 安全边界: -s read-only(沙箱只读,judge 不能写盘/逃逸 shell) 是 --no-browser/
  //   --no-playwright 约束的实际落地(已在上层校验过这些 flag 必须传)。
  // -o <FILE>: 只取 codex 的最终消息(避开 header/MCP 噪声)，比解析全 stdout 稳。
  // effort 经 -c model_reasoning_effort 注入(无 --strict-config,未知键被容忍)。
  const outFile = path.join(os.tmpdir(),
    `sie-codex-judge-${process.pid}-${Date.now()}.txt`);
  // prompt 走 stdin(不进 args) → shell:true 下无注入面; codex exec 无 prompt arg 时读 stdin。
  // -c 值不加引号: TOML 解析失败回退字面量(避免跨平台 shell 引号问题)。
  // shell:true: Windows 解析 npm 全局 codex.cmd(execFile 裸名找不到 .cmd → ENOENT)。
  const codexArgs = [
    'exec',
    '-m', model,
    '-s', 'read-only',
    '--skip-git-repo-check',
    '--color', 'never',
    '-c', `model_reasoning_effort=${effort}`,
    '-o', outFile,
  ];

  let exitCode = 0;
  const r = spawnSync('codex', codexArgs, {
    input: promptText,
    encoding: 'utf8',
    shell: true,
    maxBuffer: 8 * 1024 * 1024,
    timeout: 590000,  // 略低于 invoke_codex_judge 的 600s，让 Python 侧先 TimeoutExpired
  });
  if (r.error) {
    process.stderr.write(`codex error: ${r.error.message}\n`);
    exitCode = 1;
  } else if (r.status !== 0) {
    process.stderr.write(`codex exit ${r.status}: ${(r.stderr || '').slice(-300)}\n`);
    exitCode = r.status || 1;
  }

  let lastMessage = '';
  try {
    lastMessage = fs.readFileSync(outFile, 'utf8');
  } catch (_) { /* 文件缺失=失败 */ }
  try { fs.unlinkSync(outFile); } catch (_) {}

  if (exitCode !== 0 || !lastMessage.trim()) {
    process.exit(exitCode || 1);
  }

  process.stdout.write(lastMessage);  // 含 judge 的 span_scores JSON, 供 _parse_span_scores 提取
  process.exit(0);
}
