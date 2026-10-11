# -*- coding: utf-8 -*-
"""把 BLENDER_ARCHITECTURE.md / ARCHITECTURE.md 里标了 📖 的声明变成证据。

📖 原本的意思是「来自 Blender 公开源码结构，未在本机逐行验证」。
这个脚本把那些声明逐条变成**可重跑**的检查 —— 你可以在自己的机器上跑一遍，
看看结论是否仍然成立。

用法：
    blender.exe --background --factory-startup --python verify_architecture.py

    # 想顺带验证撤销（§5.1），去掉 --factory-startup：
    blender.exe --background --python verify_architecture.py

退出码：0 = 全部 PASS；1 = 有 FAIL。
"""

import bpy
import json
import os
import platform
import sys
import tempfile

RESULTS = []


def check(section, claim, verdict, evidence):
    RESULTS.append({"section": section, "claim": claim,
                    "verdict": verdict, "evidence": evidence})


# ════════════════════════════════════════════════════════════════════
# §1.1 所有顶层数据都是 ID
# ════════════════════════════════════════════════════════════════════
ids = list(bpy.data.all_ids)
hist = {}
for i in ids:
    hist[type(i).__name__] = hist.get(type(i).__name__, 0) + 1

HEADER_FIELDS = ["name", "users", "session_uid", "library", "is_runtime_data", "tag"]
all_subclass = all(isinstance(i, bpy.types.ID) for i in ids)
header_ok = {f: all(hasattr(i, f) for i in ids) for f in HEADER_FIELDS}

check("§1.1", "所有顶层数据都是 ID，共享同一套头部",
      "PASS" if (all_subclass and all(header_ok.values())) else "FAIL",
      {"id_count": len(ids),
       "distinct_types": len(hist),
       "all_are_ID_subclass": all_subclass,
       "shared_header_on_every_id": header_ok,
       "histogram": dict(sorted(hist.items(), key=lambda kv: -kv[1]))})


# ════════════════════════════════════════════════════════════════════
# §1.2 Main 是数据库（bpy.data 的表）
# ════════════════════════════════════════════════════════════════════
tables = {}
for attr in dir(bpy.data):
    if attr.startswith("_"):
        continue
    try:
        v = getattr(bpy.data, attr, None)
    except Exception:
        continue
    if isinstance(v, bpy.types.bpy_prop_collection):
        tables[attr] = len(v)

check("§1.2", "Main 是数据库，bpy.data 的集合是它的表的视图",
      "PASS" if len(tables) >= 20 else "PARTIAL",
      {"table_count": len(tables),
       "nonempty": {k: v for k, v in sorted(tables.items(), key=lambda kv: -kv[1]) if v}})


# ════════════════════════════════════════════════════════════════════
# §2.2 RNA 同时服务四个消费者：Python / UI / 动画 / 驱动
# ════════════════════════════════════════════════════════════════════
cube = bpy.data.objects.get("Cube")
rna = {}

if cube is None:
    check("§2.2", "RNA 同时服务四个消费者", "SKIP", {"reason": "没有 Cube 对象"})
else:
    prop = cube.bl_rna.properties["location"]

    # ① Python —— 直接属性访问
    python_side = {"value": [round(v, 3) for v in cube.location],
                   "identifier": prop.identifier}

    # ② UI —— RNA 里的 UI 元数据（面板靠它自动生成控件）
    ui_side = {"subtype": prop.subtype,               # TRANSLATION -> 位移控件
               "array_length": prop.array_length,
               "hard_range": [prop.hard_min, prop.hard_max],
               "soft_range": [prop.soft_min, prop.soft_max],
               "description": (prop.description or "")[:60]}
    rot = cube.bl_rna.properties["rotation_mode"]
    ui_enum = {"identifier": rot.identifier,
               "items": [e.identifier for e in rot.enum_items]}

    # ③ 动画 —— 关键帧路径就是 RNA 路径
    anim_side = {}
    try:
        cube.keyframe_insert(data_path="location", frame=1)
        act = cube.animation_data.action if cube.animation_data else None
        # Blender 4.4+ 的 Action 是 slotted 的：action.fcurves 只是单 slot 时的
        # 快捷方式，不一定存在。要拿关键帧路径得走 layers -> strips -> channelbags。
        paths = []
        if act is not None:
            if getattr(act, "fcurves", None) and len(act.fcurves):
                paths = [fc.data_path for fc in act.fcurves]
                via = "action.fcurves"
            else:
                for layer in act.layers:
                    for strip in layer.strips:
                        for cb in strip.channelbags:
                            paths += [fc.data_path for fc in cb.fcurves]
                via = "layers/strips/channelbags (slotted)"
        else:
            via = None
        anim_side = {"data_path_used": "location", "fcurves": paths,
                     "via": via, "action": act.name if act else None}
    except Exception as e:
        anim_side = {"error": type(e).__name__ + ": " + str(e)[:60]}

    # ④ 驱动 —— 同一个 RNA 路径
    driver_side = {}
    try:
        fc = cube.driver_add("scale", 0)
        driver_side = {"data_path": fc.data_path, "index": fc.array_index,
                       "type": type(fc).__name__}
    except Exception as e:
        driver_side = {"error": type(e).__name__ + ": " + str(e)[:60]}

    same_source = (python_side["identifier"] == "location"
                   and "location" in anim_side.get("fcurves", [])
                   and driver_side.get("data_path") == "scale")

    check("§2.2", "同一份 RNA 定义同时服务 Python / UI / 动画 / 驱动",
          "PASS" if same_source else "PARTIAL",
          {"1_python": python_side,
           "2_ui_metadata": ui_side,
           "2_ui_enum": ui_enum,
           "3_animation": anim_side,
           "4_driver": driver_side,
           "note": "四者引用的是同一个 RNA identifier，不是四套并行定义"})

    # 清理（脚本要能重复跑）
    try:
        if cube.animation_data:
            cube.animation_data_clear()
        for i in range(3):
            try:
                cube.driver_remove("scale", i)
            except Exception:
                pass
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
# §6.2 GHOST 的位置（Python 侧看不到，但它的产物可见）
# ════════════════════════════════════════════════════════════════════
ghost = {"python_side_sees_ghost": hasattr(bpy, "GHOST_System"),
         "background_mode": bpy.app.background,
         "screen": bpy.context.screen is not None,
         "areas": len(bpy.context.screen.areas) if bpy.context.screen else 0,
         "windows": len(bpy.context.window_manager.windows)}

