import os
from pathlib import Path

from bpy.props import StringProperty
from bpy.types import Operator, Event, Context, FileHandler
from bpy_extras.io_utils import ImportHelper

from .properties import get_visible_sequences
from ..config import read_psa_config
from ..importer import import_psa, PsaImportOptions
from ..reader import PsaReader


class PSA_OT_import_sequences_from_text(Operator):
    bl_idname = 'psa_import.sequences_select_from_text'
    bl_label = 'Select By Text List'
    bl_description = 'Select sequences by name from text list'
    bl_options = {'INTERNAL', 'UNDO'}

    @classmethod
    def poll(cls, context):
        pg = getattr(context.scene, 'psa_import')
        return len(pg.sequence_list) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=256)

    def draw(self, context):
        layout = self.layout
        pg = getattr(context.scene, 'psa_import')
        layout.label(icon='INFO', text='Each sequence name should be on a new line.')
        layout.prop(pg, 'select_text', text='')

    def execute(self, context):
        pg = getattr(context.scene, 'psa_import')
        if pg.select_text is None:
            self.report({'ERROR_INVALID_CONTEXT'}, 'No text block selected')
            return {'CANCELLED'}
        contents = pg.select_text.as_string()
        count = 0
        for line in contents.split('\n'):
            for sequence in pg.sequence_list:
                if sequence.action_name == line:
                    sequence.is_selected = True
                    count += 1
        self.report({'INFO'}, f'Selected {count} sequence(s)')
        return {'FINISHED'}


class PSA_OT_import_sequences_select_all(Operator):
    bl_idname = 'psa_import.sequences_select_all'
    bl_label = 'All'
    bl_description = 'Select all sequences'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        pg = getattr(context.scene, 'psa_import')
        visible_sequences = get_visible_sequences(pg, pg.sequence_list)
        has_unselected_actions = any(map(lambda action: not action.is_selected, visible_sequences))
        return len(visible_sequences) > 0 and has_unselected_actions

    def execute(self, context):
        pg = getattr(context.scene, 'psa_import')
        visible_sequences = get_visible_sequences(pg, pg.sequence_list)
        for sequence in visible_sequences:
            sequence.is_selected = True
        return {'FINISHED'}


class PSA_OT_import_sequences_deselect_all(Operator):
    bl_idname = 'psa_import.sequences_deselect_all'
    bl_label = 'None'
    bl_description = 'Deselect all visible sequences'
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        pg = getattr(context.scene, 'psa_import')
        visible_sequences = get_visible_sequences(pg, pg.sequence_list)
        has_selected_sequences = any(map(lambda sequence: sequence.is_selected, visible_sequences))
        return len(visible_sequences) > 0 and has_selected_sequences

    def execute(self, context):
        pg = getattr(context.scene, 'psa_import')
        visible_sequences = get_visible_sequences(pg, pg.sequence_list)
        for sequence in visible_sequences:
            sequence.is_selected = False
        return {'FINISHED'}


def load_psa_file(context, filepath: str):
    pg = context.scene.psa_import
    pg.sequence_list.clear()
    pg.psa.bones.clear()
    pg.psa_error = ''
    try:
        # Read the file and populate the action list.
        p = os.path.abspath(filepath)
        psa_reader = PsaReader(p)
        for sequence in psa_reader.sequences.values():
            item = pg.sequence_list.add()
            item.action_name = sequence.name.decode('windows-1252')
        for psa_bone in psa_reader.bones:
            item = pg.psa.bones.add()
            item.bone_name = psa_bone.name.decode('windows-1252')
    except Exception as e:
        pg.psa_error = str(e)


def on_psa_file_path_updated(cls, context):
    load_psa_file(context, cls.filepath)


