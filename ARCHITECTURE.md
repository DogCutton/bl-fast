# bl-fast 工作原理与它经过的 Blender 架构

这份文档说明两件事：**这个工具在 Blender 内部到底做了什么**，以及**它经过的每一层是什么**。

标注约定：

- ✅ **实测** —— 本机测量得到（Blender 5.2.1 LTS / Release / Python 3.13.13 / numpy 2.3.4 / Windows 10）
- 📖 **公开架构** —— 来自 Blender 公开源码结构，**未在本机逐行验证**

所有实测数字的复现方式见文末第 8 节。

---

## 1. 全链路：从 AI 到像素

### 1.1 链路图

```
AI（语言模型）
  │  ① 生成 Python 源码【字符串】—— 注意：不是"编辑文件"，是"提交一段代码"
  ▼
mcp__blender__execute_blender_code(code="...")
  │  ② JSON over socket（addon 内部起了一个 socket 服务）
  ▼
blender_mcp.py:2101  execute_code()
  │  ③ exec(code, {"bpy": bpy})     ← 命名空间每次新建，只预置 bpy
  ▼
CPython 3.13（Blender 内嵌解释器）
  │  ④ import bl_fast  →  本工具这一层
  ▼
bpy（RNA 的 Python 绑定）
  │  ⑤ foreach_set / setattr / bl_rna
  ▼
RNA 层（rna_*.c）
  │  ⑥ RNA_property_float_set_array 之类的批量 setter
  ▼
BKE + DNA（C 结构体 + 属性层）
  │  ⑦ 写入进程内存
  ▼
Depsgraph
  │  ⑧ 需要显式标记才会重算（view_layer.update）
  ▼
Draw Manager / GPU
  │  ⑨ 需要显式的重绘标记（area.tag_redraw + redraw_timer）
  ▼
GHOST → 屏幕
```

### 1.2 每一跳的证据

| 跳 | 证据 | 类型 |
|---|---|---|
| ②③ | addon 源码第 2101 行 `def execute_code`，内部 `exec(code, namespace)`，`namespace = {"bpy": bpy}`；stdout 被 `redirect_stdout` 捕获后返回 | ✅ 读源码 |
| ③ | 执行环境 `sys.modules` 长度 1841，`bpy`/`numpy` 在内；**模块级状态跨调用保留**（计数器 1 → 2） | ✅ 实测 |
| ④ | `import bl_fast` 后 `sys.modules["bl_fast"] is mod` 为真，`__file__` 指向磁盘路径 | ✅ 实测 |
| ⑤⑥ | `obj.bl_rna.properties` 可枚举 164 个属性，149 个带 description | ✅ 实测 |
| ⑦ | 内存布局可观测：`ID.as_pointer()` + 结构体扫描能定位 `loc[3]`（偏移 744）与 `name`（偏移 42） | ✅ 实测 |
| ⑧ | 加修改器 0 MB、`evaluated_depsgraph_get()` 0 MB、`evaluated_get()` 0 MB，**`ev.data` 才 +37.82 MB** | ✅ 实测 |
| ⑨ | `redraw_timer(DRAW_WIN_SWAP)` 自己打印 `Draw window and swap: 0.0126 ms` | ✅ 实测 |

**③ 的一个直接后果**：`execute_code` 的**返回值不会被传回**，只有 stdout 被捕获。所以任何"返回结果"都必须 `print()` 出来。

---

## 2. 工具经过的 Blender 分层

按链路顺序，而不是按教科书写。

### 2.1 GHOST —— 平台抽象层 📖

工具**不直接调用** GHOST，但第 ⑨ 跳的缓冲交换最终由它完成。

公开架构：GHOST 把 Win32 / X11 / Wayland / Cocoa 的窗口、输入事件、GL 上下文统一成 `GHOST_System` / `GHOST_Window` / `GHOST_Event`。它的存在使上层不必关心平台差异。

### 2.2 wm —— 事件循环、操作符、撤销

**`bpy.ops` 就是这一层**，也是本工具主要绕开的对象。

wm 提供：

- 事件循环与 keymap
- 操作符调度（`exec` / `invoke` / `poll` / `modal`）
- **全局撤销（memfile）**

实测：一次 `bpy.ops.mesh.primitive_cube_add()` 耗时 1504 µs，构成如下——

