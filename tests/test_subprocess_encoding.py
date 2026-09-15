"""捕获子进程时必须显式指定编码。

真实症状:拿 self-evolve 去跑一个**测试输出带中文**的目标仓,PROFILE 阶段当场炸:

    UnicodeDecodeError: 'gbk' codec can't decode byte 0xac in position 50
      File "subprocess.py", line 1615, in _readerthread

原因是 `text=True` 不指定 `encoding` 时,Python 用的是**系统 ANSI 码页**
(这台机器上是 gbk),而子进程(pytest)吐的是 UTF-8。

这个缺陷的形状值得单独说:它只在**目标仓有非 ASCII 输出**时才现形。
一个全英文的目标永远不会触发它,于是它可以在套件全绿的情况下长期存在,
而第一个中文目标一来就整条闭环卡在 INIT —— 崩在读取线程里,
主进程的退出码还是 0,状态文件停在上一个阶段,看起来像「跑完了但什么都没做」。

`agents.py` 里两处一直是对的写法。这条用例把那个写法钉成全仓的规则。
"""

from __future__ import annotations

import glob
import io
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALL = re.compile(r"subprocess\.(run|Popen)\((?:[^()]|\([^()]*\))*\)", re.S)


def _calls():
    for f in sorted(glob.glob(os.path.join(HERE, "tools", "**", "*.py"), recursive=True)):
        src = io.open(f, encoding="utf-8", errors="replace").read()
        for m in CALL.finditer(src):
            yield os.path.relpath(f, HERE), src[:m.start()].count("\n") + 1, m.group(0)


def test_every_text_mode_capture_pins_utf8():
    bad = []
    for rel, line, blk in _calls():
        if "text=True" in blk and "encoding=" not in blk:
            bad.append(f"{rel}:{line}  {' '.join(blk.split())[:90]}")
    assert not bad, (
        "这些地方以 text=True 捕获子进程却没有钉编码,会用系统 ANSI 码页解 UTF-8:\n  "
        + "\n  ".join(bad))


def test_the_scan_actually_finds_calls():
    """负对照:扫描器必须真的扫到东西。

    没有这一条,一个正则写错、一个匹配都拿不到的扫描器,和一个真的全都合规的仓
    打印出同样的绿色 —— 而这正是 self-evolve 自己在防的那类缺陷。
    """
    found = list(_calls())
    assert len(found) >= 8, f"只扫到 {len(found)} 处 subprocess 调用,扫描器大概没在工作"


def test_a_bad_call_would_be_caught():
    """把一段违规代码喂给同一个判据,它必须被认出来。

    钉的是判据本身,不依赖仓里此刻恰好有没有违规写法。
    """
    sample = 'subprocess.run(["git", "log"], capture_output=True, text=True)'
    m = CALL.search(sample)
    assert m and "text=True" in m.group(0) and "encoding=" not in m.group(0)

    good = ('subprocess.run(["git", "log"], capture_output=True, text=True, '
            'encoding="utf-8", errors="replace")')
    m2 = CALL.search(good)
    assert m2 and "encoding=" in m2.group(0)
