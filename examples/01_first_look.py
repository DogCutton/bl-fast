# -*- coding: utf-8 -*-
"""练习 1：先看清你面对的是什么。

在 Blender 里运行这个脚本，然后看它的输出。

学到两件事：
  1. 动手之前先确认"我在哪个会话、哪个文件"
  2. 读 schema，而不是背 API
"""

import os
import sys
import bpy

try:
    import os.path as _osp
    _ROOT = _osp.dirname(_osp.dirname(_osp.abspath(__file__)))
except NameError:          # Blender 的 Text Editor 里没有 __file__
    _ROOT = r"F:\DeepSeek Harness Workspace\tools\bl-fast"
if _ROOT not in sys.path:
    sys.path.append(_ROOT)

print("=" * 62)
print("① 会话身份（任何改动之前先看这个）")
print("=" * 62)
print("  PID        :", os.getpid())
print("  Blender    :", bpy.app.version_string)
print("  当前文件   :", bpy.data.filepath or "(未保存 —— 改动只在内存里)")
print("  有未保存改动:", bpy.data.is_dirty)
print("  数据块总数 :", len(bpy.data.all_ids))

print()
print("=" * 62)
print("② 场景里有什么")
print("=" * 62)
for o in bpy.data.objects:
    print("  %-10s %-9s location=%s" % (
        o.name, o.type, tuple(round(v, 2) for v in o.location)))
print("  材质:", [m.name for m in bpy.data.materials])

print()
print("=" * 62)
print("③ Cube 能改什么 —— 读出来，不是背出来")
print("=" * 62)
cube = bpy.data.objects.get("Cube")
if cube is not None:
    rw = [p for p in cube.bl_rna.properties
          if not p.is_readonly and p.type in ("FLOAT", "INT", "ENUM", "BOOLEAN", "STRING")]
    print("  可写字段共 %d 个，举几个：" % len(rw))
    for p in rw[:12]:
        doc = (p.description or "")[:46]
        print("    %-22s %-8s %s" % (p.identifier, p.type, doc))

    print()
    print("  挑一个看完整定义（这就是 Blender 自带的文档）：")
    p = cube.bl_rna.properties["location"]
    print("    identifier  :", p.identifier)
    print("    name        :", p.name, " <- 人类可读名")
    print("    type        :", p.type)
    print("    subtype     :", p.subtype, " <- 语义提示：这是个位移")
    print("    is_readonly :", p.is_readonly)
    print("    description :", p.description)

    print()
    print("  再挑一个枚举，看它接受哪些拼写：")
    p = cube.bl_rna.properties["rotation_mode"]
    print("    options =", [e.identifier for e in p.enum_items])

print()
print("=" * 62)
print("④ 用 bl_fast 读同样的东西（更紧凑，输出是给模型看的）")
print("=" * 62)
try:
    import bl_fast as bf
    if cube is not None:
        txt = bf.describe_text(cube, writable_only=True)
        print("\n".join(txt.split("\n")[:10]))
        print("    ...")
        print("    （全文 %d 行）" % (txt.count("\n") + 1))
except Exception as e:
    print("  bl_fast 加载失败:", type(e).__name__, e)

print()
print("下一步：把本文件里的属性名换成你想改的，试着 setattr 看看效果。")
