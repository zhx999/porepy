"""Implementation of a degree of freedom manager."""

from __future__ import annotations

import itertools
from typing import Dict, List, Literal, Optional, Sequence, Tuple, Union

import numpy as np
import scipy.sparse as sps

import porepy as pp

__all__ = ["DofManager"]

csc_or_csr_matrix = Union[sps.csc_matrix, sps.csr_matrix]
GridLike = Union[pp.Grid, pp.MortarGrid]


class DofManager:
    """Class to keep track of degrees of freedom in a mixed-dimensional grid with
    several variables.

    This class should be used for setting the state of variables, and to get
    indices of the degrees of freedom for grids and variables.

    Notes:
        Currently both variable types, secondary and primary contribute to the global DOFs.
        The only difference is to where they are stored in the data dictionaries.
        This will change in the near future and the primary variables will **not** be part of
        the global DOF vector.

    Parameters:
        mdg: mixed-dimensional grid representing the computational domain.

    """

    admissible_dof_types: set[str] = {"cells", "faces", "nodes"}
    """A set denoting admissible types of local DOFs for variables.

    - nodes: DOFs per node, which constitute the grid
    - cells: DOFs per cell (center), which are defined by nodes
    - faces: DOFS per face, which form the (polygonal) boundary of cells

    """

    def __init__(self, mdg: pp.MixedDimensionalGrid) -> None:

        self.mdg: pp.MixedDimensionalGrid = mdg
        """Mixed-dimensional grid for which the DOFs are managed."""

        self.full_dof: np.ndarray = np.array([], dtype=int)
        """Array containing the number of DOFS per block index. The block index corresponds
        to this array's indices.

        """

        self.block_dof: Dict[Tuple[Union[pp.Grid, pp.MortarGrid], str], int] = dict()
        """Dictionary containing the block index for a given combination of grid/ mortar grid 
        and variable name (key).

        """

        full_dof, block_dof = self._create_dofs()

        self.full_dof = np.concatenate([self.full_dof, full_dof])
        self.block_dof.update(block_dof)

    def append_dofs(self, var_names: list[str]) -> None:
        """Appends DOFs for a given primary variable.

        This is meant to add DOFs dynamically after the DofManager has been instantiated. 
        I.e., this function looks up the local dofs for given names and appends new DOFs
        to the global system, such that the previous DOFs/indices are not changed.

        Does nothing if the names cannot be found in the data dicts as primary variable.

        Parameters:
            var_names: name(s) of the new variable(s) to be found in the data dictionaries.

        Raises:
            ValueError: if any DOFs have already been added for a name in ``var_names``.

        """

        full_dof, block_dof = self._create_dofs(var_names)
        
        # append the DOFs
        self.full_dof = np.concatenate([self.full_dof, full_dof])
        self.block_dof.update(block_dof)

    def _create_dofs(self, for_vars: Optional[list[str]] = None) -> tuple[np.ndarray, dict]:
        """Creates DOFs to be appended to the already existing global DOFs.
        
        Parameters: 
            for_vars: if given, creates only DOFs for variables with names found in this list.
    
        """
        # Counter for block index
        block_dof_counter = len(self.block_dof)

        # Dictionary that maps node/edge + variable combination to an index.
        block_dof: Dict[Tuple[Union[pp.Grid, pp.MortarGrid], str], int] = {}

        # Storage for number of dofs per variable per node/edge, with respect
        # to the ordering specified in block_dof
        full_dof: List[int] = []

        # Add dofs on nodes
        for sd, data in self.mdg.subdomains(return_data=True):
            # creating dofs only for primary variables
            if pp.PRIMARY_VARIABLES in data:
                for local_var, local_dofs in data[pp.PRIMARY_VARIABLES].items():
                    # filter for which variables DOFs should be created
                    if isinstance(for_vars, list):
                        if local_var not in for_vars:
                            continue

                    # make sure DOFs are not added more than once per combination
                    if (sd, local_var) in self.block_dof.keys():
                        raise ValueError(
                            f"DOFs already present for variable '{local_var}' on "
                            f"subdomain '{sd}'."
                        )

                    # First assign a block index.
                    block_dof[(sd, local_var)] = block_dof_counter
                    block_dof_counter += 1

                    # Count number of dofs for this variable on this grid and store it.
                    # The number of dofs for each dof type defaults to zero.
                    total_local_dofs = (
                        sd.num_cells * local_dofs.get("cells", 0)
                        + sd.num_faces * local_dofs.get("faces", 0)
                        + sd.num_nodes * local_dofs.get("nodes", 0)
                    )
                    full_dof.append(total_local_dofs)
            # creating dofs only for secondary variables.
            # NOTE this will be removed in the near future.
            if pp.SECONDARY_VARIABLES in data:
                for local_var, local_dofs in data[pp.SECONDARY_VARIABLES].items():
                    # filter for which variables DOFs should be created
                    if isinstance(for_vars, list):
                        if local_var not in for_vars:
                            continue

                    # make sure DOFs are not added more than once per combination
                    if (sd, local_var) in self.block_dof.keys():
                        raise ValueError(
                            f"DOFs already present for variable '{local_var}' "
                            f"on subdomain '{sd}'."
                        )

                    # First assign a block index.
                    block_dof[(sd, local_var)] = block_dof_counter
                    block_dof_counter += 1

                    # Count number of dofs for this variable on this grid and store it.
                    # The number of dofs for each dof type defaults to zero.
                    total_local_dofs = (
                        sd.num_cells * local_dofs.get("cells", 0)
                        + sd.num_faces * local_dofs.get("faces", 0)
                        + sd.num_nodes * local_dofs.get("nodes", 0)
                    )
                    full_dof.append(total_local_dofs)

        # Add dofs on edges
        for intf, data in self.mdg.interfaces(return_data=True):
            # creating dofs only for primary variables
            if pp.PRIMARY_VARIABLES in data:
                for local_var, local_dofs in data[pp.PRIMARY_VARIABLES].items():
                    # filter for which variables DOFs should be created
                    if isinstance(for_vars, list):
                        if local_var not in for_vars:
                            continue

                    # make sure DOFs are not added more than once per combination
                    if (intf, local_var) in self.block_dof.keys():
                        raise ValueError(
                            f"DOFs already present for variable '{local_var}' on interface '{intf}'."
                        )

                    # Adding block dof counter
                    block_dof[(intf, local_var)] = block_dof_counter
                    block_dof_counter += 1

                    # We only allow for cell variables on the mortar grids.
                    # This will not change in the foreseeable future
                    total_local_dofs = intf.num_cells * local_dofs.get("cells", 0)
                    full_dof.append(total_local_dofs)
            # creating dofs only for secondary variables.
            # NOTE this will be removed in the near future.
            if pp.SECONDARY_VARIABLES in data:
                for local_var, local_dofs in data[pp.SECONDARY_VARIABLES].items():
                    # filter for which variables DOFs should be created
                    if isinstance(for_vars, list):
                        if local_var not in for_vars:
                            continue

                    # make sure DOFs are not added more than once per combination
                    if (intf, local_var) in self.block_dof.keys():
                        raise ValueError(
                            f"DOFs already present for variable '{local_var}' on interface '{intf}'."
                        )

                    # Adding block dof counter
                    block_dof[(intf, local_var)] = block_dof_counter
                    block_dof_counter += 1

                    # We only allow for cell variables on the mortar grids.
                    # This will not change in the foreseeable future
                    total_local_dofs = intf.num_cells * local_dofs.get("cells", 0)
                    full_dof.append(total_local_dofs)
        
        return np.array(full_dof, dtype=int), block_dof

    def get_variables(self, primary: bool, secondary: bool) -> tuple[str]:
        """Returns a set of all, currently stored variables.

        Parameters:
            primary: if true, includes the primary variables
            secondary: if true, includes the secondary variables

        """
        # a set keeps variable names unique
        vars = set()
        # get vars on subdomains
        for data in self.mdg.subdomain_data():
            if primary:
                vars.add(set(data[pp.PRIMARY_VARIABLES].keys()))
            if secondary:
                vars.add(set(data[pp.SECONDARY_VARIABLES].keys()))
        # get vars on interfaces
        for data in self.mdg.interface_data():
            if primary:
                vars.add(set(data[pp.PRIMARY_VARIABLES].keys()))
            if secondary:
                vars.add(set(data[pp.SECONDARY_VARIABLES].keys()))

        return tuple(vars)

    def num_dofs(
        self,
    ) -> np.int_:
        """Get the number of degrees of freedom in this DofManager.

        Returns:
            np.int_: Size of subsystem.

        """
        return np.sum(self.full_dof)

    def distribute_variable(
        self,
        values: np.ndarray,
        grids: Optional[List[GridLike]] = None,
        variables: Optional[List[str]] = None,
        additive: bool = False,
        to_iterate: bool = False,
    ) -> None:
        """Distribute a vector to the nodes and edges in the MixedDimensionalGrid.

        The intended use is to split a multi-physics solution vector into its
        component parts.

        Parameters:
            values (np.array): Vector to be split. It is assumed that the ordering in
                values coresponds to that implied in self._block_dof and self._full_dof.
                Should have size self.num_dofs(), thus projections from subsets of
                variables must be done before calling this function.
            grids (list of pp.Grid or pp.MortarGrid, optional): The subdomains
                and interfaces to be considered. If not provided, all grids and edges
                found in self.block_dof will be considered.
            variables (list of str, optional): Names of the variables to be
                distributed. If not provided, all variables found in self.block_dof
                will be considered.
            additive (bool, optional): If True, the variables are added to the current
                state or iterate, instead of overwrite the existing value.
            to_iterate (bool, optional): If True, distribute to iterates, and not the
                state itself. Set to True inside a non-linear scheme (Newton), False
                at the end of a time step.

        """
        if grids is None:
            grids = list(set([key[0] for key in self.block_dof]))

        if variables is None:
            variables = list(set([key[1] for key in self.block_dof]))

        # Loop over grid-variable combinations and update data in pp.STATE or pp.ITERATE
        for g, var in itertools.product(grids, variables):
            if (g, var) not in self.block_dof:
                continue

            dof_ind = self.grid_and_variable_to_dofs(g, var)

            if isinstance(g, pp.MortarGrid):
                # This is really an edge
                data = self.mdg.interface_data(g)
            else:
                data = self.mdg.subdomain_data(g)

            if pp.STATE not in data:
                data[pp.STATE] = {}
            if to_iterate and pp.ITERATE not in data[pp.STATE]:
                data[pp.STATE][pp.ITERATE] = {}

            vals = values[dof_ind]
            if additive:
                if to_iterate:
                    data[pp.STATE][pp.ITERATE][var] = (
                        data[pp.STATE][pp.ITERATE][var] + vals
                    )
                else:
                    data[pp.STATE][var] = data[pp.STATE][var] + vals
            else:
                if to_iterate:
                    # Make a copy of the array to avoid nasty bugs
                    # Not sure if this can happen in practice, but better safe than
                    # sorry.
                    data[pp.STATE][pp.ITERATE][var] = vals.copy()
                else:
                    data[pp.STATE][var] = vals.copy()

    def assemble_variable(
        self,
        grids: Optional[List[GridLike]] = None,
        variables: Optional[List[str]] = None,
        from_iterate: bool = False,
    ) -> np.ndarray:
        """Assemble a vector from the variable state stored in nodes and edges in
        the MixedDimensionalGrid.

        Parameters:
            grids (list of grids or grid tuples (interfaces), optional): Names of the
                grids (both subdomains and interfaces) to be assembled from. If not provided,
                all variables found in self.block_dof will be considered.
            variables (list of str, optional): Names of the variables to be
                assembled. If not provided, all variables found in self.block_dof
                will be cosidered.
            from_iterate (bool, optional): If True, assemble from iterates, and not the
                state itself. Set this to True inside a non-linear scheme (Newton), False
                at the end of a time step.

        Returns:
            np.ndarray: Vector, size equal to self.num_dofs(). Values taken from the
                state for those indices corresponding to an active grid-variable
                combination. Other values are set to zero.

        """
        if grids is None:
            grids = list(set([key[0] for key in self.block_dof]))

        if variables is None:
            variables = list(set([key[1] for key in self.block_dof]))

        values = np.zeros(self.num_dofs())

        for g, var in itertools.product(grids, variables):
            if (g, var) not in self.block_dof:
                continue

            dof_ind = self.grid_and_variable_to_dofs(g, var)

            if isinstance(g, pp.MortarGrid):
                # This is really an edge
                data = self.mdg.interface_data(g)
            else:
                data = self.mdg.subdomain_data(g)

            if from_iterate:
                # Use copy to avoid nasty bugs.
                values[dof_ind] = data[pp.STATE][pp.ITERATE][var].copy()
            else:
                values[dof_ind] = data[pp.STATE][var].copy()

        return values

    def dof_var(
        self,
        var: Union[List[str], str],
        return_projection: Optional[bool] = False,
        matrix_format: csc_or_csr_matrix = sps.csr_matrix,
    ) -> Union[np.ndarray, Tuple[np.ndarray, csc_or_csr_matrix]]:
        """Get the indices in the global system of variables given as input on all
        nodes and edges (in the MixedDimensionalGrid sense).

        This method is primarily intended used when equations are assembled with an
        Assembler object. If you use the newer Ad framework (recommended), the
        Ad machinery, and in particular the EquationManager, can deliver subsystems in a
        better way.

        Parameters:
            var (str or list of str): Name or names of the variable. Should be an
                active variable.
            return_projection (bool, optional): Return the projection matrix from for
                selecting only the requested variables. Default to False.
            matrix_format (csc_or_csr_matrix, optional): Format of the projection matrix.
                Default to sps.csr_matrix.

        """
        if not isinstance(var, list):
            var = [var]  # type: ignore
        dofs = np.empty(0, dtype=int)
        dof_start = np.hstack((0, np.cumsum(self.full_dof)))

        grids: Sequence[GridLike] = [sd for sd in self.mdg.subdomains()] + [
            intf for intf in self.mdg.interfaces()  # type: ignore
        ]
        for g in grids:
            for v in var:
                if (g, v) in self.block_dof:
                    block_ind = self.block_dof[(g, v)]
                    local_dofs = np.arange(
                        dof_start[block_ind], dof_start[block_ind + 1]
                    )
                    dofs = np.hstack((dofs, local_dofs))

        if return_projection:
            projection = matrix_format(
                (np.ones(dofs.size), (np.arange(dofs.size), dofs)),
                shape=(dofs.size, np.sum(self.full_dof)),
            )
            return dofs, projection

        return dofs

    def grid_and_variable_to_dofs(self, grid: GridLike, variable: str) -> np.ndarray:
        """Get the indices in the global system of variables associated with a
        given node / edge (in the MixedDimensionalGrid sense) and a given variable.

        Parameters:
            g (pp.Grid or pp.MixedDimensionalGrid edge): Either a grid or an edge in the
                MixedDimensionalGrid.
           variable (str): Name of a variable.

        Returns:
            np.array (int): Index of degrees of freedom for this variable.

        """
        block_ind = self.block_dof[(grid, variable)]
        dof_start = np.hstack((0, np.cumsum(self.full_dof)))
        return np.arange(dof_start[block_ind], dof_start[block_ind + 1])

    def dof_to_grid_and_variable(self, ind: int) -> Tuple[GridLike, str]:
        """Find the grid (or grid pair) and variable name for a degree of freedom,
        specified by its index in the global ordering.

        Parameters:
            ind (int): Index of degree of freedom.

        Returns:
            pp.Grid or pp.MortarGrid: Grid on subdomain, or pair of grids which
                define an interface.
            str: Name of variable.

        Raises:
            ValueError: If the given index is negative or larger than the system size.

        """
        dof_start = np.hstack((0, np.cumsum(self.full_dof)))

        if ind >= dof_start[-1]:
            raise ValueError(f"Index {ind} is larger than system size {dof_start[-1]}")
        elif ind < 0:
            raise ValueError("Dof indices should be non-negative")

        # Find the block index of this grid-variable combination
        block_ind = np.argmax(dof_start > ind) - 1

        # Invert the block-dof map to make reverse loopup easy.
        inv_block_dof: Dict[int, Tuple[GridLike, str]] = {
            v: k for k, v in self.block_dof.items()
        }
        return inv_block_dof[block_ind]  # type: ignore

    def grid_and_variable_block_range(
        self,
        grids: Optional[List[GridLike]] = None,
        variables: Optional[List[str]] = None,
        sort_by: Literal["grids", "variables", ""] = "",
        return_str: bool = False,
    ) -> Dict | str:
        """Get the range of indices in the global system of variables
        associated with combinations of nodes / edges (in the MixedDimensionalGrid sense)
        and variables.

        This function is intended mainly for inquiries into the ordering of blocks
        in systems with multiple variables and/or grids. The results can be returned
        as variables or a string. Both options come with options for sorting of
        the output.

        Parameters:
            grids (pp.Grid or pp.MixedDimensionalGrid edge): List of grids, edges (in the
                MixedDimensionalGrid) or combinations of the two. If not provided, all
            grids and edges that are assigned variables will be considered.
            variables (str): Name of variables. If not provided, all variables assigned
                to at least one grid or variable will be considered).
            sort_by (str): Should take one of the values 'grids', 'variables' or an empty
                str (default). If either grids or variables is specified, the return
                 argument will be sorted according to the corresponding type.
            return_str (bool): If True, information will be returned as a string instead
                of as variables.

        Returns:
            Information on the range for grid-variable combinations. The format will
            depend on the value of sort_by: If set to grids, a dictionary with grids as
            keys will be returned, correspondingly for variables. If not specified,
            unsorted grid-variable combinations are returned.

            If return_str is True, the information will instead be returned as a string,
            with formatting determined on the value of sort_by.

        """
        if grids is None:
            grids = list(set([key[0] for key in self.block_dof]))
        if variables is None:
            variables = list(set([key[1] for key in self.block_dof]))

        # Get the range of all grid-variable combinations.
        # The iteration strategy depends on the specified output format, given by
        # the value of sort_by.
        pairs: Dict = {}
        # TODO: Match-switch, but we're not yet at Python 3.10
        if sort_by == "grids":
            for g in grids:
                this_g = {}
                for var in variables:
                    if (g, var) in self.block_dof:
                        this_g[var] = self._block_range_from_grid_and_var(g, var)
                pairs[g] = this_g
        elif sort_by == "variables":
            for var in variables:
                this_var = {}
                for g in grids:
                    if (g, var) in self.block_dof:
                        this_var[g] = self._block_range_from_grid_and_var(g, var)
                pairs[var] = this_var
        elif sort_by == "":
            for g, var in itertools.product(grids, variables):
                if (g, var) in self.block_dof:
                    pairs[(g, var)] = self._block_range_from_grid_and_var(g, var)
        else:
            s = f"Invalid value for sort_by: {sort_by}."
            s += "Permitted values are 'grids', 'variables' or an empty string"
            raise ValueError(s)

        if return_str:
            # The information should be converted to a string.
            def grid_str(grid) -> str:
                # helper function
                if isinstance(grid, tuple):
                    # This is an interface
                    return f"Grid pair with names {grid[0].name} and {grid[1].name}"
                else:
                    # This is a subdomain
                    return f"Grid with name {grid.name}"

            s = ""
            # Build the string of information according to the specified formatting.
            if sort_by == "grids":
                for g, vals in pairs.items():
                    s += grid_str(g) + "\n"
                    # Loop over variables alphabetically sorted
                    sorted_vars = sorted(list(vals.keys()), key=str.casefold)
                    for var in sorted_vars:
                        limits = vals[var]
                        s += (
                            "\t"
                            + f"Variable: {var}. Range: ({limits[0]}, {limits[1]})"
                            + "\n"
                        )
                    s += "\n"
            elif sort_by == "variables":
                # Loop over variables alphabetically sorted
                sorted_vars = sorted(pairs.keys(), key=str.casefold)
                for var in sorted_vars:
                    s += f"Variable {var}" + "\n"
                    vals = pairs[var]
                    for g, limits in vals.items():
                        s += (
                            "\t"
                            + grid_str(g)
                            + f" Range: ({limits[0]}, {limits[1]})"
                            + "\n"
                        )
                    s += "\n"
            else:
                for key, limits in pairs.items():
                    s += (
                        grid_str(key[0])
                        + f", variable {key[1]}. Range: ({limits[0]}, {limits[1]})"
                        + "\n"
                    )

            return s
        else:
            return pairs

    def _block_range_from_grid_and_var(
        self, g: GridLike, variable: str
    ) -> Tuple[int, int]:
        """Helper function to get the block range for a grid-variable combination
        (start and end of the associated dofs).

        Parameters:
            g (pp.Grid or pp.MortarGrid): Grid on subdomain, or pair of grids which
                define an interface.
            variable (str): Name of variable.

        Returns:
            tuple(int, int): Start and end of the block for this grid-variable combination.
                The end index is the start of the next block.

        """
        block_ind = self.block_dof[(g, variable)]
        dof_start = np.hstack((0, np.cumsum(self.full_dof)))
        return (dof_start[block_ind], dof_start[block_ind + 1])

    def _dof_range_from_grid_and_var(self, g: GridLike, variable: str):
        """Helper function to get the indices for a grid-variable combination.

        Parameters:
            g (pp.Grid or pp.MortarGrid): Grid on subdomain, or pair of grids which
                define an interface.
            variable (str): Name of variable.

        Returns:
            np.ndarray: Indices of the degrees of freedom for this grid-variable combination.

        """
        block_range = self._block_range_from_grid_and_var(g, variable)
        dof_range: np.ndarray = np.arange(block_range[0], block_range[1])
        return dof_range

    def projection_to(self, variables: Sequence[str]) -> sps.spmatrix:
        """Create a projection matrix from the global variable vector to a subspace specified
        by given ``variables``.

        The transpose of the returned matrix can be used to slice respective columns out of a
        global system matrix.

        Parameters:
            variables: names of variables to be projected on. The projection is
                preserving the order defined for the global DOFs.

        Returns:
            sparse projection matrix. Can be rectangular ``MxN``, where ``M<=N`` and ``N`` is
            the current size of the global DOF vector.

        """
        num_global_dofs = self.num_dofs()

        # Array for the dofs associated with each grid-variable combination
        inds = []

        # Loop over variables, find dofs
        for var in variables:
            var_grids = [pair[0] for pair in self.block_dof if pair[1] == var]
            for grid in var_grids:
                inds.append(self.grid_and_variable_to_dofs(grid, var))

        if len(inds) == 0:
            # Special case if no indices were returned
            return sps.csr_matrix((0, num_global_dofs))

        # Create projection matrix. Uniquify indices here, both to sort (will preserve
        # the ordering of the unknowns given by the DofManager) and remove duplicates
        # (in case variables were specified more than once).
        local_dofs = np.unique(np.hstack(inds))
        num_local_dofs = local_dofs.size

        return sps.coo_matrix(
            (np.ones(num_local_dofs), (np.arange(num_local_dofs), local_dofs)),
            shape=(num_local_dofs, num_global_dofs),
        ).tocsr()

    def __str__(self) -> str:
        grid_likes = [key[0] for key in self.block_dof]
        unique_grids = list(set(grid_likes))

        num_grids = 0
        num_interfaces = 0
        for g in unique_grids:
            if isinstance(g, pp.Grid):
                num_grids += 1
            else:
                num_interfaces += 1

        names = [key[1] for key in self.block_dof]
        unique_vars = list(set(names))
        s = (
            f"Degree of freedom manager for {num_grids} "
            f"subdomains and {num_interfaces} interfaces.\n"
            f"Total number of degrees of freedom: {self.num_dofs()}\n"
            "Total number of subdomain and interface variables:"
            f"{len(self.block_dof)}\n"
            f"Variable names: {unique_vars}"
        )

        return s

    def __repr__(self) -> str:

        grid_likes = [key[0] for key in self.block_dof]
        unique_grids = list(set(grid_likes))

        num_grids = 0
        num_interfaces = 0

        dim_max = -1
        dim_min = 4

        for g in unique_grids:
            if isinstance(g, pp.Grid):
                num_grids += 1
                dim_max = max(dim_max, g.dim)
                dim_min = min(dim_min, g.dim)
            else:
                num_interfaces += 1

        s = (
            f"Degree of freedom manager with in total {self.full_dof.sum()} dofs"
            f" on {num_grids} subdomains and {num_interfaces} interface variables.\n"
            f"Maximum grid dimension: {dim_max}\n"
            f"Minimum grid dimension: {dim_min}\n"
        )

        return s