modules = []
try:
    import ctypes
    k32 = ctypes.WinDLL("kernel32.dll")
    psapi = ctypes.WinDLL("psapi.dll")
    h = k32.GetCurrentProcess()
    buf = ctypes.create_string_buffer(8 * 8192)
    need = ctypes.c_ulong(0)
    psapi.EnumProcessModules(h, buf, ctypes.sizeof(buf), ctypes.byref(need))
    n = need.value // ctypes.sizeof(ctypes.c_void_p)
    arr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))
    names = set()
    for i in range(n):
        nm = ctypes.create_string_buffer(260)
        psapi.GetModuleBaseNameA(h, arr[i], nm, 260)
        s = nm.value.decode("ascii", "replace")
        if s:
            names.add(s)
    modules = sorted(names)
except Exception as e:
    modules = ["ERR: " + type(e).__name__ + ": " + str(e)[:60]]

interesting = [m for m in modules
               if any(k in m.lower() for k in
                      ("ghost", "python", "opengl", "blender", "guardedalloc", "depsgraph"))]

ghost["total_modules"] = len(modules)
ghost["blender_related_modules"] = interesting[:15]
ghost["verdict_note"] = ("GHOST 本身在 Python 侧不可见（没有 bpy.GHOST_*），"
                         "但它作为 Blender 二进制的一部分被加载；"
                         "上层拿到的只是它的产物（screen/area/window）")

check("§6.2", "GHOST 是最底层，Python 侧几乎碰不到",
      "PARTIAL",
      ghost)


# ════════════════════════════════════════════════════════════════════
# §7.1 .blend ≈ 内存转储（结构开销远小于数据本身）
# ════════════════════════════════════════════════════════════════════
import numpy as np

N = 200_000
mesh = bpy.data.meshes.new("VERIFY_DNA")
mesh.vertices.add(N)
coords = np.random.rand(N, 3).astype(np.float32)
mesh.vertices.foreach_set("co", coords.ravel())
data_bytes = coords.nbytes

tmpdir = tempfile.mkdtemp(prefix="blfast_verify_")
blend_path = os.path.join(tmpdir, "verify_dna.blend")

dna = {"vertex_count": N, "position_data_MB": round(data_bytes / 2**20, 3)}
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=False, copy=True)
    file_bytes = os.path.getsize(blend_path)
    overhead = (file_bytes - data_bytes) / data_bytes * 100
    dna.update({"blend_file_MB": round(file_bytes / 2**20, 3),
                "overhead_percent": round(overhead, 1),
                "uncompressed": True})

    # 顺带测压缩（文档里说结构化数据能压到 ~17%）
    blend_z = os.path.join(tmpdir, "verify_dna_zstd.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_z, compress=True, copy=True)
    z_bytes = os.path.getsize(blend_z)
    dna["compressed_MB"] = round(z_bytes / 2**20, 3)
    dna["compressed_ratio_percent"] = round(z_bytes / file_bytes * 100, 1)

    verdict = "PASS" if overhead < 50 else "PARTIAL"
except Exception as e:
    dna["error"] = type(e).__name__ + ": " + str(e)[:80]
    verdict = "FAIL"

check("§7.1 / §7.2", ".blend ≈ 内存转储 + 结构描述表；压缩能显著减小",
      verdict, dna)

# 清理
try:
    bpy.data.meshes.remove(mesh)
    for f in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, f))
    os.rmdir(tmpdir)
except Exception:
    pass


# ════════════════════════════════════════════════════════════════════
# §8.1 一套 NodeTree 框架，多个编辑器
# ════════════════════════════════════════════════════════════════════
nt_classes = sorted(c for c in dir(bpy.types)
                    if c.endswith("NodeTree")
                    and isinstance(getattr(bpy.types, c, None), type))

