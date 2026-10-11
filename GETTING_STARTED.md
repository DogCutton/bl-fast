# 上手：在 VSCode 里操作 Blender

写给想自己动手的人。**三条路**，按"从零到跑通"排序。

---

## 0. 你的环境（已实测确认）

| | |
|---|---|
| VSCode | 1.140.0（`D:\Microsoft VS Code`） |
| **`jacqueslucke.blender-development`** | ✅ **0.0.31 已装** —— Blender 官方推荐的那套 VSCode 集成 |
| Python 三件套 | `ms-python.python` / `pylance` / `debugpy` ✅ |
| Blender | `E:\制冰\Blender\Blender 5.2\blender.exe`（5.2.1 LTS） |
| Blender 自带 Python | `...\5.2\python\bin\python.exe`（3.13.13） |

**所以不需要再装任何东西**，直接开始。

---

## 1. 三条路，先选一条

| 路径 | 需要什么 | 适合 |
|---|---|---|
| **A. VSCode 扩展** | 已装好 | **学习首选**：补全 + 断点 + 改完就发 |
| B. Blender 内建 Scripting | 无 | 零配置，临时试验 |
| C. 命令行无头 | 无 | 批处理 / 自动化 |

### 路径 A：VSCode 扩展（推荐）

**① 用 VSCode 打开项目文件夹**

```
File → Open Folder → F:\DeepSeek Harness Workspace\tools\bl-fast
```

打开后 `.vscode/settings.json` 自动生效——里面已经写好了你这台机器的 Blender 路径。

**② 启动 Blender**

```
Ctrl+Shift+P  →  输入 "Blender: Start"  →  回车
```

会弹出一个**新的 Blender 窗口**（由扩展管理，带调试端口）。

> ⚠️ 这是**独立于你手动开的那个 Blender**。两者互不干扰，可以同时存在。

**③ 跑第一个练习**

打开 `examples/01_first_look.py`，然后：

```
Ctrl+Shift+P  →  "Blender: Run Script"
```

**输出出现在 VSCode 的终端里**（不是 Blender 的控制台）——这点比路径 B 方便很多。

**④ 改代码 → 再跑**

直接再 `Blender: Run Script` 即可，**不用重启 Blender**。

**为什么推荐 A**：输出可滚动可搜索；能下断点（`F9`）单步调试；脚本在磁盘上，可以 git 管理。

### 路径 B：Blender 内建（零配置）

1. Blender 顶部工作区 → **"脚本"**
2. 中间是 Text Editor → 新建 → 粘贴代码
3. **`Alt+P`** 运行
4. 看输出：**Window → Toggle System Console**（Windows 上默认不显示，必须手动开）

适合临时试一句：

```python
print(bpy.data.objects["Cube"].location[:])
```

### 路径 C：命令行无头

```powershell
& "E:\制冰\Blender\Blender 5.2\blender.exe" --background --factory-startup --python "脚本路径.py"
```

`--factory-startup` 会禁用所有插件——干净环境，适合验证"脚本本身有没有偷偷依赖某个插件"。

---

## 2. bl_fast 怎么加载

每个练习脚本开头都是这几行：

```python
import sys
BL_FAST = r"F:\DeepSeek Harness Workspace\tools\bl-fast"
if BL_FAST not in sys.path:
    sys.path.append(BL_FAST)
import bl_fast as bf
```

**为什么不 pip 安装**：bl_fast 依赖 `bpy`，而 `bpy` **只在 Blender 进程内存在**，不在任何
标准 Python 路径里。所以它只能"在 Blender 里"被导入——靠 `sys.path` 指到磁盘上的文件夹。

---

## 3. 四个练习

| 文件 | 学什么 |
|---|---|
| `examples/01_first_look.py` | 读会话身份 + 读 schema（不背 API） |
| `examples/02_batch_edit.py` | 批量 vs 逐个，实测差多少倍 |
| `examples/03_materials_and_media.py` | 代码建节点树 + 贴外部图片/视频 |
| `examples/04_safe_edit.py` | 事务 / 回滚 / 形状校验 / 冲突检测 |

---

## 4. 第一个真正的练习（自己写）

在 Python Console 或 VSCode 脚本里逐条试。**重点是第 3 步和第 4 步的差别**：

```python
import bpy

# 1) 看
print([o.name for o in bpy.data.objects])

# 2) 读
cube = bpy.data.objects["Cube"]
print(cube.location[:])
print(cube.bl_rna.properties["location"].description)   # 它是什么意思

# 3) 写 —— 注意：这一步之后窗口不会立刻变！
cube.location = (3, 0, 0)
print(cube.location[:])          # 数据确实变了

# 4) 通知 —— 窗口这时才变
bpy.context.view_layer.update()

# 5) 撤销
bpy.ops.ed.undo()
```

**"改了值"和"看见变化"是两件独立的事。** 这就是整个 Blender 架构的核心。
（详见 [BLENDER_ARCHITECTURE.md](BLENDER_ARCHITECTURE.md) 第 0 节）

