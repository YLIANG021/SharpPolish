import bpy
import bmesh
import math

I18N_DEFAULT_CTXT = bpy.app.translations.contexts.default


def update_algorithm_mode(self, _context):
    if self.algorithm_mode == "STANDARD":
        self.iterations = 10
        self.strength = 1.0
        self.hc_blend = 0.5
        self.boundary_strength = 1.0
        self.boundary_hc_blend = 1.0
    elif self.algorithm_mode == "TENSION":
        self.iterations = 2
        self.strength = 0.2
        self.boundary_strength = 0.1


class SHARPPOLISH_PG_properties(bpy.types.PropertyGroup):
    algorithm_mode: bpy.props.EnumProperty(
        name="Mode",
        items=[
            (
                "STANDARD",
                "Standard HC (Volume Preserve)",
                "Smooth the surface while using HC correction to reduce volume loss",
            ),
            (
                "TENSION",
                "Tension First (Surface Shrink)",
                "Skip volume compensation and prioritize tension reduction for a sharper polish",
            ),
        ],
        default="STANDARD",
        update=update_algorithm_mode,
    )

    iterations: bpy.props.IntProperty(
        name="Iterations",
        default=10,
        min=1,
        max=200,
        description="Number of smoothing iterations",
    )

    feature_angle: bpy.props.FloatProperty(
        name="Corners",
        default=0.0,
        min=0.0,
        max=math.pi,
        subtype="ANGLE",
        description="Lock boundary corners sharper than this angle to keep them from smoothing; 0 disables corner protection",
    )

    mask_unselected: bpy.props.BoolProperty(
        name="Selected",
        description="Only smooth currently selected elements and fully lock the rest",
        default=False,
    )

    show_advanced: bpy.props.BoolProperty(
        name="Advanced",
        description="Show low-level polish tuning controls",
        default=False,
    )

    strength: bpy.props.FloatProperty(
        name="Smooth",
        default=1.0,
        min=0.0,
        max=1.0,
        description="Single-step smoothing strength inside each face set",
    )

    hc_blend: bpy.props.FloatProperty(
        name="Preserve",
        default=0.5,
        min=0.0,
        max=1.0,
        description="Volume preservation strength for inner regions",
    )

    boundary_strength: bpy.props.FloatProperty(
        name="Smooth",
        default=1.0,
        min=0.0,
        max=1.0,
        description="Single-step smoothing strength on boundaries",
    )

    boundary_hc_blend: bpy.props.FloatProperty(
        name="Preserve",
        default=1.0,
        min=0.0,
        max=1.0,
        description="Volume preservation strength for boundary regions",
    )


class VIEW3D_PT_polish_panel(bpy.types.Panel):
    bl_label = "SharpPolish"
    bl_idname = "VIEW3D_PT_polish_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Edit"

    def draw(self, context):
        layout = self.layout

        if not hasattr(context.scene, "sharp_polish_props"):
            layout.label(text="Properties are not registered. Reload the add-on.", icon="ERROR")
            return

        obj = context.active_object
        props = context.scene.sharp_polish_props
        in_edit_mode = obj is not None and obj.mode == "EDIT"

        if not obj or obj.type != "MESH":
            layout.label(text="Select a mesh object", text_ctxt=I18N_DEFAULT_CTXT, icon="MESH_DATA")
            return

        mesh = obj.data
        has_faceset = ".sculpt_face_set" in mesh.attributes
        if in_edit_mode:
            bm = bmesh.from_edit_mesh(mesh)
            has_faceset = has_faceset or bm.faces.layers.int.get(".sculpt_face_set") is not None

        box_mode = layout.box()
        col_mode = box_mode.column(align=True)
        col_mode.prop(props, "algorithm_mode", text="", text_ctxt=I18N_DEFAULT_CTXT)

        box_params = layout.box()
        col_params = box_params.column(align=True)
        col_params.use_property_split = False
        col_params.use_property_decorate = False
        col_params.prop(props, "iterations")
        col_params.prop(props, "feature_angle")
        col_params.separator()

        row = box_params.row(align=True)
        row.alignment = 'LEFT'
        icon = "DISCLOSURE_TRI_DOWN" if props.show_advanced else "DISCLOSURE_TRI_RIGHT"
        row.prop(props, "show_advanced", icon=icon, emboss=False)

        if props.show_advanced:
            adv_box = box_params.box()

            inner_col = adv_box.column(align=True)
            inner_col.use_property_split = False
            inner_col.use_property_decorate = False
            inner_col.label(text="Inner", text_ctxt=I18N_DEFAULT_CTXT)
            inner_col.prop(props, "strength")
            if props.algorithm_mode != "TENSION":
                inner_col.prop(props, "hc_blend")


            bound_col = adv_box.column(align=True)
            bound_col.use_property_split = False
            bound_col.use_property_decorate = False
            bound_col.label(text="Boundary", text_ctxt=I18N_DEFAULT_CTXT)
            bound_col.prop(props, "boundary_strength")
            if props.algorithm_mode != "TENSION":
                bound_col.prop(props, "boundary_hc_blend")

        layout.separator()

        action_box = layout.box()
        row = action_box.row(align=True)

        if has_faceset:
            select_op_row = row.row(align=True)
            select_op_row.enabled = in_edit_mode
            select_op_row.operator(
                "mesh.select_faceset_boundaries",
                icon="RESTRICT_SELECT_OFF",
                text="FaceSets to Select",
                text_ctxt=I18N_DEFAULT_CTXT,
            )

        create_op_row = row.row(align=True)
        create_op_row.enabled = in_edit_mode
        create_op_row.operator(
            "mesh.create_facesets_from_edges",
            icon="MOD_MASK",
            text="Edges to FaceSets",
            text_ctxt=I18N_DEFAULT_CTXT,
        )

        if not in_edit_mode:
            action_box.label(
                text="FaceSets tools are available in Edit Mode",
                text_ctxt=I18N_DEFAULT_CTXT,
                icon="RADIOBUT_ON",
            )

        row = action_box.row(align=True)
        row.scale_y = 1.75
        split = row.split(factor=0.82, align=True)
        split.operator(
            "mesh.sharp_polish_groups",
            icon="PLAY",
            text="Polish",
            text_ctxt=I18N_DEFAULT_CTXT,
        )
        selected_toggle = split.row(align=True)
        selected_toggle.enabled = in_edit_mode
        selected_toggle.prop(props, "mask_unselected", text="Selected", toggle=True)
