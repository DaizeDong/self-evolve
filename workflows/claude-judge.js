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
 * 安全: --bare 跳过 CLAUDE.md/memory/hooks（judge 调用干净无污染）;
 *       --allowed-tools 限定只读联网工具（judge 不写盘）;
 *       --dangerously-skip-permissions 用于无交互（叠加 harness 既有 proxy/沙箱）。
 */

'use strict';

const { execFileSync } = require('child_process');

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

// 约束: 只在限定 web_search 工具时运行（与 codex-judge.js 对称）
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
  runClaude(prompt.trim());
});

// ── claude CLI 调用 ────────────────────────────────────────────────────────
function runClaude(promptText) {
  // 注: 不用 --bare —— bare 模式禁用 OAuth/keychain(只认 ANTHROPIC_API_KEY),
  // 订阅/OAuth 登录会失败。改用默认认证 + 受限工具保证 judge 干净只读。
  const claudeArgs = [
    '-p',
    '--output-format', 'json',
    '--dangerously-skip-permissions',
    '--allowed-tools', 'WebSearch',
    '--model', model,
    '--', promptText,
  ];

  let stdout = '';
  let exitCode = 0;
  try {
    stdout = execFileSync('claude', claudeArgs, {
      encoding: 'utf8',
      maxBuffer: 8 * 1024 * 1024,
      timeout: 590000,  // 略低于 invoke_claude_judge 的 600s，让 Python 侧先 TimeoutExpired
    });
  } catch (err) {
    process.stderr.write(`claude error: ${err.message}\n`);
    exitCode = err.status || 1;
    if (!exitCode) exitCode = 1;
  }

  if (exitCode !== 0 || !stdout.trim()) {
    process.exit(exitCode || 1);
  }

  // claude --output-format json: {"type":"result","result":"<响应>",...} → 取 .result
  let result = '';
  try {
    const obj = JSON.parse(stdout);
    if (obj && obj.is_error) { process.exit(1); }
    result = (obj && typeof obj.result === 'string') ? obj.result : '';
  } catch (_) {
    // 非预期 JSON → 退而用原始 stdout（下游 _parse_span_scores 仍可提取 JSON 块）
    result = stdout;
  }

  if (!result.trim()) { process.exit(1); }

  process.stdout.write(result);  // 含 judge 的 span_scores JSON
  process.exit(0);
}
