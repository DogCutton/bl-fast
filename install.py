# -*- coding: utf-8 -*-
"""bl-fast 安装脚本（在 Blender 里运行）

用法（任选一种）：
    A. Blender 的 Text Editor：打开本文件 → Alt+P
    B. 命令行：
       blender.exe --background --python install.py

它把 bl_fast.py 复制到 Blender 的「用户脚本模块目录」——
那个目录本来就在 sys.path 里，所以复制完就能 `import bl_fast`。

卸载 = 删掉那一个文件。
"""

import os
import shutil
import sys

try:
    import bpy
except ImportError:
    print("本脚本必须在 Blender 里运行（它需要 bpy）")
    raise SystemExit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "bl_fast.py")

line = "=" * 62
print(line)
print("bl-fast 安装")
print(line)
print("  Blender :", bpy.app.version_string)
print("  来源    :", SRC)

if not os.path.exists(SRC):
    print("  ✗ 找不到 bl_fast.py —— 它应该和本脚本在同一目录")
    raise SystemExit(1)

scripts = bpy.utils.user_resource("SCRIPTS")
dst_dir = os.path.join(scripts, "modules")
os.makedirs(dst_dir, exist_ok=True)
dst = os.path.join(dst_dir, "bl_fast.py")

shutil.copy2(SRC, dst)
print("  目标    :", dst)

# 立刻验证：把目标目录放进 sys.path 并真的导入一次
if dst_dir not in sys.path:
    sys.path.insert(0, dst_dir)
sys.modules.pop("bl_fast", None)
try:
    import bl_fast
except Exception as e:
    print()
    print("  ✗ 复制成功但导入失败:", type(e).__name__, e)
    raise SystemExit(1)

print()
print(line)
print("✓ 安装成功")
print(line)
print("  已导入 :", bl_fast.__file__)
print()
print("之后在**任何** Blender 脚本里都可以直接用：")
print("    import bl_fast as bf")
print()
print("快速自检：")
print("    cube = bpy.data.objects['Cube']")
print("    print(len(bf.snapshot(cube)))      # 大约 99")
print()
print("卸载：删掉上面那个文件，或运行 uninstall.ps1")
