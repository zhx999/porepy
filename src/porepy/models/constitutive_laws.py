"""Library of constitutive equations."""
from functools import partial
from typing import Callable, Optional, Union

import numpy as np
import scipy.sparse as sps

import porepy as pp

number = pp.number
Scalar = pp.ad.Scalar


def ad_wrapper(
    vals: Union[number, np.ndarray],
    array: bool,
    size: Optional[int] = None,
    name: Optional[str] = None,
) -> Union[pp.ad.Array, pp.ad.Matrix]:
    """Create ad array or diagonal matrix.

    Utility method.

    Parameters:
        vals: Values to be wrapped. Floats are broadcast to an np array.
        array: Whether to return a matrix or vector.
        size: Size of the array or matrix. If not set, the size is inferred from vals.
        name: Name of ad object.

    Returns:

    """
    if type(vals) is not np.ndarray:
        assert size is not None, "Size must be set if vals is not an array"
        vals: np.ndarray = vals * np.ones(size)

    if array:
        return pp.ad.Array(vals, name)
    else:
        if size is None:
            size = vals.size
        matrix = sps.diags(vals, shape=(size, size))
        return pp.ad.Matrix(matrix, name)


"""
Below are some examples of Mixins which are low-level components of a set of
constitutive equations. First three different versions of fluid density, then one for
permeability.

FIXME: Choose whether materials or the classes below are responsible for expanding to
number of cells. Probably safest to do that below in case of issues with vector values
or cell/face ambiguity.
"""


class DimensionReduction:
    """Apertures and specific volumes."""

    def grid_aperture(self, grid: pp.Grid):
        """FIXME: Decide on how to treat interfaces."""
        aperture = np.ones(grid.num_cells)
        if grid.dim < self.nd:
            aperture *= 0.1
        return aperture

    def aperture(self, subdomains: list[pp.Grid]) -> np.ndarray:
        """
        Aperture is a characteristic thickness of a cell, with units [m].
        1 in matrix, thickness of fractures and "side length" of cross-sectional
        area/volume (or "specific volume") for intersections of dimension 1 and 0.
        See also specific_volume.
        """
        projection = pp.ad.SubdomainProjections(subdomains, dim=1)
        for i, sd in enumerate(subdomains):
            a_loc = ad_wrapper(self.grid_aperture(sd), array=False)
            a_glob = (
                projection.cell_prolongation([sd])
                * a_loc
                * projection.cell_restriction([sd])
            )
            if i == 0:
                apertures = a_glob
            else:
                apertures = apertures + a_glob
        apertures.set_name("aperture")
        return apertures

    def specific_volume(self, subdomains: list[pp.Grid]) -> np.ndarray:
        """Specific volume [m^(nd-d)]

        Aperture is a characteristic thickness of a cell, with units [m].
        1 in matrix, thickness of fractures and "side length" of cross-sectional
        area/volume (or "specific volume") for intersections of dimension 1 and 0.
        See also specific_volume.

        Parameters:
            subdomains: List of subdomain grids.

        Returns:
            Specific volume for each cell.
        """
        # Compute specific volume as the cross-sectional area/volume
        # of the cell, i.e. raise to the power nd-dim
        projection = pp.ad.SubdomainProjections(subdomains, dim=1)
        v: pp.ad.Operator = None
        for dim in range(self.nd + 1):
            sd_dim = [sd for sd in subdomains if sd.dim == dim]
            if len(sd_dim) == 0:
                continue
            a_loc = self.aperture(sd_dim)
            v_loc = a_loc ** Scalar(self.nd + 1 - dim)
            v_glob = (
                projection.cell_prolongation(sd_dim)
                * v_loc
                * projection.cell_restriction(sd_dim)
            )
            if v is None:
                v = v_glob
            else:
                v = v + v_glob
        v.set_name("specific_volume")

        return v


