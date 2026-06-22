"""IMMUTABLE 裁决代码集权威清单 + frozen 物化/哈希（spec §3 铁律3, §6 自举）。"""
from __future__ import annotations
import os, hashlib, subprocess

# 相对 tools/sie/ 的裁决代码集。新增裁决模块必须登记于此，否则自举哈希门不护它。
# basename 归一：清单须为顶层文件名，含子路径需升级 _normalize。
IMMUTABLE_RELPATHS: tuple[str, ...] = (
    "statemachine.py",   # 状态机转移
    "acceptor.py",       # PACE 配对裁决
    "judges.py",         # 异构 judge
    "verifiable.py",     # A 档 grader / 变异测试门
    "anchors.py",        # B 档锚核查
    "selfdeception.py",  # 自欺指数多闸
    "gate_human.py",     # action 分级 / 人审门
    "profile.py",        # tier 画像冻结判定
    "sandbox.py",        # realpath 边界 / action 分级
    "supervisor.py",     # 双进程裁决 loader
    "immutable.py",      # 清单与哈希门自身
    "patch.py",          # AST 危险调用拒绝门（决策码自身、漏列则 candidate 可白名单任意危险 import）
    "proxy.py",          # 出站 harness 代发+熵/序列异常审查（漏列则 candidate 可开隐蔽 exfiltration）
    "events.py",         # 状态机 _apply 实现熔断/活性计数清零/delta 归约（漏列则 candidate 可破坏熔断）
)

_IMMUTABLE_SET = frozenset(IMMUTABLE_RELPATHS)


def _normalize(relpath: str) -> str:
    """统一分隔符 + 去 ./.. + 取 basename，防止路径绕过。

    规则：
    1. 反斜杠统一为正斜杠
    2. os.path.normpath 去掉 ./ 和 ../ 段
    3. 取 basename——只校验文件名，不关心目录前缀
       （acceptor.py / ./acceptor.py / tools/sie/acceptor.py / x/../acceptor.py 均归一为 acceptor.py）
    注：basename 取法已足够防绕过，因为 IMMUTABLE_RELPATHS 全是纯文件名（无子目录）。
    """
    p = relpath.replace("\\", "/")
    p = os.path.normpath(p).replace("\\", "/")
    return os.path.basename(p)


def is_immutable_relpath(relpath: str) -> bool:
    """路径归一化后判定是否属于 IMMUTABLE 裁决代码集。

    防绕过：
    - ./acceptor.py → acceptor.py ✓
    - tools/sie/acceptor.py → acceptor.py ✓
    - tools\\sie\\acceptor.py → acceptor.py ✓
    - sub/../acceptor.py → acceptor.py ✓
    - /abs/path/acceptor.py → acceptor.py ✓
    """
    return _normalize(relpath) in _IMMUTABLE_SET


def hash_file(path: str) -> str:
    """返回文件的 SHA-256 hexdigest。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def materialize_frozen(base_ref: str, sie_root: str, frozen_dir: str) -> dict[str, str]:
    """把 IMMUTABLE 文件从 git base_ref 的内容写到 frozen_dir，返回 {relpath: sha256}。

    关键：内容取自 base ref（git show），绝不读 candidate 工作区，
    防被改后的 IMMUTABLE 入 frozen。
    frozen_dir 由调用方放在 candidate 不可写区（supervisor 主进程私有）。
    """
    os.makedirs(frozen_dir, exist_ok=True)
    # 找到 sie_root 所在仓库的根，算出 IMMUTABLE 在仓库中的 git 路径前缀。
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=sie_root,
        check=True, capture_output=True, text=True).stdout.strip()
    rel_prefix = os.path.relpath(sie_root, repo_root).replace("\\", "/")
    digests: dict[str, str] = {}
    for rp in IMMUTABLE_RELPATHS:
        git_path = f"{rel_prefix}/{rp}" if rel_prefix not in (".", "") else rp
        try:
            content = subprocess.run(
                ["git", "show", f"{base_ref}:{git_path}"], cwd=repo_root,
                check=True, capture_output=True).stdout
        except subprocess.CalledProcessError:
            # base ref 尚无该文件（新文件未提交）：跳过物化，记空哈希以便启动门发现缺口。
            continue
        out = os.path.join(frozen_dir, rp)
        with open(out, "wb") as f:
            f.write(content)
        os.chmod(out, 0o444)  # 设置为只读（POSIX 去写权、Windows 只读属性）
        digests[rp] = hash_file(out)
    return digests


class ImmutableViolation(Exception):
    """candidate 篡改/缺失 IMMUTABLE 裁决文件——启动 fail-closed 拒绝。"""


def verify_immutable(candidate_sie_root: str, frozen_digests: dict[str, str]) -> None:
    """比对 candidate 内 IMMUTABLE 文件哈希是否与 frozen 记录一致。

    任一文件缺失、哈希不符或 frozen_digests 为空，raise ImmutableViolation。
    fail-closed：绝无静默通过的异常路径。

    处理跨平台行尾差异：候选文件的内容先转换为 LF（与 frozen 的 git show 产物一致）后再哈希。
    """
    if not frozen_digests:
        raise ImmutableViolation("frozen 哈希记录为空，拒绝在无基线下运行 IMMUTABLE 锁")
    bad: list[str] = []
    for rp, expected in frozen_digests.items():
        cand = os.path.join(candidate_sie_root, rp)
        if not os.path.isfile(cand):
            bad.append(f"{rp}: 缺失")
            continue
        # 规范化行尾为 LF（与 git show 产物一致），计算规范化后的哈希
        with open(cand, "rb") as f:
            content = f.read()
        # 转换 CRLF → LF（处理 Windows 工作区行尾转换）
        normalized = content.replace(b"\r\n", b"\n")
        h = hashlib.sha256()
        h.update(normalized)
        actual = h.hexdigest()
        if actual != expected:
            bad.append(f"{rp}: 哈希不符 expected={expected[:12]} got={actual[:12]}")
    if bad:
        raise ImmutableViolation("IMMUTABLE 校验失败: " + "; ".join(bad))
