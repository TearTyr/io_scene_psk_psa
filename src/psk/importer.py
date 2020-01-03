import bpy
import mathutils
from .data import *
import os
import bmesh


class PskImporter(object):
    def __init__(self):
        pass

    def import_(self, context, psk: Psk, name: str):
        scene = bpy.context.scene

        # bpy.ops.object.mode_set(mode='OBJECT')
        # ARMATURE

        armature = bpy.data.armatures.new(name=name)
        armature_object = bpy.data.objects.new(name, armature)
        scene.collection.objects.link(armature_object)

        # BONES
        bpy.context.view_layer.objects.active = armature_object
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        edit_bones = armature.edit_bones
        for i, psk_bone in enumerate(psk.bones):
            # Create the bone matrix
            location = mathutils.Vector((psk_bone.location.x, psk_bone.location.y, psk_bone.location.z))
            translation_matrix = mathutils.Matrix.Translation(location)
            rotation = mathutils.Quaternion((psk_bone.rotation.w, psk_bone.rotation.x, psk_bone.rotation.y, psk_bone.rotation.z))
            rotation_matrix = rotation.to_matrix().to_4x4()
            bone_matrix = rotation_matrix @ translation_matrix

            bone = edit_bones.new(psk_bone.name.decode('utf-8'))
            bone.head = (0, 0, 0)
            bone.tail = (0, 0, 1)
            if psk_bone.parent_index >= 0 and psk_bone.parent_index != i:
                bone.parent = edit_bones[psk_bone.parent_index]
            bone.matrix = bone_matrix
        bpy.ops.object.mode_set(mode='OBJECT')

        # MESH
        mesh = bpy.data.meshes.new(name=name)
        mesh_object = bpy.data.objects.new(name, mesh)
        scene.collection.objects.link(mesh_object)

        # MATERIALS
        mesh.uv_layers.new()
        for i, psk_material in enumerate(psk.materials):
            texture = bpy.data.textures.new(psk_material.name.decode('utf-8'), type='IMAGE')
            material = bpy.data.materials.new(psk_material.name.decode('utf-8'))
            material.use_nodes = True
            mesh.materials.append(material)

            # TODO: some sort of way to better organize the nodes would be helpful
            bsdf = material.node_tree.nodes["Principled BSDF"]
            texture_image = material.node_tree.nodes.new('ShaderNodeTexImage')
            material.node_tree.links.new(bsdf.inputs['Base Color'], texture_image.outputs['Color'])
            texture_image.image = texture.image

        # VERTEX GROUPS
        for i, psk_bone in enumerate(psk.bones):
            vertex_group = mesh_object.vertex_groups.new(name=psk_bone.name.decode('utf-8'))

        # WEDGES
        bm = bmesh.new()
        bm.from_mesh(mesh)

        for point in psk.points:
            bm.verts.new((point.x, point.y, point.z))

        bm.verts.ensure_lookup_table()

        # TODO: somehow get the smoothing group info incorporated (edge split modifiers, maybe?)
        for i, psk_face in enumerate(psk.faces):
            wedges = psk.wedges[psk_face.wedge_index_1], \
                     psk.wedges[psk_face.wedge_index_2], \
                     psk.wedges[psk_face.wedge_index_3]
            vertex_indices = [w.point_index for w in wedges]
            face = bm.faces.new([bm.verts[x] for x in vertex_indices])
            face.smooth = True
            face.material_index = psk_face.material_index

        bm.faces.ensure_lookup_table()

        bm.to_mesh(mesh)

        # TEXTURE COORDINATES
        uv_texture = mesh.uv_layers[0]
        uv_texture.active_render = True

        for i, psk_face in enumerate(psk.faces):
            wedges = psk.wedges[psk_face.wedge_index_1], \
                     psk.wedges[psk_face.wedge_index_2], \
                     psk.wedges[psk_face.wedge_index_3]
            for j, wedge in enumerate(wedges):
                uv_texture.data[i * 3 + j].uv = (wedge.u, 1.0 - wedge.v)

        # TODO: handle smoothing groups!
        # TODO: edit mode!
        # bpy.context.view_layer.objects.active = mesh_object
        # bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        # bm = bmesh.from_edit_mesh(mesh)
        # bm.edges.ensure_lookup_table()
        # for i, edge_key in enumerate(mesh.edge_keys):
        #     if psk.faces[edge_key[0]].smoothing_groups & \
        #        psk.faces[edge_key[1]].smoothing_groups == 0:
        #         # edge splits along faces with mismatching smoothing groups, mark this edge as sharp!
        #         bm.edges[i].smooth = False
        # bmesh.update_edit_mesh(mesh, False, False)
        # bpy.ops.object.mode_set(mode='OBJECT')

        # TODO: WEIGHTS

        mesh.validate(clean_customdata=False)
        mesh.update(calc_edges=False)

        # ARMATURE MODIFIER
        mesh_object.parent = armature_object
        armature_modifier = mesh_object.modifiers.new('Armature', 'ARMATURE')
        armature_modifier.object = armature_object
