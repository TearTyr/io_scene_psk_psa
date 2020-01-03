import bpy
import bmesh
from .data import *


class PskBuilder(object):
    def __init__(self):
        # TODO: add options in here
        pass

    def build(self, context) -> Psk:
        mesh_object = context.view_layer.objects.active

        if mesh_object.type != 'MESH':
            raise RuntimeError('Selected object must be a mesh')

        if len(mesh_object.data.materials) == 0:
            raise RuntimeError('Mesh must have at least one material')

        # ensure that there is exactly one armature modifier
        modifiers = [x for x in mesh_object.modifiers if x.type == 'ARMATURE']

        if len(modifiers) != 1:
            raise RuntimeError('Mesh must have one armature modifier')

        armature_modifier = modifiers[0]
        armature_object = armature_modifier.object

        if armature_object is None:
            raise RuntimeError('Armature modifier has no linked object')

        # Create a copy of the mesh data with all modifiers applied
        depsgraph = bpy.context.view_layer.depsgraph
        depsgraph.update()
        mesh_object = mesh_object.evaluated_get(depsgraph)
        mesh_data = bpy.data.meshes.new_from_object(mesh_object, depsgraph=depsgraph)

        # Triangulate the mesh
        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        bm.to_mesh(mesh_data)
        bm.free()
        del bm

        psk = Psk()

        # VERTICES
        for vertex in mesh_data.vertices:
            point = Vector3()
            point.x = vertex.co.x
            point.y = vertex.co.y
            point.z = vertex.co.z
            psk.points.append(point)

        # WEDGES
        uv_layer = mesh_data.uv_layers.active.data
        if len(mesh_data.loops) <= 65536:
            wedge_type = Psk.Wedge16
        else:
            wedge_type = Psk.Wedge32
        psk.wedges = [wedge_type() for _ in range(len(mesh_data.loops))]

        for loop_index, loop in enumerate(mesh_data.loops):
            wedge = psk.wedges[loop_index]
            wedge.material_index = 0
            wedge.point_index = loop.vertex_index
            wedge.u, wedge.v = uv_layer[loop_index].uv
            wedge.v = 1.0 - wedge.v
            psk.wedges.append(wedge)

        # MATERIALS
        for i, m in enumerate(mesh_data.materials):
            if m is None:
                raise RuntimeError(f'Mesh material slots cannot be empty (see material slot {i})')
            material = Psk.Material()
            material.name = bytes(m.name, encoding='utf-8')
            material.texture_index = i
            psk.materials.append(material)

        # FACES
        # TODO: this is making the assumption that the mesh is triangulated
        mesh_data.calc_loop_triangles()
        poly_groups, groups = mesh_data.calc_smooth_groups(use_bitflags=True)
        for f in mesh_data.loop_triangles:
            face = Psk.Face()
            face.material_index = f.material_index
            face.wedge_index_1 = f.loops[2]
            face.wedge_index_2 = f.loops[1]
            face.wedge_index_3 = f.loops[0]
            face.smoothing_groups = poly_groups[f.polygon_index]
            psk.faces.append(face)
            # update the material index of the wedges
            for i in range(3):
                psk.wedges[f.loops[i]].material_index = f.material_index

        # https://github.com/bwrsandman/blender-addons/blob/master/io_export_unreal_psk_psa.py
        bones = list(armature_object.data.bones)
        for bone in bones:
            psk_bone = Psk.Bone()
            psk_bone.name = bytes(bone.name, encoding='utf-8')
            psk_bone.flags = 0
            psk_bone.children_count = len(bone.children)

            try:
                psk_bone.parent_index = bones.index(bone.parent)
            except ValueError:
                psk_bone.parent_index = 0

            if bone.parent is not None:
                rotation = bone.matrix.to_quaternion()
                rotation.x = -rotation.x
                rotation.y = -rotation.y
                rotation.z = -rotation.z
                quat_parent = bone.parent.matrix.to_quaternion().inverted()
                parent_head = quat_parent @ bone.parent.head
                parent_tail = quat_parent @ bone.parent.tail
                location = (parent_tail - parent_head) + bone.head
            else:
                location = armature_object.matrix_local @ bone.head
                rot_matrix = bone.matrix @ armature_object.matrix_local.to_3x3()
                rotation = rot_matrix.to_quaternion()

            psk_bone.location.x = location.x
            psk_bone.location.y = location.y
            psk_bone.location.z = location.z

            psk_bone.rotation.x = rotation.x
            psk_bone.rotation.y = rotation.y
            psk_bone.rotation.z = rotation.z
            psk_bone.rotation.w = rotation.w

            psk.bones.append(psk_bone)

        # WEIGHTS
        # TODO: bone ~> vg might not be 1:1, provide a nice error message if this is the case
        armature = armature_object.data
        bone_names = [x.name for x in armature.bones]
        vertex_group_names = [x.name for x in mesh_object.vertex_groups]
        bone_indices = [bone_names.index(name) for name in vertex_group_names]
        for vertex_group_index, vertex_group in enumerate(mesh_object.vertex_groups):
            bone_index = bone_indices[vertex_group_index]
            for vertex_index in range(len(mesh_data.vertices)):
                try:
                    weight = vertex_group.weight(vertex_index)
                except RuntimeError:
                    continue
                if weight == 0.0:
                    continue
                w = Psk.Weight()
                w.bone_index = bone_index
                w.point_index = vertex_index
                w.weight = weight
                psk.weights.append(w)

        # Remove temporary mesh data
        bpy.data.meshes.remove(mesh_data)

        return psk
