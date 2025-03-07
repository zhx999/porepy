from __future__ import annotations

import logging
import warnings
from typing import Callable, Dict, List

import numpy as np

import porepy as pp

logger = logging.getLogger(__name__)


def grid_error(
    mdg: pp.MixedDimensionalGrid,
    mdg_ref: pp.MixedDimensionalGrid,
    variable: List[str],
    variable_dof: List[int],
) -> dict:
    """Compute grid errors a grid bucket and refined reference grid bucket

    Assumes that the coarse grid bucket has a property 'coarse_fine_cell_mapping'
    assigned on each subdomain, which maps from coarse to fine cells according to the
    method 'coarse_fine_cell_mapping(...)'.

    Parameters:
        mdg: "Coarse" mixed-dimensional grid.
        mdg_ref: "Fine" mixed-dimensional grid.
        variable: List defining which variables to compute error over.
        variable_dof: List specifying the number of degrees of freedom for each variable
            in the list 'variable'.

    Returns:
        errors: Dictionary with top level keys as node_number, within which for each
            variable, the error is reported.

    """
    warnings.warn(
        "This method will soon be removed from PorePy",
        DeprecationWarning,
    )

    assert len(variable) == len(variable_dof), (
        "Each variable must have associated " "with it a number of degrees of freedom."
    )
    n_variables = len(variable)

    errors: Dict = {}

    grids = mdg.subdomains()
    grids_ref = mdg_ref.subdomains()
    n_grids = len(grids)

    for i in np.arange(n_grids):
        g, g_ref = grids[i], grids_ref[i]
        mapping = mdg.subdomain_data(g)["coarse_fine_cell_mapping"]

        # Get time step solutions
        data = mdg.subdomain_data(g)
        data_ref = mdg_ref.subdomain_data(g_ref)
        solutions = data[pp.TIME_STEP_SOLUTIONS]
        solutions_ref = data_ref[pp.TIME_STEP_SOLUTIONS]
        node_number = data["node_number"]

        # Initialize errors
        errors[node_number] = {}

        for var_idx in range(0, n_variables):
            var = variable[var_idx]
            var_dof = variable_dof[var_idx]

            # Check if the variable exists on both the grid and reference grid
            solution_keys = set(solutions.keys())
            solution_ref_keys = set(solutions_ref.keys())
            check_keys = solution_keys.intersection(solution_ref_keys)
            if var not in check_keys:
                logger.info(
                    f"{var} not present on grid number "
                    f"{node_number} of dim {g.dim}."
                )
                continue

            # Compute errors relative to the reference grid
            # TODO: Should the solution be divided by g.cell_volumes or similar?
            # TODO: If scaling is used, consider that - or use the export-ready variables,
            #   'u_exp', 'p_exp', etc.
            sol = (
                solutions[var][0].reshape((var_dof, -1), order="F").T
            )  # (num_cells x var_dof)
            mapped_sol: np.ndarray = mapping.dot(sol)  # (num_cells x variable_dof)
            sol_ref = (
                solutions_ref[var][0].reshape((var_dof, -1), order="F").T
            )  # (num_cells x var_dof)

            # axis=0 gives component-wise norm.
            absolute_error = np.linalg.norm(mapped_sol - sol_ref, axis=0)

            norm_ref = np.linalg.norm(sol_ref)
            if np.any(norm_ref < 1e-10):
                logger.info(
                    f"Relative error not reportable. "
                    f"Norm of reference state is {norm_ref}. "
                    f"Reporting absolute error"
                )
                error = absolute_error
                is_relative = False
            else:
                error = absolute_error / norm_ref
                is_relative = True

            errors[node_number][var] = {
                "error": error,
                "is_relative": is_relative,
            }

    return errors


