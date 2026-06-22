#!/usr/bin/env node
/**
 * claude-propose-artifact.js — 研究产物提议 subagent（真 Claude 改进 research artifact JSON）
 *
 * claude-propose.js 的 artifact 版：proposer 改的不是 .py 代码，而是 B 档研究产物 JSON，
 * 目标是让产物里的事实断言更可被 SEC/EDGAR 核验（修正错误数值、补可核验锚），
 * 从而提高 verified 锚数 → marginal_gain → 可能 ACCEPT。
 *
 * 调用契约:
 *   stdin  : JSON {
 *              findings:      [<string>...],     // reflect 产出的 findings
 *              artifact_path: "<rel>",           // 目标产物相对路径
 *              artifact:      "<当前 json 文本>"  // 目标产物当前完整内容
 *            }
 *   stdout : JSON { file_rel: "<rel>", new_content: "<完整新产物 json>" }
 *            （无可改/失败 → {} 空对象）
 *   exit 0 : 成功（含空对象）; 非0 : 启动失败
 *
 * 铁律5（holdout 物理隔离）: 本 prompt 给 Claude 的产物文本里**绝不能含任何 expected/verified
 * 真值**。我们在传给 Claude 前会从每个锚里剥掉 expected/verified/observed/marginal_gain
 * 等真值字段，只保留 claim/span/source_url/cik/period/metric 等**非真值线索**。
 * Claude 据此（外加 findings）重建/修正产物，自己重新填 expected——它无法读到 holdout 真值，
 * 也无法读到 visible 锚的既有 expected 来抄答案。
 *
 * 铁律1: proposer 只生成提议；采纳由确定性 harness（verify_anchor + acceptor + selfdeception）裁决。
 * Claude 调用经 _claude_launch（cc 优先, claude fallback）。
 */

'use strict';

const fs = require('fs');
const { launchClaude } = require('./_claude_launch');

// 锚里属于「真值」的字段——铁律5 绝不外泄给 proposer。
const _TRUTH_KEYS = ['expected', 'verified', 'observed', 'verify_reason',
                     'fetched_at', 'marginal_gain', 'anchor_id'];

/** 深拷贝产物，剥掉每个锚的真值字段，返回脱敏后的产物对象（失败返回 null）。 */
function stripTruth(doc) {
  if (!doc || typeof doc !== 'object') return null;
  const out = JSON.parse(JSON.stringify(doc));
  const sections = Array.isArray(out.sections) ? out.sections : [];
  for (const sec of sections) {
    const anchors = Array.isArray(sec && sec.anchors) ? sec.anchors : [];
    for (const a of anchors) {
      if (a && typeof a === 'object') {
        for (const k of _TRUTH_KEYS) { delete a[k]; }
      }
    }
  }
  return out;
}

let raw = '';
try { raw = fs.readFileSync(0, 'utf-8'); } catch (_) { raw = '{}'; }
let input = {};
try { input = JSON.parse(raw || '{}'); } catch (_) { input = {}; }

const findings = Array.isArray(input.findings) ? input.findings : [];
const artifactPath = typeof input.artifact_path === 'string' ? input.artifact_path : '';
const artifactText = typeof input.artifact === 'string' ? input.artifact : '';

if (!artifactPath || !artifactText.trim()) {
  process.stdout.write('{}');
  process.exit(0);
}

// 解析 + 脱敏（剥真值）。解析失败 → 不外泄原文，直接放弃（返回 {}）。
let docObj = null;
try { docObj = JSON.parse(artifactText); } catch (_) { docObj = null; }
const sanitized = stripTruth(docObj);
if (!sanitized) {
  process.stdout.write('{}');
  process.exit(0);
}
const sanitizedText = JSON.stringify(sanitized, null, 2);

const prompt =
  'You are a proposer in a self-improvement loop that refines a RESEARCH ARTIFACT ' +
  '(a JSON report whose factual claims are anchored to SEC/EDGAR filings). ' +
  'Your job: improve the artifact so its factual claims are MORE verifiable against ' +
  'SEC/EDGAR. Concretely: correct numeric claims that look wrong, fix mismatched ' +
  'metric / cik / period fields, and add genuinely verifiable anchors where useful. ' +
  'Each anchor must keep the fields: claim, span, source_url, metric, cik, period, ' +
  'and you MUST supply an "expected" numeric value that you believe is the TRUE figure ' +
  'reported in that filing (USD, full precision, e.g. 391035000000). ' +
  'Do NOT remove anchors and do NOT reduce the anchor count. Keep the same JSON shape ' +
  '({"title":..., "sections":[{"text":..., "anchors":[...]}, ...]}). ' +
  'You are NOT given any ground-truth "expected"/"verified" values — infer the correct ' +
  'figures from your knowledge of these issuers\' filings. ' +
  'Output the COMPLETE new artifact JSON (not a diff). ' +
  'Return ONLY JSON: {"file_rel":"' + artifactPath + '","new_content":"<full new artifact json as a string>"}.' +
  ' If no useful improvement is possible, return {}.\n\n' +
  'FINDINGS:\n' + (findings.length ? findings.map(f => '- ' + f).join('\n') : '(none)') +
  '\n\nCURRENT ARTIFACT (truth values stripped):\n' + sanitizedText + '\n';

const out = launchClaude(['--model', 'sonnet'], prompt);
if (!out.ok) { process.stdout.write('{}'); process.exit(0); }

let result = {};
try {
  const obj = JSON.parse(out.result.slice(out.result.indexOf('{'), out.result.lastIndexOf('}') + 1));
  if (obj && obj.file_rel === artifactPath && typeof obj.new_content === 'string') {
    // 校验 new_content 是合法 JSON 且锚数不减（结构门，proposer 不能交垃圾）。
    let nc = null;
    try { nc = JSON.parse(obj.new_content); } catch (_) { nc = null; }
    if (nc && Array.isArray(nc.sections)) {
      const countAnchors = (d) =>
        (d.sections || []).reduce(
          (n, s) => n + (Array.isArray(s.anchors) ? s.anchors.length : 0), 0);
      if (countAnchors(nc) >= countAnchors(docObj)) {
        result = { file_rel: artifactPath, new_content: obj.new_content };
      }
    }
  }
} catch (_) { result = {}; }

process.stdout.write(JSON.stringify(result));
process.exit(0);
