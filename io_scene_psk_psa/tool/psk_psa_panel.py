import bpy
from bpy.types import Panel
from bpy.props import PointerProperty

from ..psk.import_ import operators as psk_import_operators
from ..psk.export import operators as psk_export_operators
from ..psk.export.properties import PSK_PG_export
from ..psa.import_ import operators as psa_import_operators
from ..psa.export import operators as psa_export_operators
from ..psa.import_.properties import PSA_PG_import
from ..psa.export.properties import PSA_PG_export

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

def register():
    bpy.utils.register_class(PSK_PSA_PT_import_export_panel)
    bpy.types.Scene.psk_export = PointerProperty(type=PSK_PG_export)
    bpy.types.Scene.psa_import = PointerProperty(type=PSA_PG_import)
    bpy.types.Scene.psa_export = PointerProperty(type=PSA_PG_export)

def unregister():
    bpy.utils.unregister_class(PSK_PSA_PT_import_export_panel)
    
    # Safely remove properties
    if hasattr(bpy.types.Scene, "psk_export"):
        del bpy.types.Scene.psk_export
    if hasattr(bpy.types.Scene, "psa_import"):
        del bpy.types.Scene.psa_import
    if hasattr(bpy.types.Scene, "psa_export"):
        del bpy.types.Scene.psa_export