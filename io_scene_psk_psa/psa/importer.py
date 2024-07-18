import typing
from typing import List, Optional, Dict
from dataclasses import dataclass, field

import bpy
import numpy as np
from bpy.types import FCurve, Object, Context
from mathutils import Vector, Quaternion

from .config import PsaConfig, REMOVE_TRACK_LOCATION, REMOVE_TRACK_ROTATION
from .data import Psa
from .reader import PsaReader

@dataclass
class PsaImportOptions:
    should_use_fake_user: bool = False
    should_stash: bool = False
    sequence_names: List[str] = field(default_factory=list)
    should_overwrite: bool = False
    should_write_keyframes: bool = True
    should_write_metadata: bool = True
    action_name_prefix: str = ''
    should_convert_to_samples: bool = False
    bone_mapping_mode: str = 'CASE_INSENSITIVE'
    fps_source: str = 'SEQUENCE'
    fps_custom: float = 30.0
    should_use_config_file: bool = True
    psa_config: PsaConfig = field(default_factory=PsaConfig)

class ImportBone:
    def __init__(self, psa_bone: Psa.Bone):
        self.psa_bone: Psa.Bone = psa_bone
        self.name: str = psa_bone.name.decode('windows-1252')  # Add this line
        self.parent: Optional[ImportBone] = None
        self.armature_bone = None
        self.pose_bone = None
        self.original_location: Vector = Vector()
        self.original_rotation: Quaternion = Quaternion()
        self.post_rotation: Quaternion = Quaternion()
        self.fcurves: List[Optional[FCurve]] = []

def calculate_fcurve_data(import_bone: ImportBone, key_data: typing.Iterable[float]) -> tuple:
    key_rotation = Quaternion(key_data[0:4])
    key_location = Vector(key_data[4:])
    
    rotation = import_bone.post_rotation.copy()
    rotation.rotate(import_bone.original_rotation)
    
    q = import_bone.post_rotation.copy()
    if import_bone.parent is None:
        q.rotate(key_rotation.conjugated())
    else:
        q.rotate(key_rotation)
    rotation.rotate(q.conjugated())
    
    location = key_location - import_bone.original_location
    location.rotate(import_bone.post_rotation.conjugated())
    
    return rotation.w, rotation.x, rotation.y, rotation.z, location.x, location.y, location.z

class PsaImportResult:
    def __init__(self):
        self.warnings: List[str] = []

def get_armature_bone_index_for_psa_bone(psa_bone_name: str, armature_bone_names: List[str], bone_mapping_mode: str = 'EXACT') -> Optional[int]:
    for armature_bone_index, armature_bone_name in enumerate(armature_bone_names):
        if bone_mapping_mode == 'CASE_INSENSITIVE':
            if armature_bone_name.lower() == psa_bone_name.lower():
                return armature_bone_index
        elif armature_bone_name == psa_bone_name:
            return armature_bone_index
    return None

def get_sample_frame_times(source_frame_count: int, frame_step: float) -> typing.Iterable[float]:
    time = 0.0
    while time < source_frame_count - 1:
        yield time
        time += frame_step
    yield source_frame_count - 1

def resample_sequence_data_matrix(sequence_data_matrix: np.ndarray, frame_step: float = 1.0) -> np.ndarray:
    if frame_step == 1.0:
        return sequence_data_matrix

    source_frame_count, bone_count = sequence_data_matrix.shape[:2]
    sample_frame_times = list(get_sample_frame_times(source_frame_count, frame_step))
    target_frame_count = len(sample_frame_times)
    resampled_sequence_data_matrix = np.zeros((target_frame_count, bone_count, 7), dtype=float)

    for sample_frame_index, sample_frame_time in enumerate(sample_frame_times):
        frame_index = int(sample_frame_time)
        if sample_frame_time % 1.0 == 0.0:
            resampled_sequence_data_matrix[sample_frame_index] = sequence_data_matrix[frame_index]
        else:
            next_frame_index = frame_index + 1
            factor = sample_frame_time - frame_index
            for bone_index in range(bone_count):
                source_frame_1_data = sequence_data_matrix[frame_index, bone_index]
                source_frame_2_data = sequence_data_matrix[next_frame_index, bone_index]
                q = Quaternion(source_frame_1_data[:4]).slerp(Quaternion(source_frame_2_data[:4]), factor)
                q.normalize()
                l = Vector(source_frame_1_data[4:]).lerp(Vector(source_frame_2_data[4:]), factor)
                resampled_sequence_data_matrix[sample_frame_index, bone_index] = q.w, q.x, q.y, q.z, l.x, l.y, l.z

    return resampled_sequence_data_matrix