| 环节 | 耗时 | 占比 | 性质 |
|---|---|---|---|
| 撤销快照 | 783 µs | **52%** | 记账 |
| 参数解析 / UI 通知 / 命名检查 | ~590 µs | 39% | 杂项 |
| 依赖图重算 | 118 µs | 8% | 同步 |
| 上下文校验（poll） | 9.6 µs | 0.7% | 校验 |
| **真正写入 8 顶点 6 面** | **< 0.2 µs** | **~0.01%** | **干活** |

**旁证**：同一操作在空场景是 1504 µs/个，在已有 100 个对象的场景涨到 **3667 µs/个**。它是随场景规模变慢的，所以这些时间花在**记账**上，而不是花在造立方体上。

### 2.3 RNA —— 属性反射层

这是本工具**最主要的接口面**，也是"AI 可读性"的来源。

RNA 提供四类东西：

| 能力 | 接口 | 实测 |
|---|---|---|
| 字段列表 | `bl_rna.properties` | Object 有 **164** 个属性（55 只读 / 109 可写） |
| 人类可读名 | `.name` | `location` → `"Location"` |
| 内置文档 | `.description` | **149/164 带文档（91%）**；可写字段是 106/109（97%） |
| 取值约束 | `.hard_min` / `.hard_max` / `.enum_items` / `.subtype` | 19 个枚举、24 个 subtype |
| **批量通道** | `foreach_get` / `foreach_set` | 见下 |

**批量通道是性能的关键**：

```
逐元素：  for v in mesh.vertices: v.co = x     1.648 µs / 顶点
批量：    mesh.vertices.foreach_set("co", arr)  0.154 µs / 顶点   （10.7×）
```

原因不在算法，而在**跨语言边界**：每次 `mesh.vertices[i]` 都会新建一个 RNA 包装对象（实测 **136.7 字节/个**，40 万个 = 52.15 MB），而 `foreach_set` 只跨边界一次，C 层做一次 memcpy。

**RNA 的一个坑（本工具在实现中连撞五次）**：`p.type` 声明的类型与运行时实际拿到的 Python 类型**不是一回事**。

| 运行时类型 | 症状 |
|---|---|
| `bytes` | `list(b'...')` 会**静默**变成整数列表 |
| `bpy_prop_array` | 不可 JSON 序列化 |
| `mathutils.Vector` | 不可 JSON 序列化 |
| `IDPropertyGroup` | 不是 `dict`，也不可 JSON 序列化 |
| `str` | 必须先于"可迭代"判断，否则 `"Cube"` → `["C","u","b","e"]` |

所以 RNA 之上必须再包一层按**运行时类型**兜底的规范化（本工具的 `_value()`）。

### 2.4 BKE + DNA —— 数据与布局

**DNA** 📖 是结构体的内存布局定义，`.blend` 文件基本是内存转储 + 指针重映射。实测印证：2M 顶点（22.89 MB 位置数据）写成未压缩 `.blend` 是 **24.93 MB**，结构开销只有 **8%**。

**BKE** 是数据模型与算法。现代 Mesh 是**属性化存储**——拓扑、几何、选择状态是同级属性层。默认 Cube 的 13 个属性层：

| 域 | 属性 | 类型 |
|---|---|---|
| POINT | `position` / `.select_vert` | FLOAT_VECTOR / BOOLEAN |
| EDGE | `.edge_verts` / `.select_edge` | INT32_2D / BOOLEAN |
| CORNER | `.corner_vert` / `.corner_edge` / `UVMap` / `.uv_select_*` | INT / INT / FLOAT2 / BOOLEAN |
| FACE | `.select_poly` / `sharp_face` | BOOLEAN |

实测每顶点成本：

| 情形 | 实测 |
|---|---|
| 纯顶点网格（4M 档） | **13.36 字节/顶点**（位置 12 + `.select_vert` 1，与理论吻合） |
| 完整网格（2.0M 顶点 / 4.0M 边 / 2.0M 面 / 8.0M corners） | **54 字节/顶点**（103 MB） |

### 2.5 Depsgraph —— 求值引擎

关键性质是 **CoW（copy-on-write）+ 惰性求值**。实测一次 subsurf 的完整时序：

| 步骤 | 提交内存变化 |
|---|---|
| `modifiers.new("subsurf")` | **0 MB** |
| `evaluated_depsgraph_get()` | **0 MB** |
| `evaluated_get(dg)` | **0 MB** |
| **`ev.data`（首次访问求值结果）** | **+37.82 MB** |
| `len(mev.vertices)` | 0 MB |