---

## 5. 调试

### 看输出
- 路径 A → VSCode 终端
- 路径 B → **Window → Toggle System Console**（Windows 上关键！）
- 路径 C → 命令行

### 看报错
Blender 的 traceback 是完整的。**真正的原因通常在最后几行**，别只看第一行。

### 下断点（路径 A）
1. `Blender: Start` 启动的实例带调试端口
2. 在 `.py` 里点行号左侧设断点（`F9`）
3. `Blender: Run Script` → 会停在断点
4. 用 VSCode 的调试面板看变量

### "我改了但没反应"——按顺序查这三步

| 检查 | 怎么做 |
|---|---|
| 1. 数据改了吗？ | `print(...)` 读回来 |
| 2. 依赖图更新了吗？ | `bpy.context.view_layer.update()` |
| 3. 界面刷新了吗？ | 用 `bf.Edit(...)`，或手动 `area.tag_redraw()` |

---

## 6. 几个必须知道的坑（都是实测撞出来的）

| 坑 | 说明 |
|---|---|
| **`node.name` 会变** | 随界面语言变（中文下是「原理化 BSDF」）。定位节点用 `node.type` 或 socket 名 |
| **枚举是动态的** | 想输出视频必须先 `image_settings.media_type = "VIDEO"`，否则 `FFMPEG` 被拒 |
| **RNA 值类型不可预测** | `p.type` 说是 FLOAT，运行时可能是 `bytes` / `Vector` / `IDPropertyGroup` |
| **内存看提交量，不看工作集** | 工作集会被系统裁掉，能测出"负增长" |
| **无头模式下 `undo` 不可用** | `bpy.ops.ed.undo.poll()` 为 False——回滚能力**必须先探测**，不能假设 |
| **撤销栈清不掉** | 操作一旦进去就留在那里。**动手前先让文件存盘** |
| **undo 之后别再用手里的引用** ⚠️ | 实测：`undo()` 后复用缓存的 `bpy` 引用，会**静默读到陈旧值**（或抛 `ReferenceError: StructRNA ... has been removed`）。读值时用 `bpy.data.objects["Cube"]` 重新取 |
| **`bpy.ops` 在脚本里常 poll 失败** | 不是"做不到"，是"先搭桥"：设活动对象，或用 `temp_override` |

---

## 7. 补全（可选）

VSCode 里 `import bpy` 默认**没有补全**，因为 `bpy` 不在任何标准路径上。

要补全得装类型存根（社区维护）：

```powershell
# 按你的 Blender 版本选（推荐，精确匹配）
pip install fake-bpy-module-5.2
```

> **已实测**（Blender 5.2.1 + 它自带的 pip 26.0.1）：
>
> - **按版本发布的包存在且精确**：`fake-bpy-module-5.2`（最新 `20260730`）
> - `fake-bpy-module-latest` 也更新到 `20261010`，但它跟随**最新** Blender
> - 实际装进去的确实是 5.2 那一份：**45 个 `*-stubs` 目录**（bpy / bmesh / mathutils / gpu / ...），
>   抽查 `attributes` / `GeometryNodeTree` / `interface` / `color_attributes` **全部存在**
>
> ⚠️ 两个坑（都踩过）：
>
> 1. **pip 走自己的 HTTP 栈，会被 Steam++ 这类 TLS 中间人挡住** —— 表现为 `HTTP 403`
>    （索引页能读，但下载 wheel 被拒）。绕法：用 PowerShell 从 `files.pythonhosted.org`
>    直接下 wheel，再 `pip install --no-index <本地 wheel>`。
> 2. **wheel 的文件名是元数据，不能改**。改成别的名字会报
>    `Invalid wheel filename (wrong number of parts)`。
> （实测：清华镜像的**索引页能读，但下 wheel 时返回 403**；这次是从官方 PyPI 下成功的。
> 所以上面那条命令故意不带镜像参数。）

**不装也完全能开发**——用第 4 节的写法在运行时查：

```python
for p in cube.bl_rna.properties:
    print(p.identifier, p.type, p.is_readonly, p.description)
```

Blender 的 RNA 里 **97% 的可写字段自带文档**，比任何补全都可靠。

---

## 8. 和 MCP 那条路的关系

你之前看到的是"AI 通过 MCP 操作 Blender"。那是**另一条独立通道**：

| | MCP 通道 | 本文的 VSCode 通道 |
|---|---|---|
| 谁在写代码 | AI | **你自己** |
| 代码在哪 | 会话里，不落盘 | **磁盘上的 `.py`**，可 git |
| Blender 实例 | 你手动开的那个 | 扩展启动的那个 |
| 输出在哪 | AI 那边 | **你的终端** |

**两者可以同时存在**——一个 Blender 给 AI 用，一个给你自己用。`bl_fast` 两边都能跑，
因为它只依赖 `bpy`（这一点用 `--factory-startup` 的独立进程验证过）。
