import numpy as np


def _laplacian_step_numpy(active_verts, neighbor_indices, neighbor_counts, source_pos, target_pos, mask_array, strength):
    if active_verts.size == 0:
        return

    target_pos[active_verts] = source_pos[active_verts]
    eff_strength = strength * (1.0 - mask_array[active_verts])
    active_counts = neighbor_counts[active_verts]
    valid_mask = (np.abs(eff_strength) >= 1e-12) & (active_counts > 0)
    if not np.any(valid_mask):
        return

    work_verts = active_verts[valid_mask]
    work_strength = eff_strength[valid_mask][:, None]
    counts = active_counts[valid_mask]
    neigh_idx = neighbor_indices[work_verts]
    valid_neighbors = neigh_idx >= 0
    # -1 entries are padding placeholders for rows with fewer neighbors.
    clipped = np.maximum(neigh_idx, 0)
    neigh_sum = np.where(valid_neighbors[:, :, None], source_pos[clipped], 0.0).sum(axis=1)
    neigh_avg = neigh_sum / counts[:, None]
    src = source_pos[work_verts]
    target_pos[work_verts] = src + (neigh_avg - src) * work_strength


def _hc_correction_step_numpy(active_verts, neighbor_indices, neighbor_counts, next_pos, b_err, cur_pos, beta):
    if active_verts.size == 0:
        return

    cur_pos[active_verts] = next_pos[active_verts]
    counts = neighbor_counts[active_verts]
    valid_mask = counts > 0
    if not np.any(valid_mask):
        return

    work_verts = active_verts[valid_mask]
    counts = counts[valid_mask]
    neigh_idx = neighbor_indices[work_verts]
    valid_neighbors = neigh_idx >= 0
    # -1 entries are padding placeholders for rows with fewer neighbors.
    clipped = np.maximum(neigh_idx, 0)
    avg_err = np.where(valid_neighbors[:, :, None], b_err[clipped], 0.0).sum(axis=1) / counts[:, None]
    one_minus_beta = 1.0 - beta
    be = b_err[work_verts]
    cur_pos[work_verts] = next_pos[work_verts] - (be * beta + avg_err * one_minus_beta)


def _laplacian_step(active_verts, neighbor_data, source_pos, target_pos, mask_array, strength):
    neighbor_indices, neighbor_counts = neighbor_data
    _laplacian_step_numpy(active_verts, neighbor_indices, neighbor_counts, source_pos, target_pos, mask_array, strength)


def _hc_correction_step(active_verts, neighbor_data, next_pos, b_err, cur_pos, beta):
    neighbor_indices, neighbor_counts = neighbor_data
    _hc_correction_step_numpy(active_verts, neighbor_indices, neighbor_counts, next_pos, b_err, cur_pos, beta)


def run_standard_polish(
    iterations,
    strength,
    b_strength,
    hc_blend,
    b_hc_blend,
    beta,
    active_inner,
    active_bound,
    inner_neighbors,
    boundary_neighbors,
    mask_array,
    cur_pos,
    next_pos,
    orig_pos,
    b_err,
):
    for _ in range(iterations):
        _laplacian_step(active_inner, inner_neighbors, cur_pos, next_pos, mask_array, strength)
        _laplacian_step(active_bound, boundary_neighbors, cur_pos, next_pos, mask_array, b_strength)

        inner_next = next_pos[active_inner]
        inner_cur = cur_pos[active_inner]
        inner_orig = orig_pos[active_inner]
        bound_next = next_pos[active_bound]
        bound_cur = cur_pos[active_bound]
        bound_orig = orig_pos[active_bound]

        b_err[active_inner] = inner_next - (inner_orig * hc_blend + inner_cur * (1.0 - hc_blend))
        b_err[active_bound] = bound_next - (bound_orig * b_hc_blend + bound_cur * (1.0 - b_hc_blend))

        _hc_correction_step(active_inner, inner_neighbors, next_pos, b_err, cur_pos, beta)
        _hc_correction_step(active_bound, boundary_neighbors, next_pos, b_err, cur_pos, beta)


def run_tension_polish(
    iterations,
    strength,
    b_strength,
    active_inner,
    active_bound,
    active_all,
    inner_neighbors,
    boundary_neighbors,
    mask_array,
    cur_pos,
    next_pos,
):
    for _ in range(iterations):
        _laplacian_step(active_inner, inner_neighbors, cur_pos, next_pos, mask_array, strength)
        _laplacian_step(active_bound, boundary_neighbors, cur_pos, next_pos, mask_array, b_strength)
        cur_pos[active_all] = next_pos[active_all]
