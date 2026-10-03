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
    "selfboot.py",       # candidate import isolation and frozen baseline assembly
    "immutable.py",      # 清单与哈希门自身
    "patch.py",          # AST 危险调用拒绝门（决策码自身、漏列则 candidate 可白名单任意危险 import）
    "proxy.py",          # 出站 harness 代发+熵/序列异常审查（漏列则 candidate 可开隐蔽 exfiltration）
    "events.py",         # 状态机 _apply 实现熔断/活性计数清零/delta 归约（漏列则 candidate 可破坏熔断）
    "runtime_data.py",   # PRIVATE runtime paths and disposable agent cwd
    "business_tree.py",  # selected snapshot identity and exact restoration
    "archive.py",        # accepted lineage and snapshots
    "evaluate.py",       # selected-parent score pairing
    "state.py",          # durable state projection
    "llm_adapter.py",    # actual-provider validation and independence
    "llm_agent_child.py",  # inherited model policy and serialized agent results
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


def hash_file(path: str, normalize_crlf: bool = False) -> str:
    """返回文件的 SHA-256 hexdigest。

    Args:
        path: 文件路径
        normalize_crlf: 若为 True，读入后将 CRLF 统一为 LF 再哈希（处理跨平台行尾）；
                        默认 False 直接对二进制内容哈希。
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()
    if normalize_crlf:
        data = data.replace(b"\r\n", b"\n")
    h.update(data)
    return h.hexdigest()


def materialize_frozen(base_ref: str, sie_root: str, frozen_dir: str) -> dict[str, str]:
    """把 IMMUTABLE 文件从 git base_ref 的内容写到 frozen_dir，返回 {relpath: sha256}。

    关键：内容取自 base ref（git show），绝不读 candidate 工作区，
    防被改后的 IMMUTABLE 入 frozen。
    frozen_dir 由调用方放在 candidate 不可写区（supervisor 主进程私有）。
    """
    from tools.sie.runtime_data import make_directory, private_file_path
    frozen_dir = str(make_directory(frozen_dir))
    # 找到 sie_root 所在仓库的根，算出 IMMUTABLE 在仓库中的 git 路径前缀。
    repo_root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=sie_root,
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    rel_prefix = os.path.relpath(sie_root, repo_root).replace("\\", "/")
    digests: dict[str, str] = {}
    for rp in IMMUTABLE_RELPATHS:
        git_path = f"{rel_prefix}/{rp}" if rel_prefix not in (".", "") else rp
        try:
            content = subprocess.run(
                ["git", "show", f"{base_ref}:{git_path}"], cwd=repo_root,
                check=True, capture_output=True).stdout
        except subprocess.CalledProcessError as error:
            raise ImmutableViolation(f"Cannot materialize required IMMUTABLE file: {rp}") from error
        out = str(private_file_path(os.path.join(frozen_dir, rp)))
        try:
            with open(out, "xb") as f:
                f.write(content)
        except FileExistsError:
            with open(out, "rb") as f:
                if f.read() != content:
                    raise ImmutableViolation(f"Existing frozen file differs from base ref: {rp}")
        os.chmod(out, 0o444)  # 设置为只读（POSIX 去写权、Windows 只读属性）
        # Preserve committed bytes, but use the same canonical hash as verification.
        digests[rp] = hash_file(out, normalize_crlf=True)
    return digests


class ImmutableViolation(Exception):
    """candidate 篡改/缺失 IMMUTABLE 裁决文件——启动 fail-closed 拒绝。"""


def verify_immutable(candidate_sie_root: str, frozen_digests: dict[str, str]) -> None:
    """比对 candidate 内 IMMUTABLE 文件哈希是否与 frozen 记录一致。

    清单不完整、哈希格式错误或任一文件缺失、哈希不符，raise ImmutableViolation。
    fail-closed：绝无静默通过的异常路径。

    Frozen and candidate digests both normalize CRLF to LF.
    """
    if not isinstance(frozen_digests, dict) or set(frozen_digests) != _IMMUTABLE_SET:
        raise ImmutableViolation("Frozen manifest must contain exactly the complete IMMUTABLE decision set")
    bad: list[str] = []
    for rp, expected in frozen_digests.items():
        if (not isinstance(expected, str) or len(expected) != 64
                or any(char not in "0123456789abcdef" for char in expected)):
            bad.append(f"{rp}: invalid SHA-256 digest")
            continue
        cand = os.path.join(candidate_sie_root, rp)
        if not os.path.isfile(cand):
            bad.append(f"{rp}: 缺失")
            continue
        # 调用 hash_file 的规范化哈希，确保与 frozen 的计算方式一致
        actual = hash_file(cand, normalize_crlf=True)
        if actual != expected:
            bad.append(f"{rp}: 哈希不符 expected={expected[:12]} got={actual[:12]}")
    if bad:
        raise ImmutableViolation("IMMUTABLE 校验失败: " + "; ".join(bad))
