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

// Every failure below prints WHY to stderr before emitting {}. Without this the four distinct
// failures (no input, launch failed, output was not JSON, output did not match the contract) reach
// the loop as one identical empty object, and the loop records one identical STATIC_REJECT. A
// calibration run lost 6 of its 7 rounds this way and its own log could not say which failure it
// was even once. stdout stays exactly as contracted; only stderr gains content.
function giveUp(why, raw) {
  process.stderr.write('claude-propose: ' + why + '\n');
  if (raw) process.stderr.write('claude-propose: raw agent output (first 600): '
                               + String(raw).slice(0, 600) + '\n');
  process.stdout.write('{}');
  process.exit(0);
}

if (!fileRels.length) {
  giveUp('no source files were supplied, so there was nothing to propose against');
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

// No model pin. The pinned 'sonnet' here was invisible from every log the loop keeps, and it is
// the proposer, the one step whose quality decides whether a round produces anything at all.
// _claude_launch resolves the session default instead.
const out = launchClaude([], prompt);
if (!out.ok) giveUp('the agent launch failed: ' + (out.error || 'no reason reported'), out.result);

const first = out.result.indexOf('{'), last = out.result.lastIndexOf('}');
if (first < 0 || last <= first) {
  giveUp('the agent returned no JSON object at all (' + out.result.length + ' chars). For a large '
         + 'target this usually means it wrote the file content somewhere instead of returning it '
         + 'inline; the contract only reads stdout.', out.result);
}

let obj = null;
try {
  obj = JSON.parse(out.result.slice(first, last + 1));
} catch (e) {
  giveUp('the agent output looked like JSON but did not parse: ' + e.message, out.result);
}

if (!obj || typeof obj !== 'object') giveUp('the agent returned JSON that is not an object', out.result);
if (Object.keys(obj).length === 0) {
  giveUp('the agent explicitly returned {}, meaning it judged that no useful change was possible',
         out.result);
}
if (typeof obj.file_rel !== 'string' || typeof obj.new_content !== 'string') {
  giveUp('the agent returned an object without both file_rel and new_content as strings (keys: '
         + JSON.stringify(Object.keys(obj)) + ')', out.result);
}
if (!fileRels.includes(obj.file_rel)) {
  // Only the given files may be edited: no inventing new paths.
  giveUp('the agent named ' + JSON.stringify(obj.file_rel) + ', which was not one of the '
         + fileRels.length + ' files it was given');
}

process.stdout.write(JSON.stringify({ file_rel: obj.file_rel, new_content: obj.new_content }));
process.exit(0);
