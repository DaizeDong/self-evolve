# Design Philosophy

## English

An improving score is useful only when the comparison still measures the intended
behavior. A candidate that selects easier tasks, removes failed obligations, or
changes its own grader can produce an upward curve without a corresponding gain.
Open-ended generation makes this problem harder: fluent judgment can be available
even when independent truth is absent.

self-evolve keeps the improvement method stable while choosing observable
evidence for each target. A pairs executed tests; B pairs independently verified
facts; C requires supplied regression and consistency measurements alongside judge
evidence. These are evidence sources, not levels of intelligence. The loop has no
C measurement producer and refuses A+B execution. This conservative boundary
leaves some useful changes unobservable, including changes to an already-green
A suite. Such cases need better measurements or review, not an invented gain.

## Fix the comparison before implementation

Choose the goal, allowed edits, evaluation policy, and holdout before changing a
candidate. Keep parent obligations in the comparison even if the candidate removes
them. Freeze selfboot decision code from the base revision so the candidate cannot
become its own grader. Changing the goal requires a new, explicit evaluation
contract rather than rewriting the rules of an existing run.

This first freeze protects the meaning of the experiment. A second freeze happens
before review: finish implementation, documentation, and any authorized version
updates, then identify the exact candidate snapshot. Review and validation must
describe that snapshot. These are separate obligations; completing docs after
implementation does not permit changing the earlier evaluator or holdout.

## Models offer hypotheses; gates need evidence

Reflection and proposals help find possible improvements. Deterministic code
checks inputs, compares measurements, and handles acceptance or review. Retain
actual returned providers when establishing judge independence. Agreement between
judges is not itself a measured gain, and a structurally valid reflection is not
proof that its factual claims were checked.

The tradeoff is deliberate: strict comparison may reject or pause a plausible
change. Lowering a threshold or treating an unavailable measurement as a pass
would hide that uncertainty. Statistical controls also have a defined scope:
passing tasks do not prove behavior outside the measured population, and the
current acceptor has no established run-wide error bound across fresh proposals.
See the [evaluation contract](reference/evaluation.md) and
[statistical assumptions](reference/acceptor_math.md).

## Keep decisions recoverable and authority explicit

Preserve failures, unavailable observations, rejection reasons, provider metadata,
and exact accepted snapshots. A digest identifies content but cannot restore it.
Complete snapshots and append-only events consume space; compact retention is
safe only when the remaining bytes and dependencies still support recovery.
The [storage contract](DATA.md) distinguishes current recovery requirements from
historical evidence and disposable execution copies.

Real run evidence belongs in a verified PRIVATE Git companion so it can retain
history without entering the public tool. Missing private proof blocks writes.
Worktrees, prompt filtering, and frozen Python code support specific boundaries;
they do not establish an operating-system sandbox. ACCEPT archives a candidate.
Installation, merge, publication, and outbound actions follow the caller's
authorization. The [maintenance handoff](reference/maintenance.md) records which
candidate was reviewed, which checks actually ran, and which actions remain.

## 中文

分数提高只有在比较仍然衡量原定行为时才有意义。候选可以选更容易的题、删掉失败义务，
也可以改自己的评分器；这些操作能让曲线上升，却不一定带来能力提升。开放式生成更难判断：
没有独立真值，也可能得到流畅的评语。

self-evolve 保持改进方法一致，为不同目标选择可观察的证据。A 配对实际执行的测试；
B 配对独立核验的事实；C 除了 judge 结果，还需要调用方提供回归与一致性测量。
这些类别表示证据来源。主循环没有 C 测量生产者，也拒绝执行 A+B。
这种保守处理会让部分有用修改无法被观察，包括对已经全绿的 A 测试集所做的修改。
这时需要补测量或转交评审，不能凭空算出收益。

### 实现前固定比较口径

修改候选前，确定目标、允许的修改范围、评测策略和留出集。即使候选删掉某项父代义务，
比较时仍要保留它。自举从基线版本冻结决策代码，避免候选充当自己的评分器。
目标改变时，应明确建立新的评测契约，不能改写已有运行的规则。

这次冻结保证实验含义稳定。评审前还要冻结一次：完成实现、文档和已获授权的版本更新，
再标明准确的候选快照。评审与验证必须对应这份快照。两次冻结承担不同责任；
实现后补齐文档，不允许改动先前冻结的评测器或留出集。

### 模型提出假设，检查需要证据

反思和提案帮助发现可能的改进。确定性代码检查输入、比较测量，再决定采纳或转交评审。
判断 judge 是否独立时，保留实际返回的 provider。judge 意见一致不能单独证明改进；
反思符合结构，也不能证明其中的事实已经核验。

严格比较可能拒绝或暂停一个看似合理的修改，这是有意保留的不确定性。
降低阈值，或把不可用测量当作通过，会把它掩盖掉。统计控制也有明确范围：
任务通过不能证明测量对象之外的行为；当前 acceptor 对反复提出的新候选没有整次运行的错误概率上界。
具体要求见[评测契约](reference/evaluation.md)与[统计假设](reference/acceptor_math.md)。

### 保留可恢复的决策，明确操作权限

保存失败、不可用观测、拒绝原因、provider 元数据，以及采纳候选的完整快照。
摘要能标识内容，却不能恢复内容。完整快照和追加事件会占用空间；只有保留下来的内容及依赖
仍然足以恢复时，才能安全缩减记录。[存储契约](DATA.md)区分当前恢复要求、历史证据与临时执行副本。

真实运行证据放在验证为 PRIVATE 的 Git 伴生仓，既保留历史，也避免进入公开工具仓。
缺少私有证明时，写入失败。worktree、prompt 过滤和冻结的 Python 代码各自保护特定边界，
不能证明操作系统沙箱隔离。ACCEPT 负责归档候选；安装、合并、发布和对外操作按调用方授权处理。
[维护交付说明](reference/maintenance.md)记录评审所用候选、实际完成的检查，以及后续动作。
