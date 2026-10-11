# bl-fast

面向 AI 代码编辑的 Blender 高速批量编辑原语库。

**一句话：让 AI 写一段代码一次提交，而不是对每个对象调用一次工具。**

> **原理与架构** → [ARCHITECTURE.md](ARCHITECTURE.md)
> 全链路（从 AI 到像素，九跳逐跳给证据）、Blender 各层（wm / RNA / BKE+DNA /
> Depsgraph / Draw / 撤销）、本工具的工作原理、以及它到不了的地方。
> 文中每个结论都标了是**实测**还是**公开架构**。
> **Blender 架构入门** → [BLENDER_ARCHITECTURE.md](BLENDER_ARCHITECTURE.md)
> 从「数据在哪 / 什么时候被算 / 什么时候被画」三个问题出发，讲 Blender 本身怎么运作。
> 适合想理解机制、而不是只想调 API 的读者。

## 动手前先报身份

`execute_code` 连的是**你当前开着的那个 Blender**，不是某个沙箱。所以在任何会改动
场景的操作之前，先确认自己在哪个会话、哪个文件：

```python
import os, bpy
print(os.getpid(), bpy.data.filepath or "(未保存)", bpy.app.background)
```

三条理由：

- **会话身份**：你可能同时开着一个 GUI 会话和一个无头进程，PID 是唯一能区分它们的
- **文件身份**：`filepath` 为空 = 这个文件**从未保存**，改动只存在于内存里
- **可回滚性**：撤销栈清不掉，操作一旦进去就留在那里

真实案例：本工具的开发过程中，在一次**未保存**的会话里做了 60+ 步测试操作，
把用户 Cube 的材质槽换掉了、多加了 3 个图像数据块、撤销栈涨到 15 MB ——
而这些改动在用户重启 Blender 后**全部丢失**，因为那个文件从未落盘。

如果一个场景对用户有价值，**先让他 Ctrl+S**，再动手。

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

## 设计四原则

1. **批量**：numpy 进 / numpy 出。绝不写 `for v in mesh.vertices`
2. **延迟**：编辑期间不碰依赖图，退出 `with` 块时一次性提交
3. **撤销单位**：一段编辑 = 一次 Ctrl+Z，而不是每一步一次
4. **失败即回滚**：`Edit` 块内任何异常（含校验失败）都自动退回编辑前状态

前三条从同一句话推出来：**固定成本与批量大小无关，所以把它摊薄。**
第四条来自另一句话：**undo 不是事务 —— 它不会自己回滚。**

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
| `set_positions(mesh, arr)` | 一次写入全部顶点位置（**校验形状**） |
| `set_positions_checked(mesh, arr)` | 同上，写完后回读比对，慢约一倍 |
| `transform_mesh(mesh, matrix)` | 4×4 矩阵批量变换（在 numpy 里算完再写回） |
| `offset_mesh(mesh, delta)` | 平移所有顶点 |

### 建模

| 函数 | 说明 |
|---|---|
| `mesh_from_arrays(name, verts, faces)` | 从 numpy 直建网格，绕开 `from_pydata`；**建完自动做拓扑校验** |
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
with bf.Edit("ai: scatter cubes"):      # undo=True 默认
    ...
# 进入时:  在编辑之前留下还原点（undo_push）
# 退出时:  view_layer.update() 一次
# 异常时:  自动 bpy.ops.ed.undo() 退回进入时的状态
```

**为什么在「进入时」push 而不是「退出时」**：实测（Blender 5.2.1）—— 进入时 push 一次
+ 之后多次数据层修改，一次 Ctrl+Z 恰好回到进入时的状态；反过来若退出时才 push，
异常路径会跳过「编辑前」状态，一次 Ctrl+Z 会退到更早的地方。

| 参数 | 默认 | 说明 |
|---|---|---|
| `undo` | `True` | 是否参与撤销栈。`False` 适合纯计算/临时对象 |
| `rollback_on_error` | `True` | 异常时是否自动回滚 |
| `verify` | `None` | 成功时的校验回调；它抛异常同样触发回滚 |

**undo 本身不是事务**，它不会在异常时自己回滚，所以才有 `rollback_on_error`。
实测：块内把值改到 9.0 后抛异常，回滚后读回 0.0（`rolled_back=True, committed=False`）。

### 反射：让 AI 看见「能做什么」和「现在是什么」

Blender 内置了说明书 —— 实测 Object 的 164 个属性里 **149 个带 description（91%）**，
只算可写字段则是 **106/109（97%）**。所以 AI 不必背 API，读出来就行。

| 函数 | 作用 | 实测规模 |
|---|---|---|
| `describe(idblock, writable_only=False)` | 能力清单：类型/范围/枚举/文档 | 109 个可写字段 |
| `describe_text(idblock, writable_only=True)` | 上者的紧凑文本版 | 219 行 / 11.6 KB |
| `snapshot(idblock)` | 当前值 → 可编辑的 `Snapshot` | 99 字段 / **2.9 KB** |
| `patch(idblock, edited, on_conflict="raise")` | 只写回**变化过**的字段 | — |

```python
# 看得见状态
print(bf.describe_text(obj, writable_only=True))   # 能改什么、怎么改

