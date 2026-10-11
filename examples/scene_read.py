import bpy

cube = bpy.data.objects.get("Cube")
print(cube,type(cube))

print("bpy.data.objects:")
for i in bpy.data.objects:
    print(i)

print("cube.bl_rna.properties内容")
for i in cube.bl_rna.properties:
    print(i)

"""
print("bpy.data内容")
print(bpy.data)
for i in bpy.data:
    print(i)
"""

print("下面是场景内容输出：")
for i in bpy.data.objects:
    print(i.name,i.id_type,i.type,i.parent,i.location)