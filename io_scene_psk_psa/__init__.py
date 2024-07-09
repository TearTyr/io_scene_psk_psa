bl_info = {
    'name': 'PSK/PSA Importer/Exporter',
    'author': 'Colin Basnett, Yurii Ti',
    'version': (7, 0, 0),
    'blender': (4, 0, 0),
    'description': 'PSK/PSA Import/Export (.psk/.psa)',
    'warning': '',
    'doc_url': 'https://github.com/DarklightGames/io_scene_psk_psa',
    'tracker_url': 'https://github.com/DarklightGames/io_scene_psk_psa/issues',
    'category': 'Import-Export'
}

import bpy
from bpy.props import PointerProperty
from bpy.app.handlers import persistent
from bpy.types import Panel

if 'bpy' in locals():
    import importlib
    # Reload all modules
    modules_to_reload = [
        'psx_data', 'psx_helpers', 'psx_types',
        'psk_data', 'psk_reader', 'psk_writer', 'psk_builder', 'psk_importer',
        'psk_properties', 'psk_ui', 'psk_export_properties', 'psk_export_operators',
        'psk_export_ui', 'psk_import_operators',
        'psa_data', 'psa_config', 'psa_reader', 'psa_writer', 'psa_builder', 'psa_importer',
        'psa_export_properties', 'psa_export_operators', 'psa_export_ui',
        'psa_import_properties', 'psa_import_operators', 'psa_import_ui',
        'combine_psk_and_gltf', 'export_as_fbx',
        'psk_psa_import_export'
    ]
    for module in modules_to_reload:
        if module in locals():
            importlib.reload(locals()[module])
else:
    # Import all required modules
    from . import (
        data as psx_data, helpers as psx_helpers, types as psx_types,
        psk, psa,
        tool
    )
    from .psk import (
        data as psk_data, reader as psk_reader, writer as psk_writer,
        builder as psk_builder, importer as psk_importer, properties as psk_properties,
        ui as psk_ui
    )
    from .psk.export import (
        properties as psk_export_properties, operators as psk_export_operators,
        ui as psk_export_ui
    )
    from .psk.import_ import operators as psk_import_operators
    from .psa import (
        data as psa_data, config as psa_config, reader as psa_reader,
        writer as psa_writer, builder as psa_builder, importer as psa_importer
    )
    from .psa.export import (
        properties as psa_export_properties, operators as psa_export_operators,
        ui as psa_export_ui
    )
    from .psa.import_ import (
        properties as psa_import_properties, operators as psa_import_operators,
        ui as psa_import_ui
    )
    from .tool import combine_psk_and_gltf, export_as_fbx
    from . import psk_psa_import_export

# Collect all classes
classes = (
    psx_types.classes +
    psk_properties.classes +
    psk_ui.classes +
    psk_import_operators.classes +
    psk_export_properties.classes +
    psk_export_operators.classes +
    psk_export_ui.classes +
    psa_export_properties.classes +
    psa_export_operators.classes +
    psa_export_ui.classes +
    psa_import_properties.classes +
    psa_import_operators.classes +
    psa_import_ui.classes
)

class PSK_PSA_PT_import_export_panel(Panel):
    bl_label = "PSK/PSA Import/Export"
    bl_idname = "VIEW3D_PT_psk_psa_import_export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "PSK / PSA"

    def draw(self, context):
        layout = self.layout
        
        # PSK Import
        layout.operator(psk_import_operators.PSK_OT_import.bl_idname, icon='MESH_DATA')
        layout.prop(context.scene.psk_export, 'bone_filter_mode')
        layout.prop(context.scene.psk_export, 'should_enforce_bone_name_restrictions')
        
        # PSK Export
        layout.operator(psk_export_operators.PSK_OT_export.bl_idname, icon='EXPORT')
        
        # PSA Import
        layout.operator(psa_import_operators.PSA_OT_import.bl_idname, icon='ANIM')
        layout.prop(context.scene.psa_import, 'should_use_fake_user')
        layout.prop(context.scene.psa_import, 'should_stash')
        
        # PSA Export
        layout.operator(psa_export_operators.PSA_OT_export.bl_idname, icon='EXPORT')
        layout.prop(context.scene.psa_export, 'fps_source')
        layout.prop(context.scene.psa_export, 'should_overwrite')

classes.append(PSK_PSA_PT_import_export_panel)

def psk_export_menu_func(self, context):
    self.layout.operator(psk_export_operators.PSK_OT_export.bl_idname, text='Unreal PSK (.psk)')

def psk_import_menu_func(self, context):
    self.layout.operator(psk_import_operators.PSK_OT_import.bl_idname, text='Unreal PSK (.psk/.pskx)')

def psa_export_menu_func(self, context):
    self.layout.operator(psa_export_operators.PSA_OT_export.bl_idname, text='Unreal PSA (.psa)')

def psa_import_menu_func(self, context):
    self.layout.operator(psa_import_operators.PSA_OT_import.bl_idname, text='Unreal PSA (.psa)')

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.TOPBAR_MT_file_export.append(psk_export_menu_func)
    bpy.types.TOPBAR_MT_file_import.append(psk_import_menu_func)
    bpy.types.TOPBAR_MT_file_export.append(psa_export_menu_func)
    bpy.types.TOPBAR_MT_file_import.append(psa_import_menu_func)
    
    bpy.types.Material.psk = PointerProperty(type=psk_properties.PSX_PG_material)
    bpy.types.Scene.psa_import = PointerProperty(type=psa_import_properties.PSA_PG_import)
    bpy.types.Scene.psa_export = PointerProperty(type=psa_export_properties.PSA_PG_export)
    bpy.types.Scene.psk_export = PointerProperty(type=psk_export_properties.PSK_PG_export)
    bpy.types.Action.psa_export = PointerProperty(type=psx_types.PSX_PG_action_export)
    
    psk_psa_import_export.register()
    combine_psk_and_gltf.register()
    export_as_fbx.register()

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    bpy.types.TOPBAR_MT_file_export.remove(psk_export_menu_func)
    bpy.types.TOPBAR_MT_file_import.remove(psk_import_menu_func)
    bpy.types.TOPBAR_MT_file_export.remove(psa_export_menu_func)
    bpy.types.TOPBAR_MT_file_import.remove(psa_import_menu_func)
    
    del bpy.types.Material.psk
    del bpy.types.Scene.psa_import
    del bpy.types.Scene.psa_export
    del bpy.types.Scene.psk_export
    del bpy.types.Action.psa_export
    
    psk_psa_import_export.unregister()
    combine_psk_and_gltf.unregister()
    export_as_fbx.unregister()

@persistent
def load_handler(dummy):
    # Convert old `psa_sequence_fps` property to new `psa_export.fps` property.
    for action in bpy.data.actions:
        if 'psa_sequence_fps' in action:
            action.psa_export.fps = action['psa_sequence_fps']
            del action['psa_sequence_fps']

bpy.app.handlers.load_post.append(load_handler)

if __name__ == '__main__':
    register()