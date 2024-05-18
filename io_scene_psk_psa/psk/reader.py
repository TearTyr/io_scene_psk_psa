import ctypes
import os
import re
import warnings
import bpy
from pathlib import Path
from typing import Dict, Tuple
from collections.abc import Mapping

from .data import *


def _read_types(fp, data_class, section: Section, data):
    buffer_length = section.data_size * section.data_count
    buffer = fp.read(buffer_length)
    offset = 0
    for _ in range(section.data_count):
        data.append(data_class.from_buffer_copy(buffer, offset))
        offset += section.data_size


def _read_material_references(path: str) -> Tuple[Mapping[str, str], str]:
    property_file_path = Path(path).with_suffix('.props.txt')
    if not property_file_path.is_file():
        # Property file does not exist.
        return {}, ''

    texture_paths: Mapping[str, str] = {}
    props_dir = os.path.dirname(path)

    with open(property_file_path, 'r') as f:
        contents = f.read()

    # Find the 'TextureParameterValues' section
    texture_param_values_pattern = r'TextureParameterValues$$(.*?)$$'
    texture_param_values_matches = re.findall(texture_param_values_pattern, contents)

    for texture_param_values_match in texture_param_values_matches:
        # Find the individual texture parameter values
        texture_param_value_pattern = r'ParameterValue = Texture2D\'(.*?)\''
        texture_param_value_matches = re.findall(texture_param_value_pattern, texture_param_values_match)

        for texture_param_value_match in texture_param_value_matches:
            # Extract the full texture path
            texture_path = texture_param_value_match
            texture_type = os.path.splitext(os.path.basename(texture_path))[0].split('_')[-1]

            # Check if the texture type matches the file name
            if texture_type in ['d', 'n', 'r', 'a']:
                # Construct the actual file path
                base_name = os.path.splitext(os.path.basename(texture_path))[0]
                tga_file_name = f"{base_name}_{texture_type}.tga"
                tga_file_path = os.path.join(props_dir, tga_file_name)
                png_file_name = f"{base_name}_{texture_type}.png"
                png_file_path = os.path.join(props_dir, png_file_name)

                if os.path.exists(tga_file_path):
                    texture_paths[texture_type] = tga_file_path
                elif os.path.exists(png_file_path):
                    texture_paths[texture_type] = png_file_path
                else:
                    # If neither .tga nor .png file exists, skip this texture
                    continue

    return texture_paths, props_dir


def import_textures(material, texture_paths, props_dir):
    node_tree = material.node_tree
    principled_bsdf = next((node for node in node_tree.nodes if node.type == 'BSDF_PRINCIPLED'), None)

    if not principled_bsdf:
        principled_bsdf = node_tree.nodes.new("ShaderNodeBsdfPrincipled")

    for texture_type, texture_path in texture_paths.items():
        image_texture_node = node_tree.nodes.new("ShaderNodeTexImage")
        image = bpy.data.images.load(texture_path)
        image_texture_node.image = image

        if texture_type == 'd':
            node_tree.links.new(image_texture_node.outputs["Color"], principled_bsdf.inputs["Base Color"])
        elif texture_type == 'n':
            normal_map_node = node_tree.nodes.new("ShaderNodeNormalMap")
            node_tree.links.new(image_texture_node.outputs["Color"], normal_map_node.inputs["Color"])
            node_tree.links.new(normal_map_node.outputs["Normal"], principled_bsdf.inputs["Normal"])
        elif texture_type == 'r':
            node_tree.links.new(image_texture_node.outputs["Color"], principled_bsdf.inputs["Roughness"])
        elif texture_type == 'a':
            node_tree.links.new(image_texture_node.outputs["Alpha"], principled_bsdf.inputs["Alpha"])


def read_psk(path: str) -> Psk:

    psk = Psk()

    # Read the PSK file sections.
    with open(path, 'rb') as fp:
        while fp.read(1):
            fp.seek(-1, 1)
            section = Section.from_buffer_copy(fp.read(ctypes.sizeof(Section)))
            if section.name == b'ACTRHEAD':
                pass
            elif section.name == b'PNTS0000':
                _read_types(fp, Vector3, section, psk.points)
            elif section.name == b'VTXW0000':
                if section.data_size == ctypes.sizeof(Psk.Wedge16):
                    _read_types(fp, Psk.Wedge16, section, psk.wedges)
                elif section.data_size == ctypes.sizeof(Psk.Wedge32):
                    _read_types(fp, Psk.Wedge32, section, psk.wedges)
                else:
                    raise RuntimeError('Unrecognized wedge format')
            elif section.name == b'FACE0000':
                _read_types(fp, Psk.Face, section, psk.faces)
            elif section.name == b'MATT0000':
                _read_types(fp, Psk.Material, section, psk.materials)
            elif section.name == b'REFSKELT':
                _read_types(fp, Psk.Bone, section, psk.bones)
            elif section.name == b'RAWWEIGHTS':
                _read_types(fp, Psk.Weight, section, psk.weights)
            elif section.name == b'FACE3200':
                _read_types(fp, Psk.Face32, section, psk.faces)
            elif section.name == b'VERTEXCOLOR':
                _read_types(fp, Color, section, psk.vertex_colors)
            elif section.name.startswith(b'EXTRAUVS'):
                _read_types(fp, Vector2, section, psk.extra_uvs)
            elif section.name == b'VTXNORMS':
                _read_types(fp, Vector3, section, psk.vertex_normals)
            elif section.name == b'MRPHINFO':
                _read_types(fp, Psk.MorphInfo, section, psk.morph_infos)
            elif section.name == b'MRPHDATA':
                _read_types(fp, Psk.MorphData, section, psk.morph_data)
            elif section.name == b'SKELSOCK':
                _read_types(fp, Psk.Socket, section, psk.sockets)
            else:
                # Section is not handled, skip it.
                fp.seek(section.data_size * section.data_count, os.SEEK_CUR)
                warnings.warn(f'Unrecognized section "{section.name} at position {fp.tell():15}"')

    '''
    UEViewer exports a sidecar file (*.props.txt) with fully-qualified reference paths for each material
    (e.g., Texture'Package.Group.Object').
    '''
    psk.material_references = _read_material_references(path)

    '''
    Tools like UEViewer and CUE4Parse write the point index as a 32-bit integer, exploiting the fact that due to struct
    alignment, there were 16-bits of padding following the original 16-bit point index in the wedge struct.
    However, this breaks compatibility with PSK files that were created with older tools that treated the
    point index as a 16-bit integer and might have junk data written to the padding bits.
    To work around this, we check if each point is still addressable using a 16-bit index, and if it is, assume the
    point index is a 16-bit integer and truncate the high bits.
    '''
    if len(psk.points) <= 65536:
        for wedge in psk.wedges:
            wedge.point_index &= 0xFFFF

    return psk