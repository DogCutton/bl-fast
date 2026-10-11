## bl-fast v{{VERSION}}

面向 **AI 代码编辑**的 Blender 高速批量编辑原语库。

一句话：**让 AI 写一段代码一次提交，而不是对每个对象调用一次工具。**

---

### 安装

**方式一：在 Blender 里运行安装脚本（推荐，跨平台）**

1. 解压附件 `{{ASSET}}`
2. Blender → 顶部工作区切到 **「脚本」** → Text Editor → 打开 `install.py` → **`Alt+P`**

**方式二：Windows 一行命令**

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

安装 = 把 `bl_fast.py` 复制进 Blender 的 `scripts/modules`（那个目录**本来就在 `sys.path` 里**）。
**零依赖**（`bpy` 和 `numpy` 都是 Blender 自带的），**卸载就是删掉那个文件**。

装完在**任何** Blender 脚本里直接用：

```python
import bl_fast as bf
```

> ⚠️ 验证时**不要**加 `--factory-startup` —— 那个参数会**排除用户脚本目录**，
> 于是装好的库反而找不到。详见 `INSTALL.md`。

---

### 这个版本包含

| 文件 | 作用 |
|---|---|
| `bl_fast.py` | 库本体：批量原语 + 事务 + 校验 + 反射接口 |
| `install.py` / `install.ps1` / `uninstall.ps1` | 安装与卸载 |
| `verify_architecture.py` | 把文档里标 ✅ 的架构声明变成**可重跑**的检查 |
| `examples/01–04` | 四个由易到难的练习（批量提速 / 节点树 / 事务安全网） |
| `README.md` | 怎么用 + **AI 是怎么编辑 Blender 的** |
| `ARCHITECTURE.md` | 工具原理，以及它穿过的 Blender 各层（九跳逐跳给证据） |
| `BLENDER_ARCHITECTURE.md` | Blender 本身怎么运作（学习用，独立成篇） |
| `GETTING_STARTED.md` | 上手：三条路（VSCode 扩展 / 内建脚本 / 命令行） |
| `INSTALL.md` | 安装说明与常见问题 |
| `.vscode/settings.json` | VSCode 通用配置（**不含**机器特定路径，原因见 INSTALL.md） |

---

### 验证状态

**架构声明**（`blender.exe --background --factory-startup --python verify_architecture.py`）

| | 声明 | 结果 |
|---|---|---|
| §1.1 | 所有顶层数据都是 ID | ✅ 38 个 ID 全是 `bpy.types.ID` |
| §1.2 | Main 是数据库 | ✅ `bpy.data` 有 40 张表 |
| §2.2 | RNA 同时服务 Python / UI / 动画 / 驱动 | ✅ 四者解析到同一 identifier |
| §5.1 | 撤销是全量快照 | ✅ 改 1 顶点与改 20000 顶点，快照都是 ~1.3 MB |
| §7.1 | `.blend` ≈ 内存转储 | ✅ 压缩率 16.9% |
| §8.1 | 一套 NodeTree 框架 | ✅ 5 个类共享 API |
| §9.1 | CPython 内嵌 | ✅ 3.13.13，12 个普通模块可用 |
| §6.2 | GHOST 的位置 | 📖 **只能间接验证**（Python 侧完全看不到它） |

**安装**：在 Blender 5.1 / 5.2 上实测；**全新会话**里 `import bl_fast` 从安装位置加载。

**分发**：解压到任意位置都能独立运行（`bl_fast.__file__` 指向解压位置，不依赖原路径）。

---

### 校验

```
SHA256  {{SHA256}}
```

---

### 许可

MIT © 2026 [DogCutton](https://github.com/DogCutton) —— 见 `LICENSE`。

自由使用、修改、分发（含商用），只需保留版权声明。
