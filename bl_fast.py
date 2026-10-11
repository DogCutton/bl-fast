# -*- coding: utf-8 -*-
"""bl_fast.py —— 面向 AI 代码编辑的 Blender 高速批量原语

三条原则
  1. 批量：numpy 进 / numpy 出。绝不写 `for v in mesh.vertices`
  2. 延迟：编辑期间不碰依赖图，退出 with 块时一次性提交
  3. 事务：一段 AI 编辑 = 一个 undo 步骤（而不是每一步一个）

设计依据是本机 Blender 5.2.1 的实测数据：
  创建 100 对象    366.7 ms (bpy.ops)  ->   5.3 ms (data 层)   69x
  移动 100 对象    592.6 ms (bpy.ops)  ->   0.6 ms (RNA)     1077x
  写顶点位置       1.648 us/顶点 (py)  -> 0.154 us/顶点      10.7x
  读顶点位置       0.593 us/顶点 (py)  -> 0.052 us/顶点      11.4x
  触发求值(50 次)   59.7 ms (逐个)      ->   0.9 ms (批量)     68x

用法
    import sys
    sys.path.append(r"F:/DeepSeek Harness Workspace/Workspace 4")
    import bl_fast as bf

    with bf.Edit("ai: scatter cubes"):
        cm = bf.cube_mesh("CM")
        objs = bf.spawn_linked("Cube", 200, cm)
        bf.set_locations(objs, np.random.rand(200, 3) * 10)

要点提醒
  * 本模块只走「数据层 + 批量 API」，不调用 bpy.ops 的建模/变换操作。
    ops 只在确实没有数据层替代时使用（mode_set、渲染、导出等）。
  * Edit 退出时才 update + undo_push。循环里不要手动 update。
"""

import bpy
import json
import time
import numpy as np

__all__ = [
    # 反射：describe / snapshot / patch
    "describe", "describe_text", "snapshot", "patch",
    "positions", "edge_verts", "face_off_corners", "attr_vector", "attr_scalar",
    "set_positions", "transform_mesh", "offset_mesh",
    "mesh_from_arrays", "cube_mesh", "grid_mesh",
    "spawn_linked", "spawn_many", "set_locations", "set_scales",
    "delete_many", "purge_orphans",
    "Edit",
]


# ------------------------------------------------------------------ 工具
def _flat(a, dtype=np.float32):
    """变成 C 连续的展平数组 —— foreach_set 要求这种布局"""
    return np.ascontiguousarray(a, dtype=dtype).ravel()


def _shaped(arr, n, cols, what):
    """形状校验 —— 让错误信息说清「期望什么、实际什么」。

    foreach_set 在形状不符时只报 "internal error setting the array"，
    调用方（尤其 AI）无法据此自我修复，所以在这里先拦住。
    """
    a = np.asarray(arr)
    if a.shape != (n, cols):
        raise ValueError(
            "%s: 期望形状 (%d, %d)，实际 %s —— "
            "N 是元素个数，每元素 %d 个分量"
            % (what, n, cols, a.shape, cols))
    return a


def _check_editable(mesh, what):
    """编辑模式下对 mesh.vertices 的写入会被静默丢弃。

    实测（Blender 5.2.1，8 顶点临时网格）：编辑模式下 set_positions 写入全零，
    读回 0.0（看起来成功），退出编辑模式后读回 12.0 —— 原值回来了。
    API 不报错、读回也对、结果无效，所以必须在入口拦住。

    真源是 BMesh：编辑期间几何归 bmesh 所有，mesh.vertices 只是它的投影。
    """
    if mesh.is_editmode:
        raise RuntimeError(
            "%s: mesh.is_editmode 为真 —— 编辑模式下几何的真源是 BMesh，"
            "改 mesh.vertices 会被静默丢弃。请先退出编辑模式"
            "（bpy.ops.object.mode_set(mode='OBJECT')），或改用 bmesh"
            % what)


# ------------------------------------------------------------------ 读取
def positions(mesh):
    """顶点位置 -> (N, 3) float32"""
    a = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def edge_verts(mesh):
    """边 -> (E, 2) int32 顶点索引"""
    a = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", a)
    return a.reshape(-1, 2)


def face_off_corners(mesh):
    """面拓扑 -> (loop_start, corner_vert)

    loop_start 给出每个面在 corner 数组里的起点；配合 corner_vert
    才能还原变长多边形（三角/四边/多边混合的网格）。
    """
    ls = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", ls)
    cv = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", cv)
    return ls, cv


