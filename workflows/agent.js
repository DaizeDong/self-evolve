#!/usr/bin/env node
/**
 * agent.js — 通用 agent 调用入口（任意家族 × 任意角色）
 *
 * 把"在某阶段调一个 agent"统一成一条命令，使 codex 成为**任何阶段**的可选异质 agent，
 * 而不是绑死 C 档判官的组件。reflect / propose / review / verify / judge 都可经此调任一家族。
 *
 *   stdin  : prompt (UTF-8)
 *   stdout : agent 响应文本（原样；上层按角色解析 JSON 等）
 *   exit 0 : 成功; 非0 : 失败（调用方按 unavailable 处理）
 *
 * flags:
 *   --family <claude|cc|codex>  必填，选 agent 家族
 *   --role   <reflect|propose|review|verify|judge|...>  可选，信息性（透传给日志）
 *   --model  <id>               可选，覆盖默认模型
 *   --tools  web_search         可选，仅允许联网检索（claude→WebSearch；codex 默认有）
 *   --effort <low|...|xhigh>    可选，codex reasoning effort
 */
'use strict';

const { launch } = require('./_agent_launch');

const args = process.argv.slice(2);
const opts = {};
let family = null;
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  if (a === '--family' && args[i + 1]) family = args[++i];
  else if (a === '--model' && args[i + 1]) opts.model = args[++i];
  else if (a === '--tools' && args[i + 1]) opts.tools = args[++i];
  else if (a === '--effort' && args[i + 1]) opts.effort = args[++i];
  else if (a === '--role' && args[i + 1]) opts.role = args[++i];  // informational
  else { process.stderr.write(`Unknown flag: ${a}\n`); process.exit(2); }
}
if (!family) { process.stderr.write('agent.js: --family required (claude|cc|codex)\n'); process.exit(2); }

let prompt = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { prompt += d; });
process.stdin.on('end', () => {
  const out = launch(family, opts, prompt.trim());
  if (!out.ok || !out.result.trim()) process.exit(1);
  process.stdout.write(out.result);
  process.exit(0);
});