def import_psa(context: Context, psa_reader: PsaReader, armature_object: Object, options: PsaImportOptions) -> PsaImportResult:
    result = PsaImportResult()
    sequences = [psa_reader.sequences[x] for x in options.sequence_names]
    armature_data = typing.cast(bpy.types.Armature, armature_object.data)

    psa_to_armature_bone_indices, armature_to_psa_bone_indices, psa_bone_names = map_bones(psa_reader.bones, armature_data.bones, options.bone_mapping_mode)
    
    import_bones = create_import_bones(psa_reader.bones, psa_to_armature_bone_indices, armature_data, armature_object)
    
    result.warnings.extend(check_for_missing_bones(psa_bone_names, armature_object.name, import_bones))

    context.window_manager.progress_begin(0, len(sequences))

    actions = create_actions(context, sequences, options, psa_to_armature_bone_indices, import_bones, psa_reader)

    if options.should_stash:
        stash_actions(armature_object, actions)

    context.window_manager.progress_end()

    return result

def map_bones(psa_bones, armature_bones, bone_mapping_mode):
    psa_to_armature_bone_indices = {}
    armature_to_psa_bone_indices = {}
    armature_bone_names = [x.name for x in armature_bones]
    psa_bone_names = []
    duplicate_mappings = []

    for psa_bone_index, psa_bone in enumerate(psa_bones):
        psa_bone_name = psa_bone.name.decode('windows-1252')
        armature_bone_index = get_armature_bone_index_for_psa_bone(psa_bone_name, armature_bone_names, bone_mapping_mode)
        if armature_bone_index is not None:
            if armature_bone_index not in armature_to_psa_bone_indices:
                psa_to_armature_bone_indices[psa_bone_index] = armature_bone_index
                armature_to_psa_bone_indices[armature_bone_index] = psa_bone_index
            else:
                duplicate_mappings.append((psa_bone_index, armature_bone_index, armature_to_psa_bone_indices[armature_bone_index]))
            psa_bone_names.append(armature_bone_names[armature_bone_index])
        else:
            psa_bone_names.append(psa_bone_name)

    return psa_to_armature_bone_indices, armature_to_psa_bone_indices, psa_bone_names

def create_import_bones(psa_bones, psa_to_armature_bone_indices, armature_data, armature_object):
    import_bones = []
    psa_bone_names_to_import_bones = {}

    for psa_bone_index, psa_bone in enumerate(psa_bones):
        if psa_bone_index not in psa_to_armature_bone_indices:
            import_bones.append(None)
            continue
        import_bone = ImportBone(psa_bone)
        armature_bone_name = armature_data.bones[psa_to_armature_bone_indices[psa_bone_index]].name
        import_bone.armature_bone = armature_data.bones[armature_bone_name]
        import_bone.pose_bone = armature_object.pose.bones[armature_bone_name]
        psa_bone_names_to_import_bones[armature_bone_name] = import_bone
        import_bones.append(import_bone)

    for import_bone in filter(None, import_bones):
        armature_bone = import_bone.armature_bone
        if armature_bone.parent:
            if armature_bone.parent.name in psa_bone_names_to_import_bones:
                import_bone.parent = psa_bone_names_to_import_bones[armature_bone.parent.name]
        
        if armature_bone.parent:
            parent_matrix = armature_bone.parent.matrix_local
            import_bone.original_location = armature_bone.matrix_local.translation - parent_matrix.translation
            import_bone.original_location.rotate(parent_matrix.to_quaternion().conjugated())
            import_bone.original_rotation = armature_bone.matrix_local.to_quaternion()
            import_bone.original_rotation.rotate(parent_matrix.to_quaternion().conjugated())
            import_bone.original_rotation.conjugate()
        else:
            import_bone.original_location = armature_bone.matrix_local.translation.copy()
            import_bone.original_rotation = armature_bone.matrix_local.to_quaternion().conjugated()

        import_bone.post_rotation = import_bone.original_rotation.conjugated()

    return import_bones

