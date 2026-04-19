import bpy

from .executor import (
    MESH_OT_create_facesets_from_edges,
    MESH_OT_select_faceset_boundaries,
    MESH_OT_sharp_polish_groups,
)
from .translations import translation_dict
from .ui import SHARPPOLISH_PG_properties, VIEW3D_PT_polish_panel

classes = [
    SHARPPOLISH_PG_properties,
    MESH_OT_create_facesets_from_edges,
    MESH_OT_select_faceset_boundaries,
    MESH_OT_sharp_polish_groups,
    VIEW3D_PT_polish_panel,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.app.translations.register(__name__, translation_dict)
    bpy.types.Scene.sharp_polish_props = bpy.props.PointerProperty(
        type=SHARPPOLISH_PG_properties
    )


def unregister():
    if hasattr(bpy.types.Scene, "sharp_polish_props"):
        del bpy.types.Scene.sharp_polish_props

    bpy.app.translations.unregister(__name__)

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