snap = bf.snapshot(obj)                            # 现在是什么（2.9 KB）
snap["location"] = [9, 9, 9]                       # 直接改
bf.patch(obj, snap)                                # 只同步这一个字段
```

**`snapshot` 会自动跳过不可逆的字段** —— 实测它丢掉了 4 个 `Matrix`
（`matrix_world` / `matrix_local` / `matrix_basis` / `matrix_parent_inverse`），
因为它们是派生数据，写回去也会被覆盖。

### 冲突检测（必须用，不能省）

`patch` 默认 `on_conflict="raise"`：**先检测全部，有冲突就抛异常、一个字段都不写**。

| 策略 | 冲突时行为 | 实测 |
|---|---|---|
| `"raise"` | 抛异常，不写任何字段 | rotation 保持用户设的 `0.5` |
| `"skip"` | 跳过冲突字段，写其余 | `skipped: ["rotation_euler"]` |
| `"force"` | 冲突也覆盖 | 覆盖成 AI 的 `1,1,1` |

**关键**：AI 改 A、你改 B 时**不会**误报冲突 —— 实测 `conflicts: []`，
AI 的 location 生效，你的 rotation 原样保留。

**反面教训**（实测对比）：不做 diff 的全量覆盖会把用户改的 rotation **抹回原值**，
而且没有任何提示。

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

## 这个路径不能做什么

实测边界（Blender 5.2.1 / Windows 10），不是推测。

### 上下文是「裸」的（必须先搭桥）

`execute_code` 运行时 `area` / `region` / `space_data` 全是 `None`，所以一部分
`bpy.ops` 的 poll 会失败：

| ops | poll |
|---|---|
| `object.mode_set` | **false**（设了活动对象后变 **true**） |
| `graph.select_all` | false（当前没有 GRAPH 区域） |
| `transform.translate` / `mesh.primitive_cube_add` / `render.render` | true |

所以规则不是「做不到」，而是**先搭桥**：
`bpy.context.view_layer.objects.active = obj` + `obj.select_set(True)`，
或 `bpy.context.temp_override(window=..., area=..., region=...)`（实测可用）。

### 编辑模式下的顶点写入会被静默丢弃 ★

8 顶点临时网格，编辑模式下：

| 阶段 | 读回 |
|---|---|
| 写入全零后，**编辑模式内**读回 | `0.0` ← 看起来成功了 |
| **退出编辑模式后**读回 | `12.0` ← 原值回来了 |

API 不报错、读回也对、结果无效 —— 最危险的一类失败。
因为编辑期间几何的真源是 **BMesh**，`mesh.vertices` 只是投影。
`set_positions` 现在会在入口抛 `RuntimeError` 拦住它；要么先退出编辑模式，
要么改用 `bmesh`。

### 求值副本是「假的可写」

```
ev.location = (1,1,1)              -> OK（不报错）
ev.data.vertices[0].co = (1,1,1)   -> OK（不报错）
ev.data is orig.data               -> false
```

写得进，但下次求值就覆盖，且**不进撤销栈、不保存**。

### 只读属性

| 尝试 | 结果 |
|---|---|
| `obj.users = 5` | ✗ read-only |
| `mesh.vertices = None` | ✗ read-only |
| `obj.matrix_world = ...` | ✓ 可写 |
| `obj.data = ...` | ✓ 可写 |

### 结构性限制（绕不过）

- **模态操作**：无法启动 modal operator 并用事件驱动（需要事件循环）
- **鼠标/键盘注入**：没有 API（除非 `ctypes`）
- **不能中断**：`exec` 阻塞，死循环只能等（**推断**，未实测）
- **撤销栈历史**：只能 push / undo，不能编辑
- **GPU 显存 / 视口内部状态**：只能截图

### 状态存在哪

| 载体 | 跨调用持久 |
|---|---|
| `exec` 的裸变量 | ✗（命名空间每次新建，只预置 `bpy`） |
| **模块属性**（`sys.modules`） | ✓（实测计数 1 → 2） |
| 文件系统 | ✓ |
| Blender 场景 | ✓ |

## 在里面渲染

| 方式 | 实测耗时（320×240） | 用途 |
|---|---|---|
| `bpy.ops.render.opengl(write_still=True)` | **48.9 ms** | 快速预览 |
| `bpy.ops.render.render(write_still=True)` **首次** | **27 973 ms** | 正式渲染（含着色器编译） |
| 同上，**第二次及以后** | **1 586 ms** | 比首次快 **17.6×** |
| `gpu.types.GPUOffScreen(w, h)` | 可用 | 离屏，最程序化 |

**首次渲染的 28 秒几乎全是一次性成本**（着色器编译 / GPU 上下文初始化），
别拿它去估计后续渲染。

**关键限制**：`bpy.data.images["Render Result"]` **读不到** —— 实测无论渲染前后，
它的 `size` 恒为 `[0, 0]`、`pixels` 长度为 0。所以渲染结果**必须落盘再从文件读**：

```python
scene.render.filepath = r"...\out.png"
scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)