三个语义事实：

- 原件仍是 40 000 顶点，求值副本 635 209 顶点（15.9×）→ **非破坏**
- 求值副本**不出现在 `bpy.data`**（它是 Depsgraph 私有的）
- 求值副本与原件**同名**

**这解释了为什么"改数据"不等于"看到结果"**：写入只改了 original，求值要等到有人访问。

### 2.6 Draw Manager / GPU

绘制由**显式标记**驱动，而不是自动跟随数据变化。

实测：

| 调用 | 结果 |
|---|---|
| `bpy.context.screen.tag_redraw()` | ✗ **不存在**（`AttributeError`） |
| `area.tag_redraw()` × 4 | ✓ 0.05 ms（只设标记，异步） |
| `bpy.ops.wm.redraw_timer(DRAW_WIN_SWAP, 1)` | ✓ 0.15 ms（**同步**绘制并交换缓冲） |

`bpy.data` 的直接修改**不设置重绘标记**，所以窗口会停在旧画面上直到有事件路过。这就是 `Edit(redraw=True)` 存在的原因。

**一个容易误判的点**：截图工具（`get_viewport_screenshot`）**总会**看到最新状态，因为它自己强制 draw。所以「截图能看到」**不等于**「用户能看到」——验证界面刷新只能靠人看。

### 2.7 blenloader —— .blend 读写 📖

`.blend` ≈ 内存布局 + 头/对齐。压缩（zstd，`use_file_compression=True`）在真实结构化数据上能压到 ~17%（实测空场景 0.55 MB → 0.093 MB）。

### 2.8 撤销系统（跨 wm / blenloader）

全局撤销是 **memfile 全量快照 + 环形缓冲**，不是差异记录。实测：

| 现象 | 数据 |
|---|---|
| 改网格顶点时每步快照 | **0.825 MB**（= 400k 顶点随机数据压缩到 18%） |
| 改对象变换时每步快照 | 0.36–0.88 MB（递减，不重写几何） |
| undo 回退后总量 | **15.352 MB → 15.352 MB（完全不变）** |
| 截断 redo 分支（做新操作） | **−2.958 MB**（这才是释放点） |
| 连续 45 次 push | 涨到 **30.974 MB 峰值**（第 35 步）后平台 → 对应 `undo_steps=32` |
| `undo_memory_limit` | `0` = **不限字节数，只由步数封顶** |

**结论**：撤销内存上界 ≈ `min(步数, 32) × 单步快照`；且它**不随对象删除而释放**。

---

## 3. bl-fast 的工作原理

### 3.1 三条原则

1. **批量** —— numpy 进 / numpy 出，绝不写 `for v in mesh.vertices`
2. **延迟** —— 编辑期间不碰依赖图，退出 `with` 块时一次性提交
3. **撤销单位** —— 一段编辑 = 一次 Ctrl+Z

前三条来自同一句话：**固定成本与批量大小无关，所以把它摊薄。**

第 4 条来自另一句话：**undo 不是事务，它不会自己回滚。** 所以有了 `rollback_on_error`。

### 3.2 一次 `set_positions()` 实际经过什么

```
numpy (N,3) float32
  │
  ├─ _shaped()          形状校验 —— 拦住 foreach_set 那句
  │                     "internal error setting the array"（不可操作的错误）
  ├─ _check_editable()  编辑模式守卫 —— 编辑期间几何真源是 BMesh，
  │                     直接写 mesh.vertices 会被静默丢弃
  ▼
mesh.vertices.foreach_set("co", flat)
  │
  ▼  RNA：批量 setter，一次跨界
RNA_property_float_set_array
  │
  ▼  BKE：写入属性层
CustomData layer "position"  (POINT, FLOAT_VECTOR)
  │
  ▼  DNA：float[3] × N 连续数组
一次 memcpy，全程不产生 Python 对象
```

对照：逐元素写法在每一圈都新建一个 RNA 包装对象（136.7 字节），并跨一次语言边界。

### 3.3 事务：进入时 push，失败时 undo

`Edit` 的三段行为：