class ConstantFluidDensity:

    """Underforstått:

    def __init__(self, fluid: UnitFluid):
        self.fluid = ...

    eller tilsvarende. Se SolutionStrategiesIncompressibleFlow.
    """

    def fluid_density(self, subdomains: list[pp.Grid]) -> pp.ad.Scalar:
        return Scalar(self.fluid.density(), "fluid_density")


class FluidDensityFromPressure:
    """Fluid density as a function of pressure."""

    def fluid_compressibility(self, subdomains: list[pp.Grid]) -> pp.ad.Scalar:
        return Scalar(self.fluid.compressibility(), "fluid_compressibility")

    def fluid_density(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Fluid density as a function of pressure.

        .. math::
            \\rho = \\rho_0 \\exp \\left[ c_p \\left(p - p_0\\right) \\right]

        with :math:`\\rho_0` the reference density, :math:`p_0` the reference pressure,
        :math:`c_p` the compressibility and :math:`p` the pressure.

        Parameters:
            subdomains: List of subdomain grids.

        Returns:
            Fluid density as a function of pressure.

        """
        exp = pp.ad.Function(pp.ad.exp, "density_exponential")
        # Reference variables are defined in Variables class.
        dp = self.pressure(subdomains) - self.reference_pressure(subdomains)
        # Wrap compressibility from fluid class as matrix (left multiplication with dp)
        c = self.fluid_compressibility(subdomains)
        # I suggest using the fluid's constant density as the reference value. While not
        # explicit, this saves us from defining reference properties i hytt og pine. We
        # could consider letting this class inherit from ConstantDensity (and call super
        # to obtain reference value), but I don't see what the benefit would be.
        rho_ref = Scalar(self.fluid.density(), "reference_fluid_density")
        rho = rho_ref * exp(c * dp)
        return rho


class FluidDensityFromPressureAndTemperature(FluidDensityFromPressure):
    """Extend previous case"""

    def fluid_density(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Fluid density as a function of pressure and temperature."""
        rho = super().fluid_density(subdomains)
        exp = pp.ad.Function(pp.ad.exp, "density_exponential")
        dtemp = self.temperature(subdomains) - self.reference_temperature(
            self, subdomains
        )
        rho = rho * exp(-dtemp / self.fluid.thermal_expansion())
        return rho


class ConstantViscosity:
    def fluid_viscosity(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        return Scalar(self.fluid.viscosity(), "viscosity")


class DarcyFlux:
    """This class could be refactored to reuse for other diffusive fluxes, such as
    heat conduction. It's somewhat cumbersome, though, since potential, discretization,
    and boundary conditions all need to be passed around.
    """

    def pressure_trace(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Pressure on the subdomain boundaries.

        Parameters:
            subdomains: List of subdomains where the pressure is defined.

        Returns:
            Pressure on the subdomain boundaries. Parsing the operator will return a
            face-wise array
        """
        interfaces: list[pp.MortarGrid] = self.subdomains_to_interfaces(subdomains)
        projection = pp.ad.MortarProjections(self.mdg, subdomains, interfaces, dim=1)
        discr = self.darcy_flux_discretization(subdomains)
        p: pp.ad.MixedDimensionalVariable = self.pressure(subdomains)
        pressure_trace = (
            discr.bound_pressure_cell * p
            + discr.bound_pressure_face
            * (projection.mortar_to_primary_int * self.interface_darcy_flux(interfaces))
            + discr.bound_pressure_face * self.bc_values_darcy_flux(subdomains)
            + discr.vector_source * self.vector_source(subdomains, material="fluid")
        )
        return pressure_trace

    def darcy_flux(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Darcy flux.

        Parameters:
            subdomains: List of subdomains where the Darcy flux is defined.

        Returns:
            Face-wise Darcy flux in cubic meters per second.
        """
        interfaces: list[pp.MortarGrid] = self.subdomains_to_interfaces(subdomains)
        projection = pp.ad.MortarProjections(self.mdg, subdomains, interfaces, dim=1)
        discr: pp.ad.Discretization = self.darcy_flux_discretization(subdomains)
        flux: pp.ad.Operator = (
            discr.flux * self.pressure(subdomains)
            + discr.bound_flux
            * (
                self.bc_values_darcy_flux(subdomains)
                + projection.mortar_to_primary_int
                * self.interface_darcy_flux(interfaces)
            )
            + discr.vector_source * self.vector_source(subdomains, material="fluid")
        )
        flux.set_name("Darcy_flux")
        return flux

    def darcy_flux_discretization(
        self, subdomains: list[pp.Grid]
    ) -> pp.ad.Discretization:
        """
        Note:
            The ad.Discretizations may be purged altogether. Their current function is
            very similar to the ad.Geometry in that both basically wrap numpy/scipy
            arrays in ad arrays and collect them in a block matrix. This similarity
            could possibly be exploited. Revisit at some point.

        Parameters:
            subdomains: List of subdomains where the Darcy flux is defined.

        Returns:
            Discretization of the Darcy flux.

        """
        return pp.ad.MpfaAd(self.darcy_discretization_parameter_key, subdomains)

    def vector_source(
        self, grids: Union[list[pp.Grid], list[pp.MortarGrid]], material: str
    ) -> pp.ad.Operator:
        """Vector source term.

        Represents gravity effects. EK: Let's discuss how to name/think about this term.
        Note that it appears slightly differently in a flux and a force/momentum
        balance.

        Parameters:
            grids: List of subdomain or interface grids where the vector source is
            defined. material: Name of the material. Could be either "fluid" or "solid".

        Returns:
            Cell-wise nd-vector source term operator
        """
        val: np.ndarray = self.fluid.convert_units(0, "m*s^-2")
        size = np.sum([g.num_cells for g in grids]) * self.nd
        source: pp.ad.Array = ad_wrapper(
            val, array=True, size=size, name="zero_vector_source"
        )
        return source

    def interface_vector_source(self, interfaces):
        """Interface vector source term.

        The term is the product of unit normals and vector source values. Normalization
        is needed to balance the integration done in the interface flux law.

        Parameters:
            interfaces: List of interfaces where the vector source is defined.

        Returns:
            Face-wise vector source term.
        """
        subdomains = self.interfaces_to_subdomains(interfaces)
        projection = pp.ad.MortarProjections(self.mdg, subdomains, interfaces, dim=self.nd)
        # Expand cell volumes to nd
        # Fixme: Do we need right multiplication with transpose as well?
        cell_volumes = self.wrap_grid_attribute(interfaces, "cell_volumes")
        face_normals = self.wrap_grid_attribute(subdomains, "face_normals")

        # Expand cell volumes to nd
        scalar_to_nd = sum(self.basis(subdomains))
        cell_volumes_inv = scalar_to_nd * cell_volumes ** (-1)
        # Account for sign of boundary face normals
        flip = self.internal_boundary_normal_to_outwards(interfaces)
        unit_outwards_normals = (
            flip * cell_volumes_inv * projection.primary_to_mortar_avg * face_normals
        )
        return unit_outwards_normals * self.vector_source(interfaces)


class AdvectiveFlux:
    def advective_flux(
        self,
        subdomains: list[pp.Grid],
        advected_entity: pp.ad.Operator,
        discr: pp.ad.Discretization,
        bc_values: pp.ad.Operator,
        interface_flux: Callable[[list[pp.MortarGrid]], pp.ad.Operator],
    ) -> pp.ad.Operator:
        """Advective flux.

        Parameters:
            subdomains: List of subdomains.
            advected_entity: Operator representing the advected entity.
            discr: Discretization of the advective flux.
            bc_values: Boundary conditions for the advective flux.
            interface_flux: Interface flux operator/variable.

        Returns:
            Operator representing the advective flux.
        """
        darcy_flux = self.darcy_flux(subdomains)
        interfaces = self.subdomains_to_interfaces(subdomains)
        mortar_projection = pp.ad.MortarProjections(
            self.mdg, subdomains, interfaces, dim=1
        )
        flux: pp.ad.Operator = (
            darcy_flux * (discr.upwind * advected_entity)
            - discr.bound_transport_dir * darcy_flux * bc_values
            # Advective flux coming from lower-dimensional subdomains
            - discr.bound_transport_neu
            * (
                mortar_projection.mortar_to_primary_int * interface_flux(interfaces)
                + bc_values
            )
        )
        return flux

    def interface_advective_flux(
        self,
        interfaces: list[pp.MortarGrid],
        advected_entity: pp.ad.Operator,
        discr: pp.ad.Discretization,
    ) -> pp.ad.Operator:
        """Advective flux on interfaces.

        Parameters:
            interfaces: List of interface grids.

        Returns:
            Operator representing the advective flux on the interfaces.
        """
        # If no interfaces are given, make sure to proceed with a non-empty subdomain
        # list.
        if not interfaces:
            subdomains = self.mdg.subdomains(dim=self.nd)
        else:
            subdomains = self.interfaces_to_subdomains(interfaces)
        mortar_projection = pp.ad.MortarProjections(
            self.mdg, subdomains, interfaces, dim=1
        )
        trace = pp.ad.Trace(subdomains)
        # Project the two advected entities to the interface and multiply with upstream
        # weights and the interface Darcy flux.
        interface_flux: pp.ad.Operator = self.interface_darcy_flux(interfaces) * (
            discr.upwind_primary
            * mortar_projection.primary_to_mortar_avg
            * trace.trace
            * advected_entity
            + discr.upwind_secondary
            * mortar_projection.secondary_to_mortar_avg
            * advected_entity
        )
        return interface_flux


class GravityForce:
    """Gravity force.

    The gravity force is defined as the product of the fluid density and the gravity
    vector:

    .. math::
        g = -\\rho \\mathbf{g}= -\\rho \\begin{bmatrix} 0 \\\\ 0 \\\\ G \\end{bmatrix}

    where :math:`\\rho` is the fluid density, and :math:`G` is the magnitude of the
    gravity acceleration.

    To be used in fluid fluxes and as body force in the force/momentum balance equation.

    TODO: Decide whether to use this or zero as default for Darcy fluxes.
    """

    def gravity_force(
        self, grids: Union[list[pp.Grid], list[pp.MortarGrid]], material: str
    ) -> pp.ad.Operator:
        """Vector source term.

        Represents gravity effects. EK: Let's discuss how to name/think about this term.
        Note that it appears slightly differently in a flux and a force/momentum
        balance.

        Parameters:
            grids: List of subdomain or interface grids where the vector source is
            defined. material: Name of the material. Could be either "fluid" or "solid".

        Returns:
            Cell-wise nd-vector source term operator
        """
        val: np.ndarray = self.fluid.convert_units(pp.GRAVITY_ACCELERATION, "m*s^-2")
        size = np.sum([g.num_cells for g in grids])
        gravity: pp.ad.Array = ad_wrapper(val, array=True, size=size, name="gravity")
        rho = getattr(self, material + "_density")(grids)
        # Gravity acts along the last coordinate direction (z in 3d, y in 2d)
        e_n = self.e_i(grids, i=self.nd - 1, dim=self.nd)
        source = (-1) * rho * e_n * gravity
        source.set_name("gravity_force")
        return source


class LinearElasticMechanicalStress:
    """Linear elastic stress tensor.

    To be used in mechanical problems, e.g. force balance.

    """

    def mechanical_stress(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Linear elastic mechanical stress."""
        for sd in subdomains:
            assert sd.dim == self.nd
        discr = pp.ad.MpsaAd(self.mechanics_discretization_parameter_key, subdomains)
        interfaces = self.subdomains_to_interfaces(subdomains)
        bc = self.bc_values_mechanics(subdomains)
        proj = pp.ad.MortarProjections(self.mdg, subdomains, interfaces, dim=self.nd)
        stress = (
            discr.stress * self.displacement(subdomains)
            + discr.bound_stress * bc
            + discr.bound_stress
            * proj.mortar_to_primary_avg
            * self.interface_displacement(interfaces)
        )
        stress.set_name("mechanical_stress")
        return stress


# Foregriper litt her for å illustrere utvidelse til poromekanikk.
# Det blir
# PoroConstit(LinearElasticSolid, PressureStress):
#    def stress(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
#        return self.pressure_stress(subdomains) + self.mechanical_stress(subdomains)
class PressureStress:
    """Stress tensor from pressure.

    To be used in poromechanical problems.
    """

    pressure: Callable[[list[pp.Grid]], pp.ad.Operator]
    """Pressure variable. Should be defined in the class inheriting from this mixin."""
    reference_pressure: Callable[[list[pp.Grid]], pp.ad.Operator]
    """Reference pressure. Should be defined in the class inheriting from this mixin."""

    def pressure_stress(self, subdomains):
        """Pressure contribution to stress tensor.

        Parameters:
            subdomains: List of subdomains where the stress is defined.

        Returns:
            Pressure stress operator.
        """
        for sd in subdomains:
            assert sd.dim == self.nd
        discr = pp.ad.BiotAd(self.mechanics_parameter_key, subdomains)
        stress: pp.ad.Operator = (
            discr.grad_p * self.pressure(subdomains)
            # The reference pressure is only defined on sd_primary, thus there is no need
            # for a subdomain projection.
            - discr.grad_p * self.reference_pressure(subdomains)
        )
        stress.set_name("pressure_stress")
        return stress


class ConstantSolidDensity:
    def solid_density(self, subdomains: list[pp.Grid]) -> pp.ad.Scalar:
        return Scalar(self.solid.density(), "solid_density")


class LinearElasticSolid(LinearElasticMechanicalStress, ConstantSolidDensity):
    """Linear elastic properties of a solid.

    Includes "primary" stiffness parameters (lame_lambda, shear_modulus) and "secondary"
    parameters (bulk_modulus, lame_mu, poisson_ratio). The latter are computed from the former.
    Also provides a method for computing the stiffness matrix as a FourthOrderTensor.
    """

    def shear_modulus(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Shear modulus [Pa].

        Parameters:
            subdomains: List of subdomains where the shear modulus is defined.

        Returns:
            Cell-wise shear modulus operator [Pa].
        """
        return Scalar(self.solid.shear_modulus(), "shear_modulus")

    def lame_lambda(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Lame's first parameter [Pa].

        Parameters:
            subdomains: List of subdomains where the shear modulus is defined.

        Returns:
            Cell-wise Lame's first parameter operator [Pa].
        """
        return Scalar(self.solid.lame_lambda(), "lame_lambda")

    def youngs_modulus(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Young's modulus [Pa].

        Parameters:
            subdomains: List of subdomains where the Young's modulus is defined.

        Returns:
            Cell-wise Young's modulus in Pascal.
        """
        val = (
            self.solid.shear_modulus()
            * (3 * self.solid.lame_lambda() + 2 * self.solid.shear_modulus())
            / (self.solid.lame_lambda() + self.solid.shear_modulus())
        )
        return Scalar(val, "youngs_modulus")

    def bulk_modulus(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Bulk modulus [Pa]."""
        val = (self.solid.lame_lambda() + 2 * self.solid.shear_modulus()) / 3
        return Scalar(val, "bulk_modulus")

    def stiffness_tensor(self, subdomain: pp.Grid) -> pp.FourthOrderTensor:
        """Stiffness tensor [Pa].

        Parameters:
            subdomain: Subdomain where the stiffness tensor is defined.

        Returns:
            Cell-wise stiffness tensor in SI units.
        """
        lmbda = self.solid.lame_lambda() * np.ones(subdomain.num_cells)
        mu = self.solid.shear_modulus() * np.ones(subdomain.num_cells)
        return pp.FourthOrderTensor(mu, lmbda)


class FracturedSolid:
    """Fractured rock properties.

    This class is intended for use with fracture deformation models.
    """

    def gap(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Fracture gap [m].

        Parameters:
            subdomains: List of subdomains where the gap is defined.

        Returns:
            Cell-wise fracture gap operator [m].
        """
        angle: pp.ad.Operator = self.dilation_angle(subdomains)
        f_norm = pp.ad.Function(
            partial(pp.ad.functions.l2_norm, self.nd - 1), "norm_function"
        )
        f_tan = pp.ad.Function(pp.ad.functions.tan, "tan_function")
        shear_dilation: pp.ad.Operator = f_tan(angle) * f_norm(
            self.tangential_component(subdomains) * self.displacement_jump(subdomains)
        )

        gap = self.reference_gap(subdomains) + shear_dilation
        gap.set_name("gap_with_shear_dilation")
        return gap

    def reference_gap(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Reference gap [m].

        Parameters:
            subdomains: List of fracture subdomains.

        Returns:
            Cell-wise reference gap operator [m].
        """
        return Scalar(self.solid.gap(), "reference_gap")

    def friction_coefficient(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Friction coefficient.

        Parameters:
            subdomains: List of fracture subdomains.

        Returns:
            Cell-wise friction coefficient operator.
        """
        return Scalar(
            self.solid.friction_coefficient(),
            "friction_coefficient",
        )

    def dilation_angle(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Dilation angle [rad].

        Parameters:
            subdomains: List of fracture subdomains.

        Returns:
            Cell-wise dilation angle operator [rad].
        """
        return Scalar(self.solid.dilation_angle(), "dilation_angle")


class FrictionBound:
    """Friction bound for fracture deformation.

    This class is intended for use with fracture deformation models.
    """

    normal_component: Callable[[list[pp.Grid]], pp.ad.Operator]
    """Operator extracting normal component of vector. Should be defined in class combined with
    this mixin."""
    traction: Callable[[list[pp.Grid]], pp.ad.Variable]
    """Traction variable. Should be defined in class combined with from this mixin."""
    friction_coefficient: Callable[[list[pp.Grid]], pp.ad.Operator]
    """Friction coefficient. Should be defined in class combined with this mixin."""

    def friction_bound(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        """Friction bound [m].

        Parameters:
            subdomains: List of fracture subdomains.

        Returns:
            Cell-wise friction bound operator [Pa].

        """
        t_n: pp.ad.Operator = self.normal_component(subdomains) * self.contact_traction(
            subdomains
        )
        bound: pp.ad.Operator = (-1) * self.friction_coefficient(subdomains) * t_n
        bound.set_name("friction_bound")
        return bound


class ConstantPorousMedium:
    def permeability(self, subdomains: list[pp.Grid]) -> pp.SecondOrderTensor:
        """Permeability [m^2].

        This will be set as before (pp.PARAMETERS) since it

        Parameters:
            subdomain: Subdomain where the permeability is defined.
                Permeability is a discretization parameter and is assigned to individual
                subdomain data dictionaries. Hence, the list will usually contain only
                one element.

        Returns:
            Cell-wise permeability tensor.
        """
        assert len(subdomains) == 1, "Only one subdomain is allowed."
        size = subdomains[0].num_cells
        return self.solid.permeability() * np.ones(size)

    def normal_permeability(self, interfaces: list[pp.MortarGrid]) -> pp.ad.Operator:
        return self.solid.normal_permeability()

    def porosity(self, subdomains: list[pp.Grid]) -> pp.ad.Operator:
        return Scalar(self.solid.porosity(), "porosity")


class ConstantSinglePhaseFluid(ConstantFluidDensity, ConstantViscosity):
    """Collection of constant fluid properties.

    This class is intended for use in single-phase flow models.
    """

    ...