def check_for_missing_bones(psa_bone_names: List[str], armature_name: str, import_bones: List[Optional[ImportBone]]) -> List[str]:
    warnings = []
    import_bone_names = [bone.name for bone in import_bones if bone is not None]
    missing_bone_names = set(psa_bone_names) - set(import_bone_names)
    if missing_bone_names:
        warnings.append(
            f"The armature '{armature_name}' is missing {len(missing_bone_names)} bones that exist in "
            f"the PSA:\n{sorted(missing_bone_names)}"
        )
    
    bones_with_missing_parents = [bone for bone in import_bones if bone is not None and bone.armature_bone.parent and not bone.parent]
    if bones_with_missing_parents:
        warnings.append(
            f"{len(bones_with_missing_parents)} bone(s) have parents that are not present in the PSA:\n"
            f"{[bone.name for bone in bones_with_missing_parents]}"
        )
    
    return warnings

def create_actions(context, sequences, options, psa_to_armature_bone_indices, import_bones, psa_reader):
    actions = []
    for sequence_index, sequence in enumerate(sequences):
        sequence_name = sequence.name.decode('windows-1252')
        action_name = options.action_name_prefix + sequence_name
        sequence_bone_track_flags = options.psa_config.sequence_bone_flags.get(sequence_name, {})

        action = bpy.data.actions.get(action_name) if options.should_overwrite else None
        if not action:
            action = bpy.data.actions.new(name=action_name)

        target_fps = get_target_fps(options, sequence, context)

        if options.should_write_keyframes:
            action.fcurves.clear()
            create_fcurves(action, psa_to_armature_bone_indices, import_bones, sequence_bone_track_flags)
            write_keyframes(action, sequence, psa_reader, target_fps, import_bones, options)

        if options.should_write_metadata:
            action.psa_export.fps = target_fps

        action.use_fake_user = options.should_use_fake_user
        actions.append(action)

        context.window_manager.progress_update(sequence_index)

    return actions

def get_target_fps(options, sequence, context):
    if options.fps_source == 'CUSTOM':
        return options.fps_custom
    elif options.fps_source == 'SCENE':
        return context.scene.render.fps
    elif options.fps_source == 'SEQUENCE':
        return sequence.fps
    else:
        raise ValueError(f'Unknown FPS source: {options.fps_source}')

def create_fcurves(action, psa_to_armature_bone_indices, import_bones, sequence_bone_track_flags):
    for psa_bone_index, armature_bone_index in psa_to_armature_bone_indices.items():
        bone_track_flags = sequence_bone_track_flags.get(psa_bone_index, 0)
        import_bone = import_bones[psa_bone_index]
        pose_bone = import_bone.pose_bone
        rotation_data_path = pose_bone.path_from_id('rotation_quaternion')
        location_data_path = pose_bone.path_from_id('location')
        add_rotation_fcurves = (bone_track_flags & REMOVE_TRACK_ROTATION) == 0
        add_location_fcurves = (bone_track_flags & REMOVE_TRACK_LOCATION) == 0
        
        import_bone.fcurves = [
            action.fcurves.new(rotation_data_path, index=i, action_group=pose_bone.name) if add_rotation_fcurves else None
            for i in range(4)
        ] + [
            action.fcurves.new(location_data_path, index=i, action_group=pose_bone.name) if add_location_fcurves else None
            for i in range(3)
        ]

