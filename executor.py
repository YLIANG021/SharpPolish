import bpy
import bmesh
import hashlib
import math
import traceback
from collections import OrderedDict, defaultdict
from enum import Enum

from bpy.app.translations import pgettext_rpt as rpt_

from .core_algorithms import np, run_standard_polish, run_tension_polish


class PolishResult(Enum):
    SUCCESS = "success"
    NO_FACE_SET = "no_face_set"
    SINGLE_GROUP = "single_group"


_topo_cache = OrderedDict()
_TOPO_CACHE_LIMIT = 12


def _cache_key_prefix(mesh_ptr):
    return f"{mesh_ptr}:"


def _invalidate_mesh_cache(mesh):
    prefix = _cache_key_prefix(int(mesh.as_pointer()))
    stale_keys = [key for key in _topo_cache if key.startswith(prefix)]
    for key in stale_keys:
        _topo_cache.pop(key, None)


def _hash_int_sequence(values):
    if not values:
        return 0

    array = np.asarray(values, dtype=np.int64)
    digest = hashlib.blake2b(np.ascontiguousarray(array).tobytes(), digest_size=8).digest()
    return int.from_bytes(digest, "little", signed=False)


def _to_numpy_int_array(values):
    return np.asarray(values, dtype=np.int32)


def _neighbor_matrix(neighbor_lists):
    vert_count = len(neighbor_lists)
    max_degree = max((len(neighbors) for neighbors in neighbor_lists), default=0)
    if max_degree == 0:
        return (
            np.empty((vert_count, 0), dtype=np.int32),
            np.zeros(vert_count, dtype=np.int32),
        )

    indices = np.full((vert_count, max_degree), -1, dtype=np.int32)
    counts = np.zeros(vert_count, dtype=np.int32)
    for idx, neighbors in enumerate(neighbor_lists):
        count = len(neighbors)
        counts[idx] = count
        if count:
            indices[idx, :count] = neighbors
    return indices, counts


def _mesh_topology_signature(mesh):
    edge_vertices = [0] * (len(mesh.edges) * 2)
    if edge_vertices:
        mesh.edges.foreach_get("vertices", edge_vertices)

    loop_vertices = [0] * len(mesh.loops)
    if loop_vertices:
        mesh.loops.foreach_get("vertex_index", loop_vertices)

    poly_loop_totals = [0] * len(mesh.polygons)
    if poly_loop_totals:
        mesh.polygons.foreach_get("loop_total", poly_loop_totals)

    return (
        _hash_int_sequence(edge_vertices),
        _hash_int_sequence(loop_vertices),
        _hash_int_sequence(poly_loop_totals),
    )


def _bmesh_topology_signature(bm):
    edge_vertices = []
    loop_vertices = []
    poly_loop_totals = []

    for edge in bm.edges:
        edge_vertices.extend((edge.verts[0].index, edge.verts[1].index))

    for face in bm.faces:
        poly_loop_totals.append(len(face.loops))
        for loop in face.loops:
            loop_vertices.append(loop.vert.index)

    return (
        _hash_int_sequence(edge_vertices),
        _hash_int_sequence(loop_vertices),
        _hash_int_sequence(poly_loop_totals),
    )


def _mesh_shape_signature(mesh):
    coords = [0.0] * (len(mesh.vertices) * 3)
    if coords:
        mesh.vertices.foreach_get("co", coords)
    quantized = [int(round(value * 100000.0)) for value in coords]
    return _hash_int_sequence(quantized)


def _bmesh_shape_signature(bm):
    quantized = []
    for vert in bm.verts:
        quantized.extend(
            (
                int(round(vert.co.x * 100000.0)),
                int(round(vert.co.y * 100000.0)),
                int(round(vert.co.z * 100000.0)),
            )
        )
    return _hash_int_sequence(quantized)


def _faceset_signature(face_sets):
    return _hash_int_sequence(face_sets)


def _get_face_set_data_source(mesh, bm=None):
    if bm is not None:
        layer = bm.faces.layers.int.get(".sculpt_face_set")
        if layer is not None:
            return "BMESH", layer

    face_attr = mesh.attributes.get(".sculpt_face_set")
    if face_attr and face_attr.domain == "FACE":
        return "MESH", face_attr

    return None, None


def _uses_whole_mesh(face_sets):
    if not face_sets:
        return True
    return len(set(face_sets)) <= 1