| 时机 | 动作 | 依据 |
|---|---|---|
| `__enter__` | `bpy.ops.ed.undo_push()` | 实测：进入时 push 一次 + 之后连改 3 次，**一次 Ctrl+Z 恰好回到进入时状态** |
| 正常 `__exit__` | `view_layer.update()` → `_notify_ui()` | 依赖图求值 + 强制重绘 |
| 异常 `__exit__` | `bpy.ops.ed.undo()` | **借 undo 换原子性** —— 实测改到 9.0 后抛异常，回滚后读回 0.0 |

**为什么在进入时 push 而不是退出时**（这是实测发现的）：进入时 push 建立的是"编辑前状态"这个精确还原点；若只在退出时 push，异常路径会跳过它，一次 Ctrl+Z 会退到更早的地方。

**一个被实测推翻的初始判断**：本工具最初以为"不 push 就不能撤销"，实测三组对照后推翻——

```
A) 改数据、完全不 push      → undo → 回到改前值
B) 改数据、push 在后        → undo → 回到改前值
C) 编辑前 push 一次、连改 3 次 → 一次 undo → 回到起点
```

Blender 在 undo 时会把当前状态压进 redo 栈，所以 undo 栈顶**不需要**是当前状态。

### 3.4 四个安全层

| 层 | 手段 | 拦什么 | 实测 |
|---|---|---|---|
| 可撤销 | 进入时 push | 一次编辑一个撤销单位 | 3 次修改 1 次撤销 |
| 原子性 | 异常时 `undo()` | 半成品残留 | 9.0 → 0.0 |
| 可验证 | `_shaped` / 索引检查 / `validate` / `set_positions_checked` | 静默失败 | 见下 |
| 可诊断 | 错误信息带"期望 vs 实际" | AI 无法自我修复 | 见下 |

错误信息的对照：

```
拦之前： RuntimeError: internal error setting the array
拦之后： ValueError: set_positions: 期望形状 (100, 3)，实际 (100, 2)
```

**"静默失败"是本工具最重视的一类问题**，实测撞到两个：

| 场景 | 表现 |
|---|---|
| 编辑模式写 `mesh.vertices` | 编辑模式内读回 `0.0`（像成功了），**退出后读回 `12.0`** |
| 写 `evaluated.data` | `setattr` 返回 OK，但下次求值就覆盖，且不进撤销栈 |

两者都是**不报错、读回也对、结果无效**——而 AI 唯一的现实检验就是读回值。

### 3.5 反射层：`describe` / `snapshot` / `patch`

这一层直接把 §2.3 的 RNA 能力暴露给调用方。

| 函数 | 读的是 RNA 的什么 | 实测规模 |
|---|---|---|
| `describe` | `bl_rna.properties` 的 name/type/description/range/enum/subtype | 109 个可写字段，106 带文档 |
| `describe_text` | 上者的紧凑文本 | 219 行 / 11 609 字符 |
| `snapshot` | 可写且可逆字段的当前值 | 99 字段 / **2910 字节** |
| `patch` | 只写回相对 `base` 变化的字段 | 见下 |

**为什么是"变化字段"而不是全量**——实测对照：

| 同步方式 | 用户设的 rotation | AI 设的 location |
|---|---|---|
| 全量覆盖 | **被抹回 `(0,0,0)`** | `(9,9,9)` |
| **diff 应用** | **`(0.5,0,0)` 保住** | `(9,9,9)` |

`patch` 默认 `on_conflict="raise"`：先检测全部，有冲突就抛异常且**一个字段都不写**。

**几何不在这条路上**：顶点是二进制缓冲，20 万顶点文本化要 **3.2 MB / 245.5 ms**；而同样几何的**程序化描述只有 71 字节**。所以参数层走文本，几何走 numpy 通道。

---

## 4. 工具到不了的地方

全部实测。

| 限制 | 表现 |
|---|---|
| **编辑模式** | 几何真源是 BMesh，`mesh.vertices` 只是投影；写入被静默丢弃 |
| **求值副本** | `setattr` 接受但不保留 |
| **只读属性** | Object 55/164，Mesh 40/71 |
| **上下文是裸的** | `execute_code` 运行时 `area`/`region`/`space_data` 均为 `None`；`object.mode_set.poll()` 在没有活动对象时为 `false`，设了之后变 `true` |
| **渲染结果不在内存里** | `bpy.data.images["Render Result"]` 的 `size` 恒为 `[0,0]`、`pixels` 长度 0，**必须落盘再读回** |
| **模态操作** | 无法启动并用事件驱动 |
| **输入注入** | 无 API（除非 `ctypes`） |
| **中断** | `exec` 阻塞，死循环只能等（**推断**，未实测） |
| **不可进文本的** | 指针（35 个 POINTER 属性只能存名字）、Matrix、缓冲 |

