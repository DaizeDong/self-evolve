#!/usr/bin/env node
/**
 * claude-propose.js — 提议 subagent（真 Claude 生成代码改动）
 *
 * 调用契约:
 *   stdin  : JSON { findings: [<string>...], files: { "<rel>": "<content>", ... } }
 *   stdout : JSON { file_rel: "<rel>", new_content: "<full new file content>" }
 *            （无可改/失败 → {} 空对象）
 *   exit 0 : 成功（含空对象）; 非0 : 启动失败
 *
 * 铁律1: proposer 只生成提议；采纳由确定性 harness 裁决。
 * 生成的 new_content 后续经 apply_patch 的 import 白名单 + AST 危险门 + 沙箱边界
 * (+ 自举时 IMMUTABLE 硬拒) 全部门控；proposer 无法绕过这些门。
 * Claude 调用经 _claude_launch（cc 优先, claude fallback）。
 */

'use strict';

const fs = require('fs');
const { launchClaude } = require('./_claude_launch');

let raw = '';
try { raw = fs.readFileSync(0, 'utf-8'); } catch (_) { raw = '{}'; }
let input = {};
try { input = JSON.parse(raw || '{}'); } catch (_) { input = {}; }

const findings = Array.isArray(input.findings) ? input.findings : [];
const files = (input.files && typeof input.files === 'object') ? input.files : {};
const fileRels = Object.keys(files);

if (!fileRels.length) {
  process.stdout.write('{}');
  process.exit(0);
}

let fileBlock = '';
for (const rel of fileRels) {
  fileBlock += `\n--- FILE: ${rel} ---\n${files[rel]}\n`;
}

const prompt =
  'You are a proposer in a self-improvement loop. Given the findings and the CURRENT ' +
  'source files below, produce ONE concrete, minimal file change that best addresses ' +
  'the findings (fix the bug / make failing behavior pass). Choose the single most ' +
  'impactful file. Output the COMPLETE new content of that one file (not a diff). ' +
  'Do not add dangerous imports or I/O. ' +
  'Return ONLY JSON: {"file_rel":"<one of the given paths>","new_content":"<full new file content>"}. ' +
  'If no useful change is possible, return {}.\n\n' +
  'FINDINGS:\n' + (findings.length ? findings.map(f => '- ' + f).join('\n') : '(none)') +
  '\n\nCURRENT FILES:\n' + fileBlock + '\n';

const out = launchClaude(['--model', 'sonnet'], prompt);
if (!out.ok) { process.stdout.write('{}'); process.exit(0); }

let result = {};
try {
  const obj = JSON.parse(out.result.slice(out.result.indexOf('{'), out.result.lastIndexOf('}') + 1));
  if (obj && typeof obj.file_rel === 'string' && typeof obj.new_content === 'string'
      && fileRels.includes(obj.file_rel)) {   // 只允许改给定文件之一（不许凭空新建路径）
    result = { file_rel: obj.file_rel, new_content: obj.new_content };
  }
} catch (_) { result = {}; }

process.stdout.write(JSON.stringify(result));
process.exit(0);