def get_mesh_attributes(mesh, bm=None):
    face_sets = None

    source_kind, source = _get_face_set_data_source(mesh, bm)
    if source_kind == "BMESH":
        face_sets = [0] * len(bm.faces)
        for face in bm.faces:
            face_sets[face.index] = face[source]
    elif source_kind == "MESH":
        face_count = len(mesh.polygons)
        face_sets = [0] * face_count
        if face_count > 0:
            source.data.foreach_get("value", face_sets)

    vert_count = len(mesh.vertices)
    masks = [0.0] * vert_count
    mask_attr = mesh.attributes.get(".sculpt_mask")
    if mask_attr and mask_attr.domain == "POINT" and vert_count > 0:
        mask_attr.data.foreach_get("value", masks)

    return face_sets, masks


def build_topology_data(bm, face_set_per_face, feature_angle):
    vert_groups = defaultdict(set)
    for face in bm.faces:
        fset_id = face_set_per_face[face.index]
        for vert in face.verts:
            vert_groups[vert.index].add(fset_id)

    vert_count = len(bm.verts)
    vert_class = [0] * vert_count
    inner_neighbors = [[] for _ in range(vert_count)]
    boundary_neighbors = [[] for _ in range(vert_count)]

    lock_enabled = feature_angle > 0.001
    dot_threshold = -math.cos(feature_angle) if lock_enabled else 2.0

    for vert in bm.verts:
        idx = vert.index

        if any(len(edge.link_faces) > 2 for edge in vert.link_edges):
            continue

        open_edges = [edge for edge in vert.link_edges if len(edge.link_faces) == 1]
        fset_count = len(vert_groups[idx])

        if fset_count >= 3:
            continue

        if open_edges:
            if fset_count >= 2 or len(open_edges) != 2:
                continue
            vert_class[idx] = 3
        else:
            if fset_count == 1:
                vert_class[idx] = 1
            elif fset_count == 2:
                vert_class[idx] = 2
            else:
                continue

    for vert in bm.verts:
        idx = vert.index
        cls = vert_class[idx]

        if cls == 1:
            inner_neighbors[idx] = [edge.other_vert(vert).index for edge in vert.link_edges]

        elif cls == 2:
            boundary_neighbor_verts = []
            for edge in vert.link_edges:
                if len(edge.link_faces) != 2:
                    continue
                fset_a = face_set_per_face[edge.link_faces[0].index]
                fset_b = face_set_per_face[edge.link_faces[1].index]
                if fset_a != fset_b:
                    boundary_neighbor_verts.append(edge.other_vert(vert))

            if len(boundary_neighbor_verts) != 2:
                vert_class[idx] = 0
                continue

            if lock_enabled:
                v1 = (boundary_neighbor_verts[0].co - vert.co).normalized()
                v2 = (boundary_neighbor_verts[1].co - vert.co).normalized()
                if v1.dot(v2) >= dot_threshold:
                    vert_class[idx] = 0
                    continue

            boundary_neighbors[idx] = [boundary_neighbor_verts[0].index, boundary_neighbor_verts[1].index]

        elif cls == 3:
            boundary_neighbor_verts = [edge.other_vert(vert) for edge in vert.link_edges if len(edge.link_faces) == 1]
            if len(boundary_neighbor_verts) != 2:
                vert_class[idx] = 0
                continue

            if lock_enabled:
                v1 = (boundary_neighbor_verts[0].co - vert.co).normalized()
                v2 = (boundary_neighbor_verts[1].co - vert.co).normalized()
                if v1.dot(v2) >= dot_threshold:
                    vert_class[idx] = 0
                    continue

            boundary_neighbors[idx] = [boundary_neighbor_verts[0].index, boundary_neighbor_verts[1].index]

    return (
        _to_numpy_int_array(vert_class),
        _neighbor_matrix(inner_neighbors),
        _neighbor_matrix(boundary_neighbors),
    )


def get_or_build_topology(mesh, face_set_per_face, feature_angle, bm=None):
    shape_signature = 0
    topology_signature = _bmesh_topology_signature(bm) if bm is not None else _mesh_topology_signature(mesh)
    vert_count = len(bm.verts) if bm is not None else len(mesh.vertices)
    edge_count = len(bm.edges) if bm is not None else len(mesh.edges)
    face_count = len(bm.faces) if bm is not None else len(mesh.polygons)
    if feature_angle > 0.001:
        shape_signature = _bmesh_shape_signature(bm) if bm is not None else _mesh_shape_signature(mesh)

    cache_key = (
        f"{_cache_key_prefix(int(mesh.as_pointer()))}"
        f"{vert_count}:"
        f"{edge_count}:"
        f"{face_count}:"
        f"{round(feature_angle, 6)}:"
        f"{_faceset_signature(face_set_per_face)}:"
        f"{topology_signature}:"
        f"{shape_signature}"
    )

    cached = _topo_cache.get(cache_key)
    if cached is not None:
        _topo_cache.move_to_end(cache_key)
        return cached

    owns_bmesh = bm is None
    work_bm = bm if bm is not None else bmesh.new()

    try:
        if owns_bmesh:
            work_bm.from_mesh(mesh)
        work_bm.verts.ensure_lookup_table()
        work_bm.faces.ensure_lookup_table()
        data = build_topology_data(work_bm, face_set_per_face, feature_angle)
    finally:
        if owns_bmesh:
            work_bm.free()

    _topo_cache[cache_key] = data
    _topo_cache.move_to_end(cache_key)
    while len(_topo_cache) > _TOPO_CACHE_LIMIT:
        _topo_cache.popitem(last=False)

    return data