def attr_vector(mesh, name):
    """FLOAT_VECTOR 属性层 -> (N, 3)"""
    d = mesh.attributes[name].data
    out = np.empty(len(d) * 3, dtype=np.float32)
    d.foreach_get("vector", out)
    return out.reshape(-1, 3)


def attr_scalar(mesh, name, dtype=np.float32):
    """标量属性层 -> (N,)。布尔层传 dtype=bool"""
    d = mesh.attributes[name].data
    out = np.empty(len(d), dtype=dtype)
    d.foreach_get("value", out)
    return out


# ------------------------------------------------------------------ 写入
def set_positions(mesh, arr):
    """一次写入全部顶点位置。不触发依赖图（交给 Edit 统一提交）"""
    _check_editable(mesh, "set_positions")
    mesh.vertices.foreach_set(
        "co",
        _flat(_shaped(arr, len(mesh.vertices), 3, "set_positions"), np.float32))
    return mesh


def set_positions_checked(mesh, arr, atol=1e-5):
    """写入后立刻回读比对，用一次读取换「确实写进去了」的证据。

    比 set_positions 慢一倍左右（多一次 memcpy），
    但把「我以为改了」变成「我验证了」。返回实测最大偏差。
    """
    arr = _shaped(arr, len(mesh.vertices), 3, "set_positions_checked")
    set_positions(mesh, arr)
    back = positions(mesh)
    diff = float(np.abs(back - arr).max()) if arr.size else 0.0
    if not diff <= atol:
        raise RuntimeError(
            "set_positions_checked: 回读不一致，最大偏差 %.6g > 容差 %.6g"
            % (diff, atol))
    return diff


def transform_mesh(mesh, matrix):
    """用 4x4 矩阵批量变换顶点。

    变换在 numpy 里做完再一次写回，比逐顶点 RNA 赋值快两个数量级。
    matrix 可以是 (4,4) 或 (3,4)。
    """
    M = np.asarray(matrix, dtype=np.float32)
    if M.shape not in ((4, 4), (3, 4)):
        raise ValueError(
            "transform_mesh: matrix 形状应为 (4,4) 或 (3,4)，实际 %s"
            % (M.shape,))
    p = positions(mesh)
    p = p @ M[:3, :3].T + M[:3, 3]
    set_positions(mesh, p)
    return p


def offset_mesh(mesh, delta):
    """平移所有顶点（比 transform_mesh 更省一次矩阵乘）"""
    p = positions(mesh)
    p += np.asarray(delta, dtype=np.float32)
    set_positions(mesh, p)
    return p


# ------------------------------------------------------------------ 建模
def mesh_from_arrays(name, verts, faces, calc_edges=True, validate=True):
    """从 numpy 直接建网格，绕开 from_pydata 的 Python 嵌套 list。

    verts : (N, 3)  顶点坐标
    faces : (F, K)  等长多边形（K=3 三角 / K=4 四边）
    等长是**硬要求**：变长面请分块建或改用 bmesh。
    """
    verts = np.ascontiguousarray(verts, dtype=np.float32)
    faces = np.ascontiguousarray(faces, dtype=np.int32)
    if verts.ndim != 2 or verts.shape[1] != 3:
        raise ValueError("verts 必须是 (N,3)")
    if faces.ndim != 2:
        raise ValueError("faces 必须是 (F,K) 等长数组")

    n, f, k = len(verts), len(faces), faces.shape[1]
    if faces.size and (int(faces.min()) < 0 or int(faces.max()) >= n):
        raise ValueError(
            "faces 索引越界: 实测范围 [%d, %d]，但只有 %d 个顶点"
            % (int(faces.min()), int(faces.max()), n))
    me = bpy.data.meshes.new(name)
    me.vertices.add(n)
    me.vertices.foreach_set("co", verts.ravel())
    if f:
        me.loops.add(f * k)
        me.polygons.add(f)
        me.polygons.foreach_set("loop_start", np.arange(f, dtype=np.int32) * k)
        me.loops.foreach_set("vertex_index", faces.ravel())
    me.update(calc_edges=calc_edges)
    if validate:
        fixed = me.validate(verbose=False)
        if fixed:
            bpy.data.meshes.remove(me)
            raise ValueError(
                "mesh_from_arrays(%s): 拓扑校验需修正 %d 处问题"
                "（越界索引 / 退化面 / 重复元素），网格已丢弃"
                % (name, fixed))
    return me


