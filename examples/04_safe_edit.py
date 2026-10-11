# -*- coding: utf-8 -*-
"""练习 4：安全编辑 —— 事务、自动回滚、校验、冲突检测。

这个练习演示 bl_fast 存在的理由：批量编辑很快，但快的前提是"少做事"，
而少做的那部分里有些是安全网。这里把它们一个一个补回来。
"""

import sys
import bpy
import numpy as np

BL_FAST = r"F:\DeepSeek Harness Workspace\tools\bl-fast"
if BL_FAST not in sys.path:
    sys.path.append(BL_FAST)
import bl_fast as bf

cube = bpy.data.objects["Cube"]
line = "=" * 62

# ------------------------------------------------------------------ 1
print(line)
print("① 事务：块内抛异常 -> 自动回滚")
print(line)
print("  编辑前 location =", tuple(round(v, 2) for v in cube.location))
try:
    with bf.Edit("练习：会失败的编辑") as ed:
        cube.location = (9.0, 9.0, 9.0)
        raise RuntimeError("故意失败")
except RuntimeError as e:
    print("  捕获到:", e)
print("  之后 location   =", tuple(round(v, 2) for v in cube.location))
print("  committed=%s  rolled_back=%s" % (ed.committed, ed.rolled_back))
if ed.rollback_failed:
    print("  ⚠️ 回滚失败：这个环境里 bpy.ops.ed.undo() 不可用")
elif not ed.undo_available:
    print("  ⚠️ 环境不支持 undo —— 没有还原点，也没回滚")
    print("     （无头进程常见；GUI 会话里应正常）")
else:
    print("  ✓ 已回滚：undo 让「改了一半」的数据退回编辑前")
    print("    （注意：undo 本身不会自己回滚，是 Edit 在异常时主动调它）")

# ------------------------------------------------------------------ 2
print()
print(line)
print("② 形状校验：错误信息说清「期望什么、实际什么」")
print(line)
cm = bf.cube_mesh("EXAMPLE_CHECK")          # 8 顶点
print("  网格有 %d 个顶点，所以形状应该是 (8, 3)" % len(cm.vertices))
try:
    bf.set_positions(cm, np.zeros((8, 2), dtype=np.float32))
except ValueError as e:
    print("  传 (8,2) ->", e)
print("  （对比：不拦的话 foreach_set 只会说 internal error setting the array）")

# ------------------------------------------------------------------ 3
print()
print(line)
print("③ 回读校验：证明真的写进去了")
print(line)
diff = bf.set_positions_checked(cm, np.zeros((8, 3), dtype=np.float32))
print("  set_positions_checked 返回最大偏差 =", diff)

# ------------------------------------------------------------------ 4
print()
print(line)
print("④ 快照 + 增量同步（保住你自己手改的部分）")
print(line)
cube.location = (0.0, 0.0, 0.0)
cube.rotation_euler = (0.0, 0.0, 0.0)

snap = bf.snapshot(cube)
print("  快照: %d 个字段，跳过 %d 个不可逆字段（Matrix 之类）"
      % (len(snap), len(snap.skipped)))

snap["location"] = [1.0, 2.0, 3.0]          # "AI 想改的"
cube.rotation_euler = (0.5, 0.0, 0.0)       # "你同时手改的"

result = bf.patch(cube, snap)
print("  patch 结果:", result)
print("  location       =", tuple(round(v, 2) for v in cube.location))
print("  你的 rotation  =", tuple(round(v, 2) for v in cube.rotation_euler),
      "-> 保住了吗:", abs(cube.rotation_euler[0] - 0.5) < 1e-6)

# ------------------------------------------------------------------ 5
print()
print(line)
print("⑤ 冲突检测：两边改同一个字段")
print(line)
cube.location = (0.0, 0.0, 0.0)
cube.rotation_euler = (0.0, 0.0, 0.0)
snap2 = bf.snapshot(cube)
snap2["rotation_euler"] = [1.0, 1.0, 1.0]   # AI 也要改 rotation
cube.rotation_euler = (0.5, 0.0, 0.0)       # 你先改了
try:
    bf.patch(cube, snap2)
    print("  *** 没有抛异常，不对劲 ***")
except RuntimeError as e:
    print("  raise 策略 ->", str(e)[:80])
print("  rotation 仍是", tuple(round(v, 2) for v in cube.rotation_euler),
      "（一个字都没写）")
r = bf.patch(cube, snap2, on_conflict="skip")
print("  skip 策略 ->", r, " rotation =", tuple(round(v, 2) for v in cube.rotation_euler))

# ------------------------------------------------------------------ 收尾
cube.location = (0.0, 0.0, 0.0)
cube.rotation_euler = (0.0, 0.0, 0.0)
bf.delete_many([cm])
bf.purge_orphans()

print()
print(line)
print("五条安全网，各自拦住的东西")
print(line)
print("  ① 事务   —— 失败时留下半成品")
print("  ② 形状   —— 静默写错（不报错但结果无效）")
print("  ③ 回读   —— 「我以为改了」")
print("  ④ diff   —— 同步时抹掉你手动改的东西")
print("  ⑤ 冲突   —— 两边改同一处而不自知")