img = bpy.data.images.load(r"...\out.png")     # 从文件读回
px = np.empty(len(img.pixels), dtype=np.float32)
img.pixels.foreach_get(px)                      # 实测 320x240 RGBA 可读
```

这是「AI 看到渲染结果」的完整闭环：**渲染 → 落盘 → 读像素（或直接看图）**。

## 让界面刷新

**数据层修改不会自动设置重绘标记**，所以用户的视口会停在旧画面上，直到有事件
（鼠标移动等）路过。`Edit` 默认在退出时强制刷新（`redraw=True`）。

实测（Blender 5.2.1）：

| 调用 | 结果 |
|---|---|
| `bpy.context.screen.tag_redraw()` | ✗ **不存在**（`AttributeError`） |
| `area.tag_redraw()` × 4 | ✓ 0.05 ms（只设标记，异步） |
| `bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)` | ✓ **0.15 ms**，同步绘制并交换缓冲 |

所以刷新要两步：先 `area.tag_redraw()` 设标记，再 `redraw_timer` 强制同步一次。
实测 24 帧连续刷新共 392.8 ms，每帧 0.15 ms —— 便宜到可以在动画循环里用。

```python
with bf.Edit("ai: ..."):                  # 默认 redraw=True
    ...改动...
# 退出时: view_layer.update() -> tag_redraw() xN -> redraw_timer

with bf.Edit("ai: ...", redraw=False):    # 后台任务可以关掉
    ...
```

**一个容易误判的点**：截图工具（`get_viewport_screenshot`）**总会**看到最新状态，
因为它自己会强制 draw。所以「截图能看到」不等于「用户能看到」——
验证界面刷新**不能靠截图**，只能靠人看。

## 已知限制

- **`bpy.ops` 不可替代的场合**：`mode_set`（进编辑/雕刻模式）、渲染、导出、部分编辑器操作。
  正确的规则不是"永远别用 ops"，而是"**ops 只用在数据层没有替代的地方**"。
- **编辑模式下改顶点会被静默丢弃**：`set_positions` 已加守卫（抛 `RuntimeError`）。
  编辑期间几何归 BMesh 所有，必须改用 `bmesh` 或先退出编辑模式。
- **`snapshot` 只覆盖参数层**，不含几何（顶点/面是二进制缓冲，20 万顶点文本化要
  3.2 MB / 245 ms）。几何请走 `positions()` / `set_positions()`。
- **`describe_text` 不小**：一个 Object 是 219 行 / 11.6 KB（约 3k tokens）。
  只要字段名和类型时可以自己筛一遍 `describe()` 的返回值。
- **`mesh_from_arrays` 要求等长面**（全三角或全四边）。混合拓扑得走 bmesh。
- **校验是选择性的**：`set_positions` 只校验**形状**（拦住静默错误），
  要证明数值真的写进去了得用 `set_positions_checked`（多一次 memcpy）。
- **`mesh_from_arrays` 的校验有价格**：`validate=True`（默认）实测让建 10 万三角面
  从 72.5 ms 变成 100.3 ms（**+38.5%**）。要极限吞吐就传 `validate=False`，
  代价是失去越界索引 / 退化面的守卫。
- **回滚依赖 undo 栈**：`rollback_on_error` 靠 `bpy.ops.ed.undo()` 实现，
  所以 `undo=False` 时它无效；回滚精度也受撤销栈状态影响（栈满后是环形淘汰）。
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

单次测量的方差不小：同一个「创建 200 对象」基准先后跑出 21.49 ms 与 10.22 ms。
没有重复取中位数，也没有误差棒 —— 这些数字应当读作量级，而不是精确值。