### 渲染路径实测（320×240）

| 方式 | 耗时 |
|---|---|
| `bpy.ops.render.opengl(write_still=True)` | **48.9 ms** |
| `bpy.ops.render.render(write_still=True)` 首次 | **27 972.7 ms**（着色器编译） |
| 同上，第二次及以后 | **1 585.5 ms**（快 17.6×） |
| `gpu.types.GPUOffScreen` | 可用 |

---

## 5. 状态存在哪

| 载体 | 跨调用持久 | 证据 |
|---|---|---|
| `exec` 的裸变量 | ✗ | 命名空间每次新建，只预置 `bpy` |
| **模块属性**（`sys.modules`） | ✓ | 计数器 1 → 1 → 2 |
| 文件系统 | ✓ | 读写正常 |
| Blender 场景 | ✓ | — |

---

## 6. 加速比一览

| 任务 | 慢路径 | 快路径 | 加速 |
|---|---|---|---|
| 创建 200 个对象 + 随机摆放 | `bpy.ops` 逐个 **2572.05 ms** | 数据层批量 **21.49 ms** | **119.7×** |
| 100 万顶点变形 | Python 循环 **3324.90 ms**（外推） | numpy **226.17 ms** | **14.7×** |
| 建 10 万三角面网格 | `from_pydata` **447.15 ms** | numpy 直建 **86.12 ms** | **5.2×** |
| 50 次改动提交 | 逐个 `update()` **93.80 ms** | 批量一次 **1.67 ms** | **56.2×** |
| 移动 100 个对象 | `bpy.ops` 逐个 **592.57 ms** | RNA 直写 **0.55 ms** | **1077×** |

**加速比不可迁移**：120× 是"绕开 ops 省下的开销 ÷ 该任务实际计算量"，同一套代码建网格只有 5.2×。

**代价也必须记**：`mesh_from_arrays(validate=True)` 让建 10 万三角面从 **72.5 ms 变成 100.3 ms（+38.5%）**。

---

## 7. 一句话总结

> **Blender 把"操作"和"状态"分得很开**：`bpy.ops` 走的是 wm 那一整套（撤销快照 + 依赖图 + 上下文校验），而 `bpy.data` + RNA 的批量通道直接落到 BKE/DNA。
> **本工具的全部价值就是**：把编辑走数据层（省掉记账）、把边界批量过（省掉跨语言税）、把提交延后到一次（省掉重复求值），**然后补回被绕掉的安全网**（撤销单位、失败回滚、形状/拓扑校验、冲突检测、界面刷新）。

---

## 8. 这些数字怎么复现

环境：Blender 5.2.1 LTS Release，内嵌 Python 3.13.13，numpy 2.3.4，Windows 10。

```python
# 进程内存（Windows）；Linux/macOS 请换成对应读数
import ctypes
class PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
_k32 = ctypes.WinDLL("kernel32.dll"); _psapi = ctypes.WinDLL("psapi.dll")
_k32.GetCurrentProcess.restype = ctypes.c_void_p; _k32.GetCurrentProcess.argtypes = []
_psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
_psapi.GetProcessMemoryInfo.restype = ctypes.c_int

def priv_MB():
    c = PMC(); c.cb = ctypes.sizeof(c)
    _psapi.GetProcessMemoryInfo(_k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.PagefileUsage / 2**20, 2)

# 撤销内存（Blender 自己暴露的，单位是字节）
bpy.app.memory_usage_undo()

# RNA schema
len(bpy.data.objects["Cube"].bl_rna.properties)
```

**两条方法学提醒**（都是踩过的坑）：

1. **用提交内存（`PagefileUsage`），不要用工作集**。实测工作集从 808 MB *下降*到 642 MB（Windows 裁掉空闲页），甚至出现 priv 1086 / ws 309 的倒挂。
2. **单次测量方差很大**。同一基准先后跑出 21.49 ms 与 10.22 ms；小档位（10 万/20 万顶点）会因堆里已有空闲块而出现**负增长**。所以本文的数字应当读作**量级**，不是精确值。
