'use strict';
/**
 * _claude_launch.js — 共享 Claude 启动器（cc 优先, claude fallback）
 *
 * 所有调 Claude 的接缝（claude-judge / reflect-fanout / review-fanout /
 * claude-propose）统一经此，保证一致的:
 *   - cc 优先（用户封装的 claude, 走 split-billing 网关）, claude 作 fallback;
 *   - fallback 仅在 cc **启动失败** 时触发(ENOENT / cmd 9009 / sh 127),
 *     cc 已启动但 agent 报错(status!=0)不回退(避免重复计费, claude 多半同样失败);
 *   - prompt 走 stdin（shell:true 解析 .cmd, 但 prompt 不进命令行 → 无注入面）;
 *   - --output-format json → 取 .result。
 *
 * 导出 launchClaude(extraArgs, promptText) -> { ok: bool, result: string }。
 */

const { spawnSync } = require('child_process');

const BASE_ARGS = ['-p', '--output-format', 'json', '--dangerously-skip-permissions'];
const TIMEOUT_MS = 590000;  // 略低于 Python 侧 600s，让上层 TimeoutExpired 先触发

function _spawn(bin, args, promptText) {
  return spawnSync(bin, args, {
    input: promptText,
    encoding: 'utf8',
    shell: true,            // Windows 解析 cc.cmd / claude(.cmd)；prompt 走 stdin 故安全
    maxBuffer: 16 * 1024 * 1024,
    timeout: TIMEOUT_MS,
  });
}

function _isLaunchFailure(r) {
  // ENOENT(spawn error) / Windows cmd "not recognized"(9009) / sh "not found"(127)
  return !!r.error || r.status === 9009 || r.status === 127;
}

/**
 * @param {string[]} extraArgs  附加 claude flag（如 --model, --allowed-tools, --append-system-prompt）
 * @param {string}   promptText prompt（经 stdin 传入）
 * @returns {{ok: boolean, result?: string}}
 */
function launchClaude(extraArgs, promptText) {
  const args = BASE_ARGS.concat(extraArgs || []);
  let r = _spawn('cc', args, promptText);
  if (_isLaunchFailure(r)) {
    process.stderr.write('launch: cc unavailable, falling back to claude\n');
    r = _spawn('claude', args, promptText);
  }
  if (r.error || r.status !== 0 || !r.stdout || !r.stdout.trim()) {
    process.stderr.write(`launch error: status=${r.status} ${(r.stderr || '').slice(-200)}\n`);
    return { ok: false };
  }
  // claude --output-format json: {"type":"result","result":"...","is_error":bool,...}
  try {
    const obj = JSON.parse(r.stdout);
    if (obj && obj.is_error) return { ok: false };
    if (obj && typeof obj.result === 'string' && obj.result.trim()) {
      return { ok: true, result: obj.result };
    }
  } catch (_) {
    // 非预期 JSON → 退用原始 stdout（下游可再提取 JSON 块）
    return { ok: true, result: r.stdout };
  }
  return { ok: false };
}

module.exports = { launchClaude };
