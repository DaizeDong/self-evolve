#!/usr/bin/env node
/**
 * claude-judge.js — Claude judge 执行点（异质 judge 的 Claude 家族）
 *
 * 调用契约（镜像 codex-judge.js）:
 *   stdin  : judge prompt (UTF-8 text, 无真值 — 铁律5)
 *   stdout : Claude 的响应文本（含 JSON span_scores，供 _parse_span_scores 提取）
 *   exit 0 : 成功; exit 非0 : 失败（invoke_claude_judge 视为 available=False）
 *
 * flags（judge_claude.py 传入）:
 *   --tools web_search : 仅允许 web_search（映射到 claude --allowed-tools WebSearch）
 *   --model <id>       : 可选, 默认 sonnet（judge 可信且经济; 可按 §12 校准上调）
 *
 * Claude 调用经 _claude_launch（cc 优先, claude fallback；prompt 走 stdin）。
 * judge 只读联网工具 WebSearch（不写盘）, 叠加 harness 既有 proxy/沙箱。
 */

'use strict';

const { launchClaude } = require('./_claude_launch');

// ── CLI flag 解析 ──────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let model = 'sonnet';
let tools = null;

for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--model' && args[i + 1]) { model = args[++i]; }
  else if (a === '--tools' && args[i + 1]) { tools = args[++i]; }
  else {
    process.stderr.write(`Unknown flag: ${a}\n`);
    process.exit(2);
  }
}

if (!tools || tools !== 'web_search') {
  process.stderr.write('claude-judge.js: --tools web_search is required\n');
  process.exit(2);
}

// ── 读取 stdin prompt ──────────────────────────────────────────────────────
let prompt = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { prompt += d; });
process.stdin.on('end', () => {
  if (!prompt.trim()) {
    process.stderr.write('claude-judge.js: empty prompt from stdin\n');
    process.exit(1);
  }
  const out = launchClaude(
    ['--allowed-tools', 'WebSearch', '--model', model],
    prompt.trim(),
  );
  if (!out.ok || !out.result.trim()) { process.exit(1); }
  process.stdout.write(out.result);  // 含 judge 的 span_scores JSON
  process.exit(0);
});
