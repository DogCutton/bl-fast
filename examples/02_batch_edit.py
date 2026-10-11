# -*- coding: utf-8 -*-
"""练习 2：为什么"批量"能快 100 倍。

同一个任务做两遍 —— 一遍用 bpy.ops 逐个来，一遍用数据层批量做 —— 对比耗时。

你会看到：结果完全一样，差别全在"通知"上。
"""

import sys
import time
import bpy
import numpy as np

try:
    import os.path as _osp
    _ROOT = _osp.dirname(_osp.dirname(_osp.abspath(__file__)))
except NameError:          # Blender 的 Text Editor 里没有 __file__
    _ROOT = r"F:\DeepSeek Harness Workspace\tools\bl-fast"
if _ROOT not in sys.path:
    sys.path.append(_ROOT)
import bl_fast as bf

N = 100

# ---------------------------------------------------------------- 慢路径
print("慢路径：bpy.ops 逐个建 %d 个立方体 ..." % N)
t0 = time.perf_counter()
for i in range(N):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.active_object
    o.location = (i % 10, i // 10, 0.0)
t_slow = time.perf_counter() - t0
print("  耗时 %.1f ms  （平均 %.2f ms/个）" % (t_slow * 1000, t_slow * 1000 / N))

# 清掉刚才建的（名字通常是 立方体 / Cube.xxx，两种都清）
bf.delete_many([o for o in bpy.data.objects
                if o.name.startswith(("Cube.", "立方体"))])
bf.purge_orphans()

# ---------------------------------------------------------------- 快路径
print()
print("快路径：数据层批量建 %d 个 ..." % N)
t0 = time.perf_counter()
with bf.Edit("练习：批量建立方体") as ed:
    cm = bf.cube_mesh("EXAMPLE_CUBE")
    objs = bf.spawn_linked("Ex", N, cm)          # 几何共享，内存只存一份
    pos = np.column_stack([np.arange(N) % 10, np.arange(N) // 10, np.zeros(N)])
    bf.set_locations(objs, pos)
t_fast = time.perf_counter() - t0
print("  耗时 %.1f ms  （平均 %.3f ms/个）" % (t_fast * 1000, t_fast * 1000 / N))
print("  committed =", ed.committed)

print()
print("=" * 62)
print("结论：快 %.1f 倍" % (t_slow / t_fast))
print("=" * 62)
print("结果一样（100 个对象、位置一样），差别在于：")
print("  · 慢路径每次调用都要拍撤销快照、重算依赖图、校验上下文")
print("  · 快路径只在 with 块退出时做一次")
print()
print("自己试试：把 N 改成 500，看倍数怎么变。")

# 想留着看效果就把下面两行注释掉
# bf.delete_many(objs)
# bf.purge_orphans()
print()
print("（已保留这 %d 个对象，想清掉就把文件末尾两行取消注释再跑一次）" % N)