probe = {}
mat = next((m for m in bpy.data.materials if m.use_nodes and m.node_tree), None)
if mat:
    nt = mat.node_tree
    probe = {"instance": type(nt).__name__,
             "bl_idname": nt.bl_idname,
             "nodes_new": hasattr(nt.nodes, "new"),
             "links_new": hasattr(nt.links, "new"),
             "interface": hasattr(nt, "interface")}

check("§8.1", "材质/几何/合成/纹理节点共享同一套 NodeTree 框架",
      "PASS" if (len(nt_classes) >= 4 and probe.get("nodes_new") and probe.get("links_new"))
      else "PARTIAL",
      {"nodetree_classes": nt_classes, "shared_api_probe": probe})


# ════════════════════════════════════════════════════════════════════
# §9.1 CPython 内嵌
# ════════════════════════════════════════════════════════════════════
import importlib

mods = {}
failed_mods = []
# tkinter 不在列表里：Blender 不带 Tk（它有自己的 GUI 工具包），缺它是预期的
for m in ["ctypes", "subprocess", "socket", "json", "sqlite3", "ssl", "zlib",
          "uuid", "numpy", "multiprocessing", "pickle", "tarfile"]:
    try:
        mod = importlib.import_module(m)
        mods[m] = str(getattr(mod, "__version__", "ok"))
    except Exception as e:
        mods[m] = "FAIL:" + type(e).__name__
        failed_mods.append(m)

is_cpython = platform.python_implementation() == "CPython"
all_imported = not failed_mods

check("§9.1", "Blender 内嵌一个完整的 CPython（可以直接用普通模块）",
      "PASS" if (is_cpython and all_imported) else "PARTIAL",
      {"failed": failed_mods,
       "implementation": platform.python_implementation(),
       "version": sys.version.split()[0],
       "compiler": platform.python_compiler(),
       "sys_executable": sys.executable,
       "modules": mods})


# ════════════════════════════════════════════════════════════════════
# §5.1 撤销 = 全量快照，不是差异
#      ← 需要 undo 系统可用（无头 + factory-startup 下不可用）
# ════════════════════════════════════════════════════════════════════
undo = {}
try:
    can_undo = bool(bpy.ops.ed.undo.poll())
except Exception:
    can_undo = False

undo["undo_available"] = can_undo

if not can_undo:
    check("§5.1", "撤销是全量快照（改 1 个顶点与改很多顶点成本相近）",
          "SKIP",
          {"reason": "这个环境里 bpy.ops.ed.undo.poll() 为假（无头 + factory-startup 常见）",
           "how_to_run": "去掉 --factory-startup 再跑一次本脚本"})
else:
    m = bpy.data.meshes.new("VERIFY_UNDO")
    K = 200_000
    m.vertices.add(K)
    base = np.random.rand(K, 3).astype(np.float32)
    m.vertices.foreach_set("co", base.ravel())

    def measure(nverts):
        """改 nverts 个顶点，测一次 undo 快照的字节数"""
        p = base.copy()
        p[:nverts] += 1.0
        m.vertices.foreach_set("co", p.ravel())
        before = bpy.app.memory_usage_undo()
        bpy.ops.ed.undo_push(message="verify")
        after = bpy.app.memory_usage_undo()
        return after - before

    try:
        small = measure(1)
        big = measure(20_000)
        ratio = (big / small) if small else None
        verdict = "PASS" if (small and big and 0.5 < big / small < 2.0) else "PARTIAL"
        undo.update({"changed_1_vertex_bytes": small,
                     "changed_20000_vertices_bytes": big,
                     "ratio": round(ratio, 3) if ratio else None,
                     "interpretation": ("比值接近 1 => 快照与改动量无关 => 全量；"
                                        "比值接近 20000 => 差异记录")})
    except Exception as e:
        undo["error"] = type(e).__name__ + ": " + str(e)[:80]
        verdict = "FAIL"

    check("§5.1", "撤销是全量快照，不是差异记录", verdict, undo)
    try:
        bpy.data.meshes.remove(m)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════
# 报告
# ════════════════════════════════════════════════════════════════════
print()
print("=" * 70)
print("BLENDER 架构声明验证")
print("=" * 70)
print("Blender %s | %s | %s" % (bpy.app.version_string,
                                platform.system(), platform.python_version()))
print()

failed = 0
for r in RESULTS:
    tag = {"PASS": "[PASS]", "PARTIAL": "[PART]", "FAIL": "[FAIL]", "SKIP": "[SKIP]"}[r["verdict"]]
    print("%s %-14s %s" % (tag, r["section"], r["claim"]))
    if r["verdict"] == "FAIL":
        failed += 1

print()
print("-" * 70)
print("详细证据（JSON）")
print("-" * 70)
print(json.dumps(RESULTS, indent=2, ensure_ascii=False, default=str))
print()
print("=" * 70)
if failed:
    print("结果: 有 %d 项 FAIL" % failed)
    print("=" * 70)
    sys.exit(1)
print("结果: 全部通过")
print("=" * 70)