def cube_mesh(name="CubeFast", size=1.0):
    """立方体：8 顶点 / 6 个四边面"""
    h = size * 0.5
    v = np.array([[-h, -h, -h], [h, -h, -h], [h, h, -h], [-h, h, -h],
                  [-h, -h, h], [h, -h, h], [h, h, h], [-h, h, h]], dtype=np.float32)
    f = np.array([[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4],
                  [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]], dtype=np.int32)
    return mesh_from_arrays(name, v, f)


def grid_mesh(name="GridFast", nx=64, ny=64, size=2.0):
    """规则四边形网格：nx*ny 顶点 / (nx-1)*(ny-1) 面"""
    xs = np.linspace(-size / 2, size / 2, nx, dtype=np.float32)
    ys = np.linspace(-size / 2, size / 2, ny, dtype=np.float32)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    verts = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(nx * ny, np.float32)])
    idx = np.arange(nx * ny, dtype=np.int32).reshape(nx, ny)
    faces = np.stack([idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(),
                      idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()], axis=1)
    return mesh_from_arrays(name, verts, faces)


# ------------------------------------------------------------------ 对象
def spawn_linked(name, count, mesh, collection=None, pad=4):
    """创建 count 个共享同一 mesh 的对象（实例化，几何只存一份）"""
    coll = collection if collection is not None else bpy.context.scene.collection
    objs = []
    for i in range(count):
        o = bpy.data.objects.new("%s.%0*d" % (name, pad, i), mesh)
        coll.objects.link(o)
        objs.append(o)
    return objs


def spawn_many(name, meshes, collection=None, pad=4):
    """每个 mesh 建一个对象，一一对应"""
    coll = collection if collection is not None else bpy.context.scene.collection
    objs = []
    for i, m in enumerate(meshes):
        o = bpy.data.objects.new("%s.%0*d" % (name, pad, i), m)
        coll.objects.link(o)
        objs.append(o)
    return objs


def set_locations(objs, locs):
    """批量写 location。逐个 RNA 赋值已是合法路径里最快的（无集合级 foreach）"""
    locs = np.asarray(locs, dtype=np.float64).reshape(-1, 3)
    if len(locs) != len(objs):
        raise ValueError("objs 与 locs 数量不一致")
    for o, l in zip(objs, locs):
        o.location = l
    return objs


def set_scales(objs, scales):
    """批量写 scale。传 (3,) 会广播到所有对象"""
    scales = np.asarray(scales, dtype=np.float64)
    if scales.ndim == 1:
        scales = np.tile(scales, (len(objs), 1))
    for o, s in zip(objs, scales):
        o.scale = s
    return objs


def delete_many(objs):
    """一次删除一批对象（实测 100 个 = 1.35 ms）"""
    items = list(objs)
    bpy.data.batch_remove(items)
    return len(items)


def purge_orphans(recursive=True):
    """清掉没有用户引用的 datablock（大对象删完记得调）"""
    return bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True,
                                  do_recursive=recursive)


