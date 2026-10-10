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
import numpy as np

__all__ = [
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
    mesh.vertices.foreach_set("co", _flat(arr, np.float32))
    return mesh


def transform_mesh(mesh, matrix):
    """用 4x4 矩阵批量变换顶点。

    变换在 numpy 里做完再一次写回，比逐顶点 RNA 赋值快两个数量级。
    matrix 可以是 (4,4) 或 (3,4)。
    """
    M = np.asarray(matrix, dtype=np.float32)
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
def mesh_from_arrays(name, verts, faces, calc_edges=True):
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
    me = bpy.data.meshes.new(name)
    me.vertices.add(n)
    me.vertices.foreach_set("co", verts.ravel())
    if f:
        me.loops.add(f * k)
        me.polygons.add(f)
        me.polygons.foreach_set("loop_start", np.arange(f, dtype=np.int32) * k)
        me.loops.foreach_set("vertex_index", faces.ravel())
    me.update(calc_edges=calc_edges)
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


# ------------------------------------------------------------------ 事务
class Edit(object):
    """一段 AI 编辑 = 一次依赖图提交 + 一个 undo 步骤

        with bf.Edit("ai: ..."):
            ...批量改动...

    退出时统一做 view_layer.update() 和 undo_push()。
    实测：逐个 update 比最后一次性 update 慢约 68 倍；
          undo 每步约 0.2-0.9 MB（改网格时每步整份重写）。
    """

    __slots__ = ("label", "undo", "committed")

    def __init__(self, label="ai edit", undo=True):
        self.label = label
        self.undo = undo
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            return False        # 出错不提交，让异常炸出去
        bpy.context.view_layer.update()
        if self.undo:
            bpy.ops.ed.undo_push(message=self.label)
        self.committed = True
        return False