def _active_mesh_and_bmesh(obj):
    mesh = obj.data
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return mesh, bm
    return mesh, None


def _object_mode_selection_mask(mesh, mask_list):
    vert_count = len(mesh.vertices)
    if vert_count == 0:
        return

    sel_state = [False] * vert_count
    mesh.vertices.foreach_get("select", sel_state)
    for index, is_selected in enumerate(sel_state):
        if not is_selected:
            mask_list[index] = 1.0


def _edit_mode_selection_mask(bm, mask_list):
    for vert in bm.verts:
        if not vert.select:
            mask_list[vert.index] = 1.0


def _get_coordinates(mesh, bm=None):
    if bm is None:
        coords = [0.0] * (len(mesh.vertices) * 3)
        if coords:
            mesh.vertices.foreach_get("co", coords)
        return np.asarray(coords, dtype=np.float32).reshape((-1, 3))

    return np.asarray([(vert.co.x, vert.co.y, vert.co.z) for vert in bm.verts], dtype=np.float32)


def _write_coordinates(mesh, coords, bm=None):
    if bm is None:
        flat_coords = coords.reshape(-1).tolist()
        if flat_coords:
            mesh.vertices.foreach_set("co", flat_coords)
        mesh.update()
        return

    for index, vert in enumerate(bm.verts):
        co = coords[index]
        vert.co.x = float(co[0])
        vert.co.y = float(co[1])
        vert.co.z = float(co[2])

    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def execute_polish(context):
    obj = context.active_object
    props = context.scene.sharp_polish_props
    mesh, bm = _active_mesh_and_bmesh(obj)

    face_set_per_face, mask_list = get_mesh_attributes(mesh, bm)
    if _uses_whole_mesh(face_set_per_face):
        face_set_per_face = [1] * len(mesh.polygons)

    if props.mask_unselected and bm is not None:
        if bm is not None:
            _edit_mode_selection_mask(bm, mask_list)

    vert_class, inner_neighbors, boundary_neighbors = get_or_build_topology(
        mesh,
        face_set_per_face,
        props.feature_angle,
        bm=bm,
    )

    mask_array = np.asarray(mask_list, dtype=np.float32)
    active_inner = np.flatnonzero((vert_class == 1) & (mask_array < 1.0)).astype(np.int32)
    active_bound = np.flatnonzero(((vert_class == 2) | (vert_class == 3)) & (mask_array < 1.0)).astype(np.int32)
    active_all = np.concatenate((active_inner, active_bound)).astype(np.int32)
    cur_pos = _get_coordinates(mesh, bm=bm).copy()
    next_pos = cur_pos.copy()
    if props.algorithm_mode == "STANDARD":
        orig_pos = cur_pos.copy()
        b_err = np.zeros_like(cur_pos)
    else:
        orig_pos = None
        b_err = None

    if props.algorithm_mode == "TENSION":
        run_tension_polish(
            props.iterations,
            props.strength,
            props.boundary_strength,
            active_inner,
            active_bound,
            active_all,
            inner_neighbors,
            boundary_neighbors,
            mask_array,
            cur_pos,
            next_pos,
        )
    else:
        run_standard_polish(
            props.iterations,
            props.strength,
            props.boundary_strength,
            props.hc_blend,
            props.boundary_hc_blend,
            0.5,
            active_inner,
            active_bound,
            inner_neighbors,
            boundary_neighbors,
            mask_array,
            cur_pos,
            next_pos,
            orig_pos,
            b_err,
        )

    _write_coordinates(mesh, cur_pos, bm=bm)
    return PolishResult.SUCCESS


class _MeshOperatorMixin:
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode in {"OBJECT", "EDIT"}


class _EditMeshOperatorMixin:
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.mode == "EDIT"


