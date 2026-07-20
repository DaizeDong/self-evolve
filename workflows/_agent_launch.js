'use strict';
/**
 * _agent_launch.js — 统一 agent 启动器（任意阶段、任意家族）
 *
 * 把"调一个 agent"抽象成 launch(family, opts, prompt)，使 codex 与 claude 成为**可在
 * 任何阶段互换/组合的异质 agent 选项**，而非绑死某个阶段的组件。异质交叉校验由此可贯穿
 * reflect / propose / review / evaluate / judge 全流程。
 *
 *   family 'claude' | 'cc'  → 经 _claude_launch（cc 优先, claude fallback, -p json, stdin）
 *   family 'codex'          → codex exec -s read-only（禁写盘/逃逸; -o 取最终消息; web_search）
 *
 * 返回 { ok: bool, result: string }。两家族失败均 graceful（ok:false），绝不抛。
 */

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { launchClaude } = require('./_claude_launch');

const TIMEOUT_MS = 590000;

function _launchCodex(opts, prompt) {
  // 默认当下最强（与 memory 一致: codex 永远用最强模型）。2026-07 = gpt-5.6-sol + max。
  const model = opts.model || 'gpt-5.6-sol';
  const effort = opts.effort || 'max';
  const outFile = path.join(os.tmpdir(), `sie-agent-codex-${process.pid}-${Date.now()}.txt`);
  // read-only 沙箱: codex 不能写盘/逃逸 shell（任意阶段调 codex 都只读, 防副作用）。
  // -o 取最终消息避开 header/MCP 噪声。prompt 走 stdin → shell:true 下无注入面。
  const codexArgs = [
    'exec', '-m', model, '-s', 'read-only',
    '--skip-git-repo-check', '--color', 'never',
    '-c', `model_reasoning_effort=${effort}`,
    '-o', outFile,
  ];
  const r = spawnSync('codex', codexArgs, {
    input: prompt, encoding: 'utf8', shell: true,
    maxBuffer: 16 * 1024 * 1024, timeout: TIMEOUT_MS,
  });
  let out = '';
  try { out = fs.readFileSync(outFile, 'utf8'); } catch (_) {}
  try { fs.unlinkSync(outFile); } catch (_) {}
  if (r.error || r.status !== 0 || !out.trim()) {
    process.stderr.write(`codex unavailable: status=${r.status} ${(r.stderr || '').slice(-200)}\n`);
    return { ok: false };
  }
  return { ok: true, result: out };
}

function _launchClaudeFamily(opts, prompt) {
  const extra = [];
  if (opts.tools === 'web_search') extra.push('--allowed-tools', 'WebSearch');
  extra.push('--model', opts.model || 'sonnet');
  const out = launchClaude(extra, prompt);
  return out.ok ? { ok: true, result: out.result } : { ok: false };
}

/**
 * @param {string} family 'claude' | 'cc' | 'codex'
 * @param {object} opts   { model?, tools?('web_search'), effort? }
 * @param {string} prompt
 * @returns {{ok:boolean, result?:string}}
 */
function launch(family, opts, prompt) {
  opts = opts || {};
  if (!prompt || !prompt.trim()) return { ok: false };
  if (family === 'codex') return _launchCodex(opts, prompt);
  // 默认/claude/cc 走 claude 家族
  return _launchClaudeFamily(opts, prompt);
}

module.exports = { launch };
