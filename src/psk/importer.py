import bpy
import mathutils
from .data import *
import bmesh
import os


class PskImporter(object):
    def __init__(self):
        pass

    '''
    There are a couple of scenarios that we need to "fix" so that the model can be imported in its entirety.
    
    First off, PSKs exported out of umodel technically contain degenerate faces, where 2 of the "wedges" point to
    the same vertex (eg. a triangle with vertices [A A B]). This is not a valid polygon and therefore cannot
    be imported directly. The solution here is to replace all duplicate vertex indices with a copy of the duplicated
    vertex (eg. [A A B] ~> [A Z B] where Z is a new vertex that is a copy of A)
    
    The next problem is that there are duplicate faces in exports coming out of the PSK. For example, one of the faces
    may be [A, B, C], and another is [B, C, A] (or even just [A, B, C]). This is effectively the same face, and Blender
    understandably disallows this. This is likely related, in some way to the previous problem, and the solution is
    nearly the same: duplicate one of the vertices to make the face "unique". We need to be able to "hash" the faces
    regardless of winding order.
    
    TODO: note that the hashing mechanism 
    '''
    def fix_degenerate_geometry(self, psk):
        def replace_vertices(vertex_indices: List[int]):
            yield False
            yield vertex_indices[1] == vertex_indices[0]
            yield vertex_indices[2] == vertex_indices[0] or vertex_indices[2] == vertex_indices[1]
        # TODO: ensure that the same vertices are not used on a per-face basis (create new duplicate vertices)
        face_hashes = set()
        for psk_face in psk.faces:
            wedges = psk.wedges[psk_face.wedge_index_1], \
                     psk.wedges[psk_face.wedge_index_2], \
                     psk.wedges[psk_face.wedge_index_3]
            vertex_indices = [w.point_index for w in wedges]
            if len(set(vertex_indices)) < 3:
                for i, should_replace in enumerate(replace_vertices(vertex_indices)):
                    if should_replace:
                        point = psk.points[vertex_indices[i]]
                        new_point = Vector3()
                        new_point.x = point.x
                        new_point.y = point.y
                        new_point.z = point.z
                        wedges[i].point_index = len(psk.points)
                        psk.points.append(new_point)
            # Find the lowest value and choose a pivot point
            min_vertex_index = min(vertex_indices)
            pivot_index = vertex_indices.index(min_vertex_index)
            vertex_indices = [vertex_indices[i % 3] for i in range(pivot_index, pivot_index + 3)]
            face_hash = (vertex_indices[0] & 0x1FFFFF) | ((vertex_indices[1] & 0x1FFFFF) << 21) | ((vertex_indices[2] & 0x1FFFFF) << 42)
            if face_hash in face_hashes:
                point_index = wedges[pivot_index].point_index
                point = psk.points[point_index]
                new_point = Vector3()
                new_point.x = point.x
                new_point.y = point.y
                new_point.z = point.z
                new_point_index = len(psk.point)
                wedges[pivot_index].point_index = new_point_index
                psk.points.append(new_point)
                # Update the vertex index (0-index is the pivot index) and recalculate the face hash.
                # NOTE: this is technically unnecessary, but for completeness this should be done.
                vertex_indices[0] = new_point_index
                # Recalculate the face hash
                face_hash = (vertex_indices[0] & 0x1FFFFF) | ((vertex_indices[1] & 0x1FFFFF) << 21) | (
                            (vertex_indices[2] & 0x1FFFFF) << 42)
            face_hashes.add(face_hash)
            # TODO: sort the vertex indices, hash them somehow (assuming 64-bit ints, use 21-bits?), and store it in a
            # set; if it already exists in the set, then create a single new vertex and update the refs



    def import_(self, context, psk: Psk, name: str):

        self.fix_degenerate_geometry(psk)

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

        # VERTICES
        bm = bmesh.new()
        bm.from_mesh(mesh)

        for point in psk.points:
            bm.verts.new((point.x, point.y, point.z))

        bm.verts.ensure_lookup_table()

        # TODO: somehow get the smoothing group info incorporated (edge split modifiers, maybe?)
        # FACES might need to be remapped (original face indices ~> actual face indices?)
        # other, better option: gracefully handle the degenerate geometry
        # by creating extra vertices and keeping track of that shit
        for i, psk_face in enumerate(psk.faces):
            wedges = psk.wedges[psk_face.wedge_index_1], \
                     psk.wedges[psk_face.wedge_index_2], \
                     psk.wedges[psk_face.wedge_index_3]
            vertex_indices = [w.point_index for w in reversed(wedges)]
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

        bpy.context.view_layer.objects.active = mesh_object
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        bm = bmesh.from_edit_mesh(mesh)
        bm.edges.ensure_lookup_table()
        # Smoothing groups are not exported out of umodel, but we handle them here anyways.
        for edge in bm.edges:
            if len(edge.link_faces) == 2:
                print(psk.faces[edge.link_faces[0].index].smoothing_groups, psk.faces[edge.link_faces[1].index].smoothing_groups)
                if psk.faces[edge.link_faces[0].index].smoothing_groups == psk.faces[edge.link_faces[1].index].smoothing_groups:
                    bm.edges[i].select = True
        bmesh.update_edit_mesh(mesh, False, False)
        del bm
        bpy.ops.object.mode_set(mode='OBJECT')

        # TODO: WEIGHTS! (next)

        mesh.validate(clean_customdata=False)
        mesh.update(calc_edges=False)

        # ARMATURE MODIFIER
        mesh_object.parent = armature_object
        armature_modifier = mesh_object.modifiers.new('Armature', 'ARMATURE')
        armature_modifier.object = armature_object
