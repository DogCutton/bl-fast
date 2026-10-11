# -*- coding: utf-8 -*-
"""练习 3：用代码建一棵材质节点树，并把外部图片贴上去。

全程不碰 UI —— 节点编辑器的内容本质上是数据。
"""

import os
import sys
import bpy

try:
    import os.path as _osp
    _ROOT = _osp.dirname(_osp.dirname(_osp.abspath(__file__)))
except NameError:          # Blender 的 Text Editor 里没有 __file__
    _ROOT = r"F:\DeepSeek Harness Workspace\tools\bl-fast"
if _ROOT not in sys.path:
    sys.path.append(_ROOT)
import bl_fast as bf

# 换成你自己的图片路径
IMAGE = r"F:\DeepSeek Harness Workspace\Workspace 4\render_eevee.png"

with bf.Edit("练习：建材质 + 贴图"):

    # ---------------------------------------------------------- 1) 材质与节点树
    mat = bpy.data.materials.new("EXAMPLE_MAT")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()                       # 清掉默认的两个节点

    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapn = nt.nodes.new("ShaderNodeMapping")

    for n, (x, y) in ((coord, (-500, 0)), (mapn, (-250, 0)), (tex, (0, 0)),
                      (bsdf, (300, 0)), (out_node, (600, 0))):
        n.location = (x, y)

    nt.links.new(coord.outputs["UV"], mapn.inputs["Vector"])
    nt.links.new(mapn.outputs["Vector"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    print("节点 (%d 个):" % len(nt.nodes))
    for n in nt.nodes:
        print("    %-14s type=%-18s" % (n.name, n.type))
    print("连接 (%d 条):" % len(nt.links))
    for l in nt.links:
        print("    %s.%s -> %s.%s" % (l.from_node.type, l.from_socket.name,
                                      l.to_node.type, l.to_socket.name))

    # ---------------------------------------------------------- 2) 外部图片
    print()
    if os.path.exists(IMAGE):
        img = bpy.data.images.load(IMAGE, check_existing=True)
        tex.image = img
        print("图像已接上:", img.name, "| source=%s" % img.source,
              "| size=%s" % list(img.size), "| colorspace=%s" % img.colorspace_settings.name)
    else:
        print("找不到:", IMAGE)
        print("把脚本顶部的 IMAGE 改成你自己的图片路径")

    # ---------------------------------------------------------- 3) 挂到 Cube
    cube = bpy.data.objects["Cube"]
    cube.data.materials.clear()
    cube.data.materials.append(mat)
    print()
    print("已挂到", cube.name, "->", [m.name for m in cube.data.materials])

print()
print("=" * 62)
print("要点")
print("=" * 62)
print("  · 定位节点用 node.type（BSDF_PRINCIPLED / TEX_IMAGE），")
print("    或用 socket 名（\"Base Color\" / \"Vector\"）")
print("  · 绝不要用 node.name —— 它随界面语言变（中文界面下是「原理化 BSDF」）")
print("  · 视频/序列也是同一个 API：")
print("      bpy.data.images.load(\"clip.mp4\")   -> source = MOVIE")
print("      img.source = \"SEQUENCE\"            -> 图像序列")
print()
print("回退：把材质换成原来那个，用")
print("    cube.data.materials.clear(); cube.data.materials.append(bpy.data.materials['Material'])")