# ------------------------------------------------------------------ 反射
class Snapshot(dict):
    """字段快照：一个可 json.dumps 的 dict，额外携带导出瞬间的原始值。

    `.base` 用于 patch() 的冲突检测（「同一字段被两边都改了」）。
    做成 dict 子类，是为了让调用方直接改值：

        snap = bf.snapshot(obj)
        snap["location"] = [9, 9, 9]
        bf.patch(obj, snap)
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.base = dict(self)
        self.stamp = None
        self.skipped = []


def _value(v):
    """RNA 值 -> (可 json / 可写回的值, 是否可逆)。

    实测踩过的坑，都是「看着像数据，其实是个代理对象」：
      bytes                 list(b'..') 会变成整数列表，必须优先排除
      bpy_prop_array/Vector 迭代得到数字，可逆
      IDPropertyGroup       迭代和 JSON 都不行，跳过
      str                   必须先于「可迭代」判断，否则 "Cube" 变成 ["C","u","b","e"]
    """
    if v is None or isinstance(v, (bool, int, str)):
        return v, True
    if isinstance(v, float):
        return round(v, 6), True
    if isinstance(v, bytes):
        return None, False
    try:
        items = list(v)
    except TypeError:
        return None, False
    out = []
    for x in items:
        if isinstance(x, (bool, int, str)):
            out.append(x)
        elif isinstance(x, float):
            out.append(round(x, 6))
        else:
            return None, False
    return out, True


def snapshot(idblock):
    """当前值 -> Snapshot（只含可写且可逆的字段）。

    几何不在里面：顶点/面是二进制缓冲，20 万顶点文本化要 3.2 MB / 245 ms。
    几何请走 positions() / set_positions() 那条通道。
    """
    snap = Snapshot()
    for p in idblock.bl_rna.properties:
        i = p.identifier
        if i == "rna_type" or p.is_readonly:
            continue
        if p.type not in ("BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"):
            continue
        try:
            v = getattr(idblock, i)
        except Exception:
            snap.skipped.append((i, "read failed"))
            continue
        val, ok = _value(v)
        if ok:
            snap[i] = val
        else:
            snap.skipped.append((i, type(v).__name__))
    snap.stamp = time.time()
    snap.base = dict(snap)
    return snap


def describe(idblock, writable_only=False):
    """RNA schema -> 能力清单。这是 Blender 内置的「说明书」。

    实测 Object 的 164 个属性里 149 个带 description（91%）：能写什么、
    什么类型、什么范围、枚举怎么拼、这个值什么意思，都可以读出来，
    不必让模型去背 API。
    """
    out = {}
    for p in idblock.bl_rna.properties:
        i = p.identifier
        if i == "rna_type" or (writable_only and p.is_readonly):
            continue
        d = {"name": p.name, "type": p.type, "readonly": p.is_readonly}
        if p.description:
            d["doc"] = p.description
        try:
            if p.subtype and p.subtype != "NONE":
                d["subtype"] = p.subtype
        except Exception:
            pass
        if p.type == "ENUM":
            d["options"] = [e.identifier for e in p.enum_items]
        elif p.type in ("FLOAT", "INT"):
            try:
                d["range"] = [p.hard_min, p.hard_max]
            except Exception:
                pass
        out[i] = d
    return out


def describe_text(idblock, writable_only=True):
    """describe() 的紧凑文本版 —— 比 JSON 省很多 token。"""
    lines = []
    for i, d in describe(idblock, writable_only=writable_only).items():
        bits = [i, d["type"]]
        if d["readonly"]:
            bits.append("ro")
        if "subtype" in d:
            bits.append("subtype=" + d["subtype"])
        if "range" in d:
            bits.append("range=[%g,%g]" % tuple(d["range"]))
        if "options" in d:
            bits.append("options=" + "|".join(d["options"]))
        lines.append("  ".join(bits))
        if d.get("doc"):
            lines.append("      " + d["doc"])
    return "\n".join(lines)


_UNSET = object()


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def patch(idblock, edited, base=_UNSET, on_conflict="raise"):
    """把 edited 里「相对 base 变化过」的字段写回去。

    只应用变化字段，所以 AI 没碰过的东西 —— 包括你刚在 Blender 里手改的 ——
    不会被抹掉。实测：全量覆盖会把用户改的 rotation 抹回原值，diff 应用则保留。

    base 省略时取 edited.base（snapshot() 带回来的）。
    on_conflict:
      "raise"  有冲突就抛异常，且一个字段都不写（原子，默认）
      "skip"   跳过冲突字段，写其余
      "force"  冲突也覆盖
    """
    if base is _UNSET:
        base = getattr(edited, "base", None)
    if base is None:
        raise ValueError(
            "patch: 缺少 base，无法区分「AI 改的」和「外部改的」。"
            "请传 snapshot() 的返回值；确实要全量覆盖时显式给 base={}")

    current = snapshot(idblock)
    changed = {k: v for k, v in edited.items()
               if not (k in base and _same(v, base[k]))}
    if base:
        conflicts = [k for k in changed
                     if k in current and not _same(current[k], base.get(k))]
    else:
        conflicts = []          # 显式 base={} = 放弃冲突检测

    if conflicts and on_conflict == "raise":
        raise RuntimeError(
            "patch: %d 个字段在导出后被外部改过，而 AI 也要改它们：%s。"
            "什么都没写。改用 on_conflict='skip' 跳过，或 'force' 强行覆盖"
            % (len(conflicts), ", ".join(sorted(conflicts))))

    applied, skipped = [], []
    for k, v in changed.items():
        if k not in current:
            skipped.append(k)
            continue
        if k in conflicts and on_conflict == "skip":
            skipped.append(k)
            continue
        try:
            setattr(idblock, k, v)
            applied.append(k)
        except Exception:
            skipped.append(k)
    return {"applied": applied, "skipped": skipped,
            "conflicts": conflicts, "changed": sorted(changed)}

# ------------------------------------------------------------------ 事务
class Edit(object):
    """一段 AI 编辑 = 一个撤销单位，失败时自动回滚。

        with bf.Edit("ai: ..."):
            ...批量改动...

    进入时在编辑**之前**留下还原点，所以一次 Ctrl+Z 恰好回到进入时的状态；
    块内任何异常（含 verify 失败）都会主动 undo，把「改了一半」的数据退回去。

    实测（Blender 5.2.1）：
      * 进入时 push 一次 + 之后多次数据层修改 -> 一次 undo 即回到进入时状态
      * 反过来（退出时才 push）在异常路径会跳过「编辑前」状态，
        一次 Ctrl+Z 退到更早的地方
      * 逐个 view_layer.update() 比最后一次性 update 慢约 68 倍
      * undo 快照约 0.2-0.9 MB/步（改网格时每步整份重写），栈上限 32 步

    undo 本身不是事务 —— 它不会在异常时自己回滚，所以才有 rollback_on_error。

    退出时会强制刷新界面（redraw=True）：数据层修改不会自动设置重绘标记，
    不刷新的话你的视口会停在旧画面上，直到有事件（鼠标移动等）路过。

    ⚠️ **撤销能力是运行环境相关的**：实测在 `--background` 无头进程里，
    `bpy.ops.ed.undo()` 的 poll 会失败（"context is incorrect"）。
    所以进入时会探测一次，探测不到就明确降级 —— 块内出错时**不会假装回滚**。
    调用方可以看 `ed.undo_available` 与 `ed.rollback_failed`。
    """

    __slots__ = ("label", "undo", "rollback_on_error", "verify", "redraw",
                 "committed", "rolled_back", "undo_available", "rollback_failed")

    def __init__(self, label="ai edit", undo=True, rollback_on_error=True,
                 verify=None, redraw=True):
        self.label = label
        self.undo = undo
        self.rollback_on_error = rollback_on_error
        self.verify = verify
        self.committed = False
        self.rolled_back = False
        self.undo_available = None      # 进入时探测
        self.rollback_failed = False
        self.redraw = redraw

    def __enter__(self):
        # 在编辑之前 push：这是「编辑前状态」的唯一精确还原点。
        # 但 undo 依赖上下文，所以这里探测一次而不是等出错才发现。
        self.undo_available = False
        if self.undo:
            try:
                # poll() 提前告知 undo 是否真的可用（无头进程里它是 False）
                if not bpy.ops.ed.undo.poll():
                    raise RuntimeError("undo.poll() 为假")
                bpy.ops.ed.undo_push(message="before: " + self.label)
                self.undo_available = True
            except Exception:
                self.undo_available = False
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            try:
                bpy.context.view_layer.update()
                if self.verify is not None:
                    self.verify()
            except BaseException:
                self._rollback()      # 校验失败也算失败，一样回滚
                raise
            self._notify_ui()
            self.committed = True
            return False
        self._rollback()
        return False

    def _rollback(self):
        # 回滚失败**不能**抛新异常 —— 那会把调用方真正关心的原始错误替换掉。
        # 实测：无头进程里 bpy.ops.ed.undo() poll 失败，结果调用方看到的
        # 不是「故意失败」，而是 "Operator bpy.ops.ed.undo.poll() failed"。
        if self.rollback_on_error and self.undo_available:
            try:
                bpy.ops.ed.undo()
                self.rolled_back = True
            except Exception:
                self.rollback_failed = True
        bpy.context.view_layer.update()
        self._notify_ui()

    def _notify_ui(self):
        """把改动推给界面 —— 数据层修改不会自动设置重绘标记。

        实测（Blender 5.2.1）：
          * `bpy.data` 的直接修改不设置 redraw 标记，所以窗口停在旧画面，
            直到有事件（鼠标移动等）路过
          * `Screen` 没有 `tag_redraw()`（AttributeError），必须逐个 area 调
          * `bpy.ops.wm.redraw_timer(DRAW_WIN_SWAP)` 会真的同步绘制并交换
            缓冲（它自己打印 "Draw window and swap: 0.0252 ms"），约 2.4 ms/次
          * 截图工具总是看到最新状态，因为它自己会强制 draw ——
            所以「截图能看到」不等于「用户能看到」
        """
        if not self.redraw:
            return
        try:
            sc = bpy.context.screen
            if sc is None:          # 后台/无头模式没有 screen
                return
            for area in sc.areas:
                area.tag_redraw()
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
        except Exception:
            pass
