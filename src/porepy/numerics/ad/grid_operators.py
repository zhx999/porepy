from typing import List, Dict, Tuple, Optional

import numpy as np
import porepy as pp
import scipy.sparse as sps

from .operators import Operator, MergedOperator, Matrix


__all__ = ["MortarProjections", "Divergence", "BoundaryCondition"]


class MortarProjections(Operator):
    def __init__(
        self,
        gb: pp.GridBucket,
        grids: Optional[List[pp.Grid]] = None,
        edges: Optional[List[Tuple[pp.Grid, pp.Grid]]] = None,
        nd=1,
    ):
        if grids is None:
            grids = [g for g, _ in gb.nodes()]
        if edges is None:
            edges = [e for e, _ in gb.edges()]

        face_projection: Dict[pp.Grid, np.ndarray] = {}
        cell_projection: Dict[pp.Grid, np.ndarray] = {}

        tot_num_faces = np.sum([g.num_faces for g in grids])
        tot_num_cells = np.sum([g.num_cells for g in grids])

        face_offset = 0
        cell_offset = 0
        for g in grids:
            face_ind = face_offset + pp.fvutils.expand_indices_nd(
                np.arange(g.num_faces), nd
            )
            cell_ind = cell_offset + pp.fvutils.expand_indices_nd(
                np.arange(g.num_cells), nd
            )

            face_sz, cell_sz = g.num_faces * nd, g.num_cells * nd
            face_projection[g] = sps.coo_matrix(
                (np.ones(face_sz), (face_ind, np.arange(face_sz))),
                shape=(tot_num_faces, face_sz),
            ).tocsr()
            cell_projection[g] = sps.coo_matrix(
                (np.ones(cell_sz), (cell_ind, np.arange(cell_sz))),
                shape=(tot_num_cells, cell_sz),
            ).tocsr()

            # Correct start of the numbering for the next grid
            if g.dim > 0:
                face_offset = face_ind[-1] + 1
            cell_offset = cell_ind[-1] + 1

        # sparse blocks are slow; it should be possible to do a right multiplication
        # of local-to-global mortar indices instead of the block.

        mortar_to_primary_int, mortar_to_primary_avg = [], []
        primary_to_mortar_int, primary_to_mortar_avg = [], []

        mortar_to_secondary_int, mortar_to_secondary_avg = [], []
        secondary_to_mortar_int, secondary_to_mortar_avg = [], []

        for e in edges:
            g_primary, g_secondary = e
            mg: pp.MortarGrid = gb.edge_props(e, "mortar_grid")
            if (g_primary.dim != mg.dim + 1) or g_secondary.dim != mg.dim:
                # This will correspond to DD of sorts; we could handle this
                # by using cell_projections for g_primary and/or
                # face_projection for g_secondary, depending on the exact
                # configuration
                raise NotImplementedError("Non-standard interface.")

            # Projections to primary
            mortar_to_primary_int.append(
                face_projection[g_primary] * mg.mortar_to_primary_int(nd)
            )
            mortar_to_primary_avg.append(
                face_projection[g_primary] * mg.mortar_to_primary_avg(nd)
            )

            # Projections from primary
            primary_to_mortar_int.append(
                mg.primary_to_mortar_int(nd) * face_projection[g_primary].T
            )
            primary_to_mortar_avg.append(
                mg.primary_to_mortar_avg(nd) * face_projection[g_primary].T
            )

            mortar_to_secondary_int.append(
                cell_projection[g_secondary] * mg.mortar_to_secondary_int(nd)
            )
            mortar_to_secondary_avg.append(
                cell_projection[g_secondary] * mg.mortar_to_secondary_avg(nd)
            )

            secondary_to_mortar_int.append(
                mg.secondary_to_mortar_int(nd) * cell_projection[g_secondary].T
            )
            secondary_to_mortar_avg.append(
                mg.secondary_to_mortar_avg(nd) * cell_projection[g_secondary].T
            )

        self.mortar_to_primary_int = Matrix(
            sps.bmat([[m for m in mortar_to_primary_int]]).tocsr()
        )
        self.mortar_to_primary_avg = Matrix(
            sps.bmat([[m for m in mortar_to_primary_avg]]).tocsr()
        )
        self.mortar_to_secondary_int = Matrix(
            sps.bmat([[m for m in mortar_to_secondary_int]]).tocsr()
        )
        self.mortar_to_secondary_avg = Matrix(
            sps.bmat([[m for m in mortar_to_secondary_avg]]).tocsr()
        )
        self.primary_to_mortar_int = Matrix(
            sps.bmat([[m] for m in primary_to_mortar_int]).tocsr()
        )
        self.primary_to_mortar_avg = Matrix(
            sps.bmat([[m] for m in primary_to_mortar_avg]).tocsr()
        )
        self.secondary_to_mortar_int = Matrix(
            sps.bmat([[m] for m in secondary_to_mortar_int]).tocsr()
        )
        self.secondary_to_mortar_avg = Matrix(
            sps.bmat([[m] for m in secondary_to_mortar_avg]).tocsr()
        )


class Divergence(MergedOperator):
    def __init__(self, grids, is_scalar=True):
        self.g = grids
        self.scalar = is_scalar
        self._set_tree(None)


class BoundaryCondition(MergedOperator):
    def __init__(self, keyword, grids):
        self.keyword = keyword
        self.g = grids
        self._set_tree()