def interpolate(g: pp.GridLike, fun: Callable):
    """
    Interpolate a scalar or vector function on the cell centers of the grid.

    Parameters
    ----------
    g : grid
        Grid, or a subclass, with geometry fields computed.
    fun : function
        Scalar or vector function.

    Return
    ------
    out: np.ndarray (dim of fun, g.num_cells)
        Function interpolated in the cell centers.

    Examples
    --------

    def fun_p(pt): return np.sin(2*np.pi*pt[0])*np.sin(2*np.pi*pt[1])

    def fun_u(pt): return [\
                      -2*np.pi*np.cos(2*np.pi*pt[0])*np.sin(2*np.pi*pt[1]),
                      -2*np.pi*np.sin(2*np.pi*pt[0])*np.cos(2*np.pi*pt[1])]
    p_ex = interpolate(g, fun_p)
    u_ex = interpolate(g, fun_u)

    """

    return np.array([fun(pt) for pt in g.cell_centers.T]).T


def norm_L2(g: pp.GridLike, val: np.ndarray):
    """
    Compute the L2 norm of a scalar or vector field.

    Parameters
    ----------
    g:
        Grid, or a subclass, with geometry fields computed.
    val:
        Scalar or vector field (dim of val = g.num_cells).

    Return
    ------
    out: double
        The L2 norm of the input field.

    Examples
    --------

    def fun_p(pt): return np.sin(2*np.pi*pt[0])*np.sin(2*np.pi*pt[1])
    p_ex = interpolate(g, fun_p)
    norm_ex = norm_L2(g, p_ex)

    """

    val = np.asarray(val)
    norm_sq = lambda v: np.sum(np.multiply(np.square(v), g.cell_volumes))
    if val.ndim == 1:
        return np.sqrt(norm_sq(val))
    return np.sqrt(np.sum([norm_sq(v) for v in val]))


def l2_error(
    grid: pp.GridLike,
    true_array: np.ndarray,
    approx_array: np.ndarray,
    is_scalar: bool,
    is_cc: bool,
    relative: bool = False,
) -> pp.number:
    """Compute discrete L2-error as given in [1].

    It is possible to compute the absolute error (default) or the relative error.

    Raises:
        NotImplementedError if a mortar grid is given and ``is_cc=False``.
        ZeroDivisionError if the denominator in the relative error is zero.

    Parameters:
        grid: Either a subdomain grid or a mortar grid.
        true_array: Array containing the true values of a given variable.
        approx_array: Array containing the approximate values of a given variable.
        is_scalar: Whether the variable is a scalar quantity. Use ``False`` for
            vector quantities. For example, ``is_scalar=True`` for pressure, whereas
            ``is_scalar=False`` for displacement.
        is_cc: Whether the variable is associated to cell centers. Use ``False``
            for variables associated to face centers. For example, ``is_cc=True``
            for pressures, whereas ``is_scalar=False`` for subdomain fluxes.
        relative: Compute the relative error (if True) or the absolute error (if False).

    Returns:
        Discrete L2-error between the true and approximated arrays.

    References:

        - [1] Nordbotten, J. M. (2016). Stable cell-centered finite volume
          discretization for Biot equations. SIAM Journal on Numerical Analysis,
          54(2), 942-968.

    """
    # Sanity check
    if isinstance(grid, pp.MortarGrid) and not is_cc:
        raise NotImplementedError("Interface variables can only be cell-centered.")

    # Obtain proper measure, e.g., cell volumes for cell-centered quantities and face
    # areas for face-centered quantities.
    if is_cc:
        meas = grid.cell_volumes
    else:
        assert isinstance(grid, pp.Grid)  # to please mypy
        meas = grid.face_areas

    if not is_scalar:
        meas = meas.repeat(grid.dim)

    # Obtain numerator and denominator to determine the error.
    numerator = np.sqrt(np.sum(meas * np.abs(true_array - approx_array) ** 2))
    denominator = np.sqrt(np.sum(meas * np.abs(true_array) ** 2)) if relative else 1.0

    # Deal with the case when the denominator is zero when computing the relative error.
    if np.isclose(denominator, 0):
        raise ZeroDivisionError("Attempted division by zero.")

    return numerator / denominator