class PSA_OT_import(Operator, ImportHelper):
    bl_idname = 'psa_import.import'
    bl_label = 'Import'
    bl_description = 'Import the selected animations into the scene as actions'
    bl_options = {'INTERNAL', 'UNDO'}

    filename_ext = '.psa'
    filter_glob: StringProperty(default='*.psa', options={'HIDDEN'})
    filepath: StringProperty(
        name='File Path',
        description='File path used for importing the PSA file',
        maxlen=1024,
        default='',
        update=on_psa_file_path_updated)

    @classmethod
    def poll(cls, context):
        active_object = context.view_layer.objects.active
        if active_object is None or active_object.type != 'ARMATURE':
            cls.poll_message_set('The active object must be an armature')
            return False
        return True

    def execute(self, context):
        pg = getattr(context.scene, 'psa_import')
        psa_reader = PsaReader(self.filepath)
        sequence_names = [x.action_name for x in pg.sequence_list if x.is_selected]

        if len(sequence_names) == 0:
            self.report({'ERROR_INVALID_CONTEXT'}, 'No sequences selected')
            return {'CANCELLED'}

        options = PsaImportOptions()
        options.sequence_names = sequence_names
        options.should_use_fake_user = pg.should_use_fake_user
        options.should_stash = pg.should_stash
        options.action_name_prefix = pg.action_name_prefix if pg.should_use_action_name_prefix else ''
        options.should_overwrite = pg.should_overwrite
        options.should_write_metadata = pg.should_write_metadata
        options.should_write_keyframes = pg.should_write_keyframes
        options.should_convert_to_samples = pg.should_convert_to_samples
        options.bone_mapping_mode = pg.bone_mapping_mode
        options.fps_source = pg.fps_source
        options.fps_custom = pg.fps_custom

        if options.should_use_config_file:
            # Read the PSA config file if it exists.
            config_path = Path(self.filepath).with_suffix('.config')
            if config_path.exists():
                try:
                    options.psa_config = read_psa_config(psa_reader, str(config_path))
                except Exception as e:
                    self.report({'WARNING'}, f'Failed to read PSA config file: {e}')

        result = import_psa(context, psa_reader, context.view_layer.objects.active, options)

        if len(result.warnings) > 0:
            message = f'Imported {len(sequence_names)} action(s) with {len(result.warnings)} warning(s)\n'
            self.report({'WARNING'}, message)
            for warning in result.warnings:
                self.report({'WARNING'}, warning)
        else:
            self.report({'INFO'}, f'Imported {len(sequence_names)} action(s)')

        return {'FINISHED'}

    def invoke(self, context: Context, event: Event):
        # Attempt to load the PSA file for the pre-selected file.
        load_psa_file(context, self.filepath)

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context: Context):
        layout = self.layout
        pg = getattr(context.scene, 'psa_import')

        sequences_header, sequences_panel = layout.panel('sequences_panel_id', default_closed=False)
        sequences_header.label(text='Sequences')

        if sequences_panel:
            if pg.psa_error:
                row = sequences_panel.row()
                row.label(text='Select a PSA file', icon='ERROR')
            else:
                # Select buttons.
                rows = max(3, min(len(pg.sequence_list), 10))

                row = sequences_panel.row()
                col = row.column()

                row2 = col.row(align=True)
                row2.label(text='Select')
                row2.operator(PSA_OT_import_sequences_from_text.bl_idname, text='', icon='TEXT')
                row2.operator(PSA_OT_import_sequences_select_all.bl_idname, text='All', icon='CHECKBOX_HLT')
                row2.operator(PSA_OT_import_sequences_deselect_all.bl_idname, text='None', icon='CHECKBOX_DEHLT')

                col = col.row()
                col.template_list('PSA_UL_import_sequences', '', pg, 'sequence_list', pg, 'sequence_list_index', rows=rows)

            col = sequences_panel.column(heading='')
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(pg, 'fps_source')
            if pg.fps_source == 'CUSTOM':
                col.prop(pg, 'fps_custom')
            col.prop(pg, 'should_overwrite')
            col.prop(pg, 'should_use_action_name_prefix')
            if pg.should_use_action_name_prefix:
                col.prop(pg, 'action_name_prefix')

        data_header, data_panel = layout.panel('data_panel_id', default_closed=False)
        data_header.label(text='Data')

        if data_panel:
            col = data_panel.column(heading='Write')
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(pg, 'should_write_keyframes')
            col.prop(pg, 'should_write_metadata')

            if pg.should_write_keyframes:
                col = col.column(heading='Keyframes')
                col.use_property_split = True
                col.use_property_decorate = False
                col.prop(pg, 'should_convert_to_samples')

        advanced_header, advanced_panel = layout.panel('advanced_panel_id', default_closed=True)
        advanced_header.label(text='Advanced')

        if advanced_panel:
            col = advanced_panel.column()
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(pg, 'bone_mapping_mode')

            col = advanced_panel.column(heading='Options')
            col.use_property_split = True
            col.use_property_decorate = False
            col.prop(pg, 'should_use_fake_user')
            col.prop(pg, 'should_stash')
            col.prop(pg, 'should_use_config_file')


class PSA_FH_import(FileHandler):
    bl_idname = 'PSA_FH_import'
    bl_label = 'File handler for Unreal PSA import'
    bl_import_operator = 'psa_import.import'
    bl_export_operator = 'psa_export.export'
    bl_file_extensions = '.psa'

    @classmethod
    def poll_drop(cls, context: Context):
        return context.area and context.area.type == 'VIEW_3D'


classes = (
    PSA_OT_import_sequences_select_all,
    PSA_OT_import_sequences_deselect_all,
    PSA_OT_import_sequences_from_text,
    PSA_OT_import,
    PSA_FH_import,
)
