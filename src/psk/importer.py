import bpy
import mathutils
from .data import *
import bmesh


class PskImportOptions(object):
    def __init__(self):
        pass


class PskImporter(object):

    def __init__(self):
        pass

    def fix_degenerate_geometry(self, psk):
        """
        There are a couple of scenarios that we need to "fix" so that the model can be imported in its entirety.

        First off, PSKs exported out of umodel technically contain degenerate faces, where 2 of the "wedges" point to
        the same vertex (eg. a triangle with vertices [A A B]). This is not a valid polygon and therefore cannot
        be imported directly. The solution here is to replace all duplicate vertex indices with a copy of the duplicated
        vertex (eg. [A A B] ~> [A Z B] where Z is a new vertex that is a copy of A)

        The next problem is that there are duplicate faces in exports coming out of the PSK. For example, one of the faces
        may be [A, B, C], and another is [B, C, A] (or even just [A, B, C] again). This is effectively the same face, and Blender
        understandably disallows this. This is likely related, in some way to the previous problem, and the solution is
        nearly the same: duplicate one of the vertices to make the face "unique".

        We need to be able to "hash" the faces regardless of winding order.

        TODO: note that the face hashing mechanism will break down after ~2 million vertices. it also assumes 64-bit integers.
        """
        def replace_vertices(vertex_indices: List[int]):
            yield False
            yield vertex_indices[1] == vertex_indices[0]
            yield vertex_indices[2] == vertex_indices[0] or vertex_indices[2] == vertex_indices[1]

        def get_face_hash(vertex_indices):
            return (vertex_indices[0] & 0x1FFFFF) | ((vertex_indices[1] & 0x1FFFFF) << 21) | ((vertex_indices[2] & 0x1FFFFF) << 42)

        def copy_point(point_index: int) -> int:
            new_point_index = len(psk.points)
            point = psk.points[point_index]
            new_point = Vector3()
            new_point.x = point.x
            new_point.y = point.y
            new_point.z = point.z
            psk.points.append(new_point)
            # Duplicate vertex weights
            for weight in psk.weights:
                if weight.point_index == point_index:
                    new_weight = Psk.Weight()
                    new_weight.weight = weight.weight
                    new_weight.point_index = new_point_index
                    new_weight.bone_index = weight.bone_index
                    psk.weights.append(new_weight)
            return new_point_index

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
                        new_point_index = copy_point(vertex_indices[i])
                        wedges[i].point_index = new_point_index
                        vertex_indices[i] = new_point_index
            # Find the lowest point index and choose that as the pivot point
            min_vertex_index = min(vertex_indices)
            pivot_index = vertex_indices.index(min_vertex_index)
            vertex_indices = [vertex_indices[i % 3] for i in range(pivot_index, pivot_index + 3)]
            face_hash = get_face_hash(vertex_indices)
            if face_hash in face_hashes:
                new_point_index = copy_point(wedges[pivot_index].point_index)
                wedges[pivot_index].point_index = new_point_index
                # Update the vertex index (0-index is the pivot index) and recalculate the face hash.
                # NOTE: this is technically unnecessary, but for completeness this should be done.
                vertex_indices[0] = new_point_index
                # Recalculate the face hash
                face_hash = get_face_hash(vertex_indices)
            face_hashes.add(face_hash)

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

            # TODO: this is all wrong, probably needs to take parent matrix into account.
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

        # WEIGHTS
        bone_names = [b.name.decode('utf-8') for b in psk.bones]
        for weight in psk.weights:
            mesh_object.vertex_groups[bone_names[weight.bone_index]].add([weight.point_index], weight.weight, 'REPLACE')

        mesh.validate(clean_customdata=False)
        mesh.update(calc_edges=False)

        # ARMATURE MODIFIER
        mesh_object.parent = armature_object
        armature_modifier = mesh_object.modifiers.new('Armature', 'ARMATURE')
        armature_modifier.object = armature_object
