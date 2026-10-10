# bl-fast

面向 AI 代码编辑的 Blender 高速批量编辑原语库。

**一句话：让 AI 写一段代码一次提交，而不是对每个对象调用一次工具。**

---

## 为什么快

Blender 有两套入口：给**手指**用的 `bpy.ops`（菜单按钮背后那套），和给**程序**用的 `bpy.data`。
前者每次调用都要付"撤销快照 + 依赖图重算 + 上下文校验"的固定开销，而这套开销
**与你要编辑多少东西无关**——所以逐个调用是最贵的用法。

一次 `bpy.ops.mesh.primitive_cube_add()` 实测 1504 µs，拆开是这样：

| 项目 | 耗时 | 占比 | 性质 |
|---|---|---|---|
| 撤销快照 | 783 µs | 52% | 记账 |
| 参数解析 / UI 通知 / 命名检查 | ~590 µs | 39% | 杂项 |
| 依赖图重算 | 118 µs | 8% | 同步 |
| ops 上下文校验（poll） | 9.6 µs | 0.7% | 校验 |
| **真正造出 8 顶点 6 面几何** | **< 0.2 µs** | **≈0.01%** | **干活** |

**干活占万分之一。** 所以加速不是"把活干得更快"，而是**不干那些活**。

旁证：同一个操作在空场景里是 1504 µs/个，在已有 100 个对象的场景里涨到 3667 µs/个。
它变慢了，说明时间花在**跟场景规模相关的手续**上，而不是花在造立方体上。

## 实测加速

环境：Blender 5.2.1 LTS / Release / 内嵌 Python 3.13.13 / numpy 2.3.4 / Windows 10

| 任务 | 慢路径 | 快路径 | 加速 |
|---|---|---|---|
| 创建 200 个立方体 + 随机摆放 | `bpy.ops` 逐个 **2572 ms** | 数据层批量 **21.5 ms** | **119.7×** |
| 100 万顶点变形 | Python 循环 **3325 ms**(外推) | numpy 向量化 **226 ms** | **14.7×** |
| 建 10 万三角面网格 | `from_pydata` **447 ms** | numpy 直建 **86 ms** | **5.2×** |
| 50 次改动提交 | 逐个 `update()` **93.8 ms** | 批量一次 **1.67 ms** | **56.2×** |

**结果与原路径逐位等价**，不是牺牲正确性换速度：

- 位置数组 `np.allclose(..., atol=1e-6)` 通过
- 拓扑一致：两条建网格路径都得到 300000 顶点 / 300000 边 / 100000 面

## 设计三原则

1. **批量**：numpy 进 / numpy 出。绝不写 `for v in mesh.vertices`
2. **延迟**：编辑期间不碰依赖图，退出 `with` 块时一次性提交
3. **事务**：一段编辑 = 一个 undo 步骤，而不是每一步一个

三条都从同一句话推出来：**固定成本与批量大小无关，所以把它摊薄。**

## 加载

```python
import sys
sys.path.append(r"F:/DeepSeek Harness Workspace/tools/bl-fast")
import bl_fast as bf
```

依赖：`bpy`（Blender 自带）、`numpy`（Blender 自带，无需安装）。

## API

### 读取

| 函数 | 返回 |
|---|---|
| `positions(mesh)` | `(N,3) float32` 顶点位置 |
| `edge_verts(mesh)` | `(E,2) int32` 边 → 顶点索引 |
| `face_off_corners(mesh)` | `(loop_start, corner_vert)` 面拓扑 |
| `attr_vector(mesh, name)` | FLOAT_VECTOR 属性 → `(N,3)` |
| `attr_scalar(mesh, name, dtype)` | 标量属性 → `(N,)` |

### 写入

| 函数 | 说明 |
|---|---|
| `set_positions(mesh, arr)` | 一次写入全部顶点位置 |
| `transform_mesh(mesh, matrix)` | 4×4 矩阵批量变换（在 numpy 里算完再写回） |
| `offset_mesh(mesh, delta)` | 平移所有顶点 |

### 建模

| 函数 | 说明 |
|---|---|
| `mesh_from_arrays(name, verts, faces)` | 从 numpy 直建网格，绕开 `from_pydata` |
| `cube_mesh(name, size)` | 立方体（8 顶点 / 6 四边面） |
| `grid_mesh(name, nx, ny, size)` | 规则四边形网格 |

### 对象

| 函数 | 说明 |
|---|---|
| `spawn_linked(name, count, mesh)` | 建 N 个**共享同一 mesh** 的对象（实例化） |
| `spawn_many(name, meshes)` | 每个 mesh 建一个对象 |
| `set_locations(objs, locs)` | 批量写 location |
| `set_scales(objs, scales)` | 批量写 scale（传 `(3,)` 会广播） |
| `delete_many(objs)` | 一次删除一批 |
| `purge_orphans()` | 清掉无用户引用的 datablock |

### 事务

```python
with bf.Edit("ai: scatter cubes", undo=True):
    ...
# 退出时统一做 view_layer.update() 一次 + undo_push() 一次
```

`undo=False` 时不进撤销栈（适合纯计算或临时对象）。

## 用法

```python
import sys
import numpy as np
sys.path.append(r"F:/DeepSeek Harness Workspace/tools/bl-fast")
import bl_fast as bf

rng = np.random.RandomState(42)

with bf.Edit("ai: 200 个立方体随机散布"):
    cm   = bf.cube_mesh("CM")
    objs = bf.spawn_linked("Cube", 200, cm)      # 几何共享，内存只存一份
    bf.set_locations(objs, rng.rand(200, 3) * 10)
    bf.set_scales(objs, (0.4, 0.4, 0.4))
```

变形一个已有网格：

```python
with bf.Edit("ai: 波浪变形"):
    p = bf.positions(mesh)              # 一次读进 numpy
    p[:, 2] = 0.3 * np.sin(5 * p[:, 0]) # 向量化运算
    bf.set_positions(mesh, p)           # 一次写回
```

## 已知限制

- **`bpy.ops` 不可替代的场合**：`mode_set`（进编辑/雕刻模式）、渲染、导出、部分编辑器操作。
  正确的规则不是"永远别用 ops"，而是"**ops 只用在数据层没有替代的地方**"。
- **`mesh_from_arrays` 要求等长面**（全三角或全四边）。混合拓扑得走 bmesh。
- **无回读校验**。写完之后库不自证结果，调用方需要自己读回来验证。
- **`spawn_linked` 共享 mesh**：改一个对象的几何等于改全部。要独立几何请用 `spawn_many`。
- **撤销有硬顶**：`undo_steps` 默认 32，一次 `Edit` 占一步。改网格的每步快照约 0.8 MB
  （40 万顶点实测），栈满后环形淘汰。
- **不改变 Blender 的内存策略**：删除不归还操作系统，进程内存是高水位模型。
- **非线程安全**：Blender 的 Python API 不是线程安全的，不要多线程调用 `bpy`。
- **未覆盖往返层**：本库只优化"Blender 内部"的成本。如果调用方仍然每次工具调用只做一件事，
  最大的那层杠杆（跨进程往返）就没吃到。

## 数据来源

本库的实测数据与设计推导，来自对 Blender 5.2.1 的一次内存/性能实测，包括：
DNA 与属性化存储、Copy-on-Write 惰性求值、撤销的环形缓冲与快照成本、
`bpy.ops` 与数据层的成本解剖。
所有数字均为本机 Release 构建实测，**换版本或换构建（debug/ASAN）不保证成立**。
