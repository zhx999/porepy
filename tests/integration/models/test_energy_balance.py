"""Tests for energy balance.

"""
from typing import Callable

import numpy as np
import pytest

import porepy as pp

from .setup_utils import MassAndEnergyBalance
from .test_mass_balance import BoundaryConditionLinearPressure


class BoundaryCondition(BoundaryConditionLinearPressure):
    domain_boundary_sides: Callable[
        [pp.Grid],
        tuple[
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
        ],
    ]
    """Utility function to access the domain boundary sides."""
    fluid: pp.FluidConstants
    """Fluid object."""

    def bc_values_fourier(self, subdomains: list[pp.Grid]) -> pp.ad.Array:
        """

        Parameters:
            subdomains: List of subdomains on which to define boundary conditions.

        Returns:
            Array of boundary values.

        """
        # Define boundary regions
        values = []
        for sd in subdomains:
            _, _, west, *_ = self.domain_boundary_sides(sd)
            val_loc = np.zeros(sd.num_faces)
            val_loc[west] = 1
            values.append(val_loc)
        return pp.wrap_as_ad_array(np.hstack(values), name="bc_values_fourier")

    def bc_type_fourier(self, sd: pp.Grid) -> pp.BoundaryCondition:
        """Dirichlet conditions on all external boundaries.

        Parameters:
            sd: Subdomain grid on which to define boundary conditions.

        Returns:
            Boundary condition object.
        """
        # Define boundary regions
        _, east, west, *_ = self.domain_boundary_sides(sd)
        # Define Dirichlet conditions on the left and right boundaries
        return pp.BoundaryCondition(sd, east + west, "dir")

    def bc_values_enthalpy_flux(self, subdomains: list[pp.Grid]) -> pp.ad.Array:
        """Boundary values for the enthalpy.


        Parameters:
            subdomains: List of subdomains.

        Returns:
            Array with boundary values for the enthalpy.

        """
        # List for all subdomains
        values = []

        # Loop over subdomains to collect boundary values
        for sd in subdomains:
            # Get enthalpy values on boundary faces applying trace to interior values.
            _, _, west, *_ = self.domain_boundary_sides(sd)
            vals = np.zeros(sd.num_faces)
            vals[west] = self.fluid.specific_heat_capacity() * 1
            # Append to list of boundary values
            values.append(vals)

        # Concatenate to single array and wrap as ad.Array
        bc_values = pp.wrap_as_ad_array(np.hstack(values), name="bc_values_enthalpy")
        return bc_values


class EnergyBalanceTailoredBCs(BoundaryCondition, MassAndEnergyBalance):
    pass


@pytest.mark.parametrize(
    "fluid_vals,solid_vals",
    [
        (
            {"thermal_conductivity": 1e-10},
            {
                "thermal_conductivity": 1e-10,
                "permeability": 1e-2,
                "specific_heat_capacity": 1e3,
            },
        ),
        (
            {"thermal_conductivity": 1e5},
            {"thermal_conductivity": 1e4, "permeability": 1e-7},
        ),
    ],
)
def test_advection_or_diffusion_dominated(fluid_vals, solid_vals):
    """Test that the pressure solution is linear.

    With constant density (zero compressibility) and the specified boundary conditions,
    the pressure solution should be linear, i.e., ::math::
        p = 1 - x
        v_x = 1 * k / x_max

    We test one advection dominated and one diffusion dominated case. For the former,
    the influx is approx. w_in = v_x * specific_heat_capacity, yielding an added energy
    close to time * w_in. w_in also gives an upper bound for internal advective fluxes.
    For the latter, we check that a near linear temperature profile is obtained.

    Parameters:
        fluid_vals (dict): Dictionary with keys as those in :class:`pp.FluidConstants`
            and corresponding values.
        solid_vals (dict): Dictionary with keys as those in :class:`pp.SolidConstants`
            and corresponding values.

    """
    # Always use zero compressibility
    fluid_vals["compressibility"] = 0
    # Instantiate constants and store in params.
    fluid = pp.FluidConstants(fluid_vals)
    solid = pp.SolidConstants(solid_vals)
    params = {
        "suppress_export": True,  # Suppress output for tests
        "material_constants": {"fluid": fluid, "solid": solid},
    }

    # Create model and run simulation
    setup = EnergyBalanceTailoredBCs(params)
    pp.run_time_dependent_model(setup, params)

    if solid_vals["thermal_conductivity"] > 1:
        # Diffusion dominated case.
        # Check that the temperature is linear.
        for sd in setup.mdg.subdomains():
            var = setup.equation_system.get_variables(["temperature"], [sd])
            vals = setup.equation_system.get_variable_values(var)
            assert np.allclose(
                vals, 1 - sd.cell_centers[0] / setup.domain_bounds["xmax"], rtol=1e-4
            )
    else:
        # Advection dominated case.
        # Check that the enthalpy flux over each face is bounded by the value
        # corresponding to a fully saturated domain.
        for sd in setup.mdg.subdomains():
            val = setup.enthalpy_flux([sd]).evaluate(setup.equation_system).val
            # Account for specific volume, default value of .01 in fractures.
            normals = np.abs(sd.face_normals[0]) * np.power(0.1, setup.nd - sd.dim)
            k = setup.solid.permeability() / setup.fluid.viscosity()
            grad = 1 / setup.domain_bounds["xmax"]
            enth = setup.fluid.specific_heat_capacity() * normals * grad * k
            assert np.all(np.abs(val) < np.abs(enth) + 1e-10)

        # Total advected matrix energy: (bc_val=1) * specific_heat * (time=1 s) * (total
        # influx =grad * dp * k=1/2*k)
        total_energy = (
            setup.total_internal_energy(setup.mdg.subdomains(dim=2))
            .evaluate(setup.equation_system)
            .val
        )
        expected = setup.fluid.specific_heat_capacity() * setup.solid.permeability() / 2
        assert np.allclose(np.sum(total_energy), expected, rtol=1e-3)