def write_keyframes(action, sequence, psa_reader, target_fps, import_bones, options):
    sequence_data_matrix = psa_reader.read_sequence_data_matrix(sequence.name.decode('windows-1252'))
    
    for bone_index, import_bone in enumerate(import_bones):
        if import_bone is None:
            continue
        for frame_index in range(sequence.frame_count):
            key_data = sequence_data_matrix[frame_index, bone_index]
            sequence_data_matrix[frame_index, bone_index] = calculate_fcurve_data(import_bone, key_data)

    resampled_sequence_data_matrix = resample_sequence_data_matrix(sequence_data_matrix, frame_step=sequence.fps / target_fps)

    target_frame_count = resampled_sequence_data_matrix.shape[0]
    fcurve_data = np.zeros(2 * target_frame_count, dtype=float)
    fcurve_data[0::2] = range(target_frame_count)

    for bone_index, import_bone in enumerate(import_bones):
        if import_bone is None:
            continue
        for fcurve_index, fcurve in enumerate(import_bone.fcurves):
            if fcurve is None:
                continue
            fcurve_data[1::2] = resampled_sequence_data_matrix[:, bone_index, fcurve_index]
            fcurve.keyframe_points.add(target_frame_count)
            fcurve.keyframe_points.foreach_set('co', fcurve_data)
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = 'LINEAR'

    if options.should_convert_to_samples:
        for fcurve in action.fcurves:
            fcurve.convert_to_samples(start=0, end=sequence.frame_count)

def stash_actions(armature_object: Object, actions: List[bpy.types.Action]):
    if armature_object.animation_data is None:
        armature_object.animation_data_create()
    for action in actions:
        nla_track = armature_object.animation_data.nla_tracks.new()
        nla_track.name = action.name
        nla_track.mute = True
        nla_track.strips.new(name=action.name, start=0, action=action)

# Main function
def import_psa(context: Context, psa_reader: PsaReader, armature_object: Object, options: PsaImportOptions) -> PsaImportResult:
    result = PsaImportResult()
    sequences = [psa_reader.sequences[x] for x in options.sequence_names]
    armature_data = typing.cast(bpy.types.Armature, armature_object.data)

    psa_to_armature_bone_indices, armature_to_psa_bone_indices, psa_bone_names = map_bones(psa_reader.bones, armature_data.bones, options.bone_mapping_mode)
    
    import_bones = create_import_bones(psa_reader.bones, psa_to_armature_bone_indices, armature_data, armature_object)
    
    result.warnings.extend(check_for_missing_bones(psa_bone_names, armature_object.name, import_bones))

    context.window_manager.progress_begin(0, len(sequences))

    actions = create_actions(context, sequences, options, psa_to_armature_bone_indices, import_bones, psa_reader)

    if options.should_stash:
        stash_actions(armature_object, actions)

    context.window_manager.progress_end()

    return result

# Additional helper functions

def decode_string(byte_string: bytes) -> str:
    return byte_string.decode('windows-1252')

def create_action(name: str, overwrite: bool) -> bpy.types.Action:
    if overwrite and name in bpy.data.actions:
        return bpy.data.actions[name]
    return bpy.data.actions.new(name=name)

def set_keyframe_interpolation(fcurve: FCurve, interpolation: str = 'LINEAR'):
    for keyframe in fcurve.keyframe_points:
        keyframe.interpolation = interpolation

def convert_action_to_samples(action: bpy.types.Action, start: int, end: int):
    for fcurve in action.fcurves:
        fcurve.convert_to_samples(start=start, end=end)

# Error handling function
def handle_import_error(error: Exception, result: PsaImportResult):
    result.warnings.append(f"Error during import: {str(error)}")
    print(f"Error during PSA import: {str(error)}")

# Main import function with error handling
def safe_import_psa(context: Context, psa_reader: PsaReader, armature_object: Object, options: PsaImportOptions) -> PsaImportResult:
    result = PsaImportResult()
    try:
        return import_psa(context, psa_reader, armature_object, options)
    except Exception as e:
        handle_import_error(e, result)
        return result