# 安装 bl-fast

## 先说清楚：它是什么形式的"包"

bl-fast 是一个**依赖 `bpy` 的 Python 库**，而 `bpy` **只在 Blender 进程内存在**。

所以它**不能**用普通的 `pip install` 装到一个独立的 Python 里——那个 Python 里根本没有 `bpy`。

**唯一的安装方式：把 `bl_fast.py` 放进 Blender 自己的 `sys.path` 里。**

而 Blender 有一个专门放这类脚本的目录，它**本来就在 `sys.path` 里**：

```
%APPDATA%\Blender Foundation\Blender\<版本>\scripts\modules\
```

把 `bl_fast.py` 复制进去，**任何** Blender 脚本就能 `import bl_fast`。

> 这是一个**单文件库**：安装 = 复制一个文件，卸载 = 删掉一个文件。
> 不写注册表、不改偏好、不装任何依赖（`bpy` 和 `numpy` 都是 Blender 自带的）。

---

## 安装（两种方式，任选）

### 方式 1：在 Blender 里运行 `install.py` —— **推荐，跨平台**

1. 打开 Blender
2. 顶部工作区切到 **"脚本"**
3. Text Editor → **打开**（`Alt+O`）→ 选本目录里的 `install.py`
4. **`Alt+P`** 运行
5. 看输出：**`Window → Toggle System Console`**（Windows 上默认不显示）

它会自己找到正确的目录、复制、**并当场验证一次导入**。

### 方式 2：PowerShell 一键 —— Windows

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

它会扫描 `%APPDATA%\Blender Foundation\Blender\` 下的**所有版本**，逐个安装。

> ⚠️ `install.ps1` 的输出是**纯英文**——这不是偷懒。Windows PowerShell 5.1 在读取
> **无 BOM** 的 `.ps1` 时按系统代码页（这里是 GBK）解码，中文会变成乱码。
> 中文说明就是本文档。

---

## 验证

> ⚠️ **不要用 `--factory-startup` 验证** —— 这个参数会**排除用户脚本目录**，
> 于是装好的库反而找不到。实测对比：
>
> | 启动方式 | 用户 `scripts\modules` 在 `sys.path`？ | `import bl_fast` |
> |---|---|---|
> | `--background` | ✅ 在 | ✅ 成功 |
> | `--background --factory-startup` | ❌ **不在** | ❌ 失败 |
>
> 验证请用**正常的 Blender**（GUI，或 `--background` 不带 factory-startup）。

在 Blender 的 **Python Console**（脚本工作区左下角）里输：

```python
import bl_fast as bf
print(bf.__file__)
```

应该打印出 `...\scripts\modules\bl_fast.py`。

再试个真的：

```python
import bpy, bl_fast as bf
cube = bpy.data.objects["Cube"]
print(len(bf.snapshot(cube)))          # 大约 99
print(bf.describe_text(cube)[:120])    # 前几行能力清单
```

---

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

或者手动删掉那个 `bl_fast.py`。**就这一步。**

---

## 装完之后

| 想干什么 | 去哪 |
|---|---|
| 在 Blender 里直接用 | `import bl_fast`（不用再 `sys.path.append`） |
| 在 VSCode 里写脚本 | 见 [GETTING_STARTED.md](GETTING_STARTED.md) |
| 理解它为什么这样设计 | 见 [ARCHITECTURE.md](ARCHITECTURE.md) |
| 学 Blender 本身怎么工作 | 见 [BLENDER_ARCHITECTURE.md](BLENDER_ARCHITECTURE.md) |
| **不装也能用** | 每个练习脚本都支持"就地运行"（自己找同目录的库） |

---

## 常见问题

**Q：我有多个 Blender 版本，会装到哪个？**

`install.ps1` 装到**所有**找到的版本；`install.py` 装到你**运行它的那一个**版本。

**Q：复制进去了，`import bl_fast` 还是失败？**

按顺序查三点：

1. 目录是 `<版本>\scripts\**modules**\` 吗？（**不是** `addons`——那是插件目录，语义不同）
2. 在 Blender 里跑 `import sys; print([p for p in sys.path if "modules" in p])`，
   确认那个目录**确实在 `sys.path` 里**
3. 文件名是 `bl_fast.py` 吗（不是 `bl-fast.py`——Python 模块名不能带连字符）

**Q：为什么不做成 pip 包或者 Blender 扩展？**

- **pip 包**：可以做，但要装进 **Blender 自带的 Python** 才有意义：
  ```powershell
  & "E:\制冰\Blender\Blender 5.2\5.2\python\bin\python.exe" -m pip install <wheel>
  ```
  这条路径**我们没验证过**（本机那份 pip 的状态不明确），而"复制一个文件"已经足够可靠。
- **Blender 扩展**：扩展会被加载成 `bl_ext.<repo>.<id>`，**裸 `import bl_fast` 不保证能用**
  （除非扩展内部改 `sys.path`）。对本项目来说是绕远路。

选择"复制到 `scripts/modules`"的理由很简单：**那个目录已经在 `sys.path` 里**，
所以它是最短、最可预测的路径，而且卸载就是删一个文件。

---

## 本机实测记录

安装脚本在这台机器上跑过，结果如下（Blender 5.2.1 LTS）：

```
Blender config root : C:\Users\02008\AppData\Roaming\Blender Foundation\Blender
Source              : ...\bl-fast\bl_fast.py

  [OK] Blender 5.2  ->  C:\Users\02008\AppData\Roaming\Blender Foundation\Blender\5.2\scripts\modules\bl_fast.py

Installed into 1 Blender version(s).
```

安装后在一个**全新的** Blender 进程里（没有手动改过 `sys.path`）验证了
`import bl_fast` 与 `bf.snapshot()` 都可用。

**同一件事的两次对比** —— 这是本次最值得记的一条：

```
A) blender --background --factory-startup
   sys.path 里的 modules 目录只有 3 个 —— 用户级那个不在
   -> ModuleNotFoundError: No module named 'bl_fast'

B) blender --background          （不带 factory-startup）
   sys.path 里有 5 个，第一项就是用户级 scripts\modules
   -> IMPORT_OK: ...\Blender\5.2\scripts\modules\bl_fast.py
```

**`--factory-startup` 会排除用户脚本目录** —— 所以它既是「干净环境」的好工具，
也是「验证安装」的坏工具。这两个场景要分开用。

顺带解释了为什么两种使用方式要并存：**装了**走正常启动的 Blender；
**没装**就靠脚本里的 `sys.path.append`（那个在任何模式下都有效，包括 factory-startup）。