class MESH_OT_create_facesets_from_edges(_EditMeshOperatorMixin, bpy.types.Operator):
    bl_idname = "mesh.create_facesets_from_edges"
    bl_label = "Create Face Sets from Edges"
    bl_description = "Use selected edges as separators and create face sets by flood fill"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        mesh, edit_bm = _active_mesh_and_bmesh(obj)
        owns_bmesh = edit_bm is None
        bm = edit_bm if edit_bm is not None else bmesh.new()

        try:
            if owns_bmesh:
                bm.from_mesh(mesh)
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()

            selected_edges = {edge.index for edge in bm.edges if edge.select}
            if not selected_edges:
                self.report(
                    {"WARNING"},
                    rpt_("No selected edges found. Select separator edges in Edit Mode first."),
                )
                return {"CANCELLED"}

            visited_faces = set()
            face_to_set = {}
            current_set_id = 1

            for face in bm.faces:
                if face.index in visited_faces:
                    continue

                stack = [face]
                visited_faces.add(face.index)

                while stack:
                    curr_face = stack.pop()
                    face_to_set[curr_face.index] = current_set_id

                    for edge in curr_face.edges:
                        if edge.index in selected_edges:
                            continue
                        for link_face in edge.link_faces:
                            if link_face.index not in visited_faces:
                                visited_faces.add(link_face.index)
                                stack.append(link_face)

                current_set_id += 1

            if edit_bm is not None:
                layer = bm.faces.layers.int.get(".sculpt_face_set")
                if layer is None:
                    layer = bm.faces.layers.int.new(".sculpt_face_set")
                for face in bm.faces:
                    face[layer] = face_to_set.get(face.index, 1)
                bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            else:
                attr = mesh.attributes.get(".sculpt_face_set")
                if attr is not None and attr.domain != "FACE":
                    self.report(
                        {"ERROR"},
                        rpt_(".sculpt_face_set exists but is not a FACE domain attribute."),
                    )
                    return {"CANCELLED"}
                if attr is None:
                    attr = mesh.attributes.new(name=".sculpt_face_set", type="INT", domain="FACE")

                values = [1] * len(mesh.polygons)
                for face_index, set_id in face_to_set.items():
                    values[face_index] = set_id

                attr.data.foreach_set("value", values)
                mesh.update()

            _invalidate_mesh_cache(mesh)
            self.report(
                {"INFO"},
                rpt_("Created %d face sets from the selected edges.") % (current_set_id - 1),
            )
            return {"FINISHED"}

        finally:
            if owns_bmesh:
                bm.free()


class MESH_OT_select_faceset_boundaries(_EditMeshOperatorMixin, bpy.types.Operator):
    bl_idname = "mesh.select_faceset_boundaries"
    bl_label = "Select Face Set Boundaries"
    bl_description = "Select the edges that separate neighboring face sets"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        mesh, bm = _active_mesh_and_bmesh(obj)
        face_sets, _mask_list = get_mesh_attributes(mesh, bm)
        if face_sets is None:
            self.report({"WARNING"}, rpt_("No face sets were found on the active mesh."))
            return {"CANCELLED"}

        if bm is not None:
            for vert in bm.verts:
                vert.select = False
            for edge in bm.edges:
                edge.select = False
            for face in bm.faces:
                face.select = False

            for edge in bm.edges:
                if len(edge.link_faces) != 2:
                    continue
                fset_a = face_sets[edge.link_faces[0].index]
                fset_b = face_sets[edge.link_faces[1].index]
                if fset_a == fset_b:
                    continue
                edge.select = True
                edge.verts[0].select = True
                edge.verts[1].select = True

            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            return {"FINISHED"}

        for vert in mesh.vertices:
            vert.select = False
        for edge in mesh.edges:
            edge.select = False
        for poly in mesh.polygons:
            poly.select = False

        edge_first_fset = [-1] * len(mesh.edges)
        edge_is_boundary = [False] * len(mesh.edges)
        loops = mesh.loops

        for poly in mesh.polygons:
            fset_id = face_sets[poly.index]
            for loop_index in poly.loop_indices:
                edge_index = loops[loop_index].edge_index
                first = edge_first_fset[edge_index]
                if first == -1:
                    edge_first_fset[edge_index] = fset_id
                elif first != fset_id:
                    edge_is_boundary[edge_index] = True

        for edge_index, is_boundary in enumerate(edge_is_boundary):
            if not is_boundary:
                continue
            edge = mesh.edges[edge_index]
            edge.select = True
            mesh.vertices[edge.vertices[0]].select = True
            mesh.vertices[edge.vertices[1]].select = True

        mesh.update()
        return {"FINISHED"}


class MESH_OT_sharp_polish_groups(_MeshOperatorMixin, bpy.types.Operator):
    bl_idname = "mesh.sharp_polish_groups"
    bl_label = "Execute Polish"
    bl_description = "Apply SharpPolish to the active mesh using the current settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            execute_polish(context)
        except Exception as exc:
            traceback.print_exc()
            self.report(
                {"ERROR"},
                rpt_("Execution failed. See the console for details: %s") % exc,
            )
            return {"CANCELLED"}

        return {"FINISHED"}
