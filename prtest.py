import numpy as np
import porepy as pp

M = pp.composite.PR_Composition()
sys = M.ad_system
nc = sys.mdg.num_subdomain_cells()
vec = np.ones(nc)
h2o = pp.composite.H2O(sys)
co2 = pp.composite.CO2(sys)
# n2 = pp.composite.N2(sys)

L, G = tuple([p for p in M.phases])

M.add_component(h2o)
M.add_component(co2)
# M.add_component(n2)

EPS = 1e-15

temperature = 273.15
pressure = 0.1  # 1 10 20 23
co2_fraction = 0.6
n2_fraction = 0.0
h2o_fraction = 1 - co2_fraction - n2_fraction

sys.set_variable_values(
    h2o_fraction * vec, variables=[h2o.fraction_name], to_iterate=True, to_state=True
)
sys.set_variable_values(
    co2_fraction * vec, variables=[co2.fraction_name], to_iterate=True, to_state=True
)
# sys.set_variable_values(
#     n2_fraction * vec, variables=[n2.fraction_name], to_iterate=True, to_state=True
# )

sys.set_variable_values(
    temperature * vec, variables=[M.T_name], to_iterate=True, to_state=True
)
sys.set_variable_values(
    pressure * vec, variables=[M.p_name], to_iterate=True, to_state=True
)
sys.set_variable_values(0 * vec, variables=[M.h_name], to_iterate=True, to_state=True)

M.initialize()
M.compute_roots()

FLASH = pp.composite.Flash(M, auxiliary_npipm=False)
FLASH.use_armijo = True
FLASH.armijo_parameters["rho"] = 0.9
M.compute_roots()
FLASH.flash("isothermal", "npipm", "feed", True, True)
# FLASH.post_process_fractions()
FLASH.evaluate_specific_enthalpy()
FLASH.evaluate_saturations()
FLASH.print_state()

# isenthalpic procedure, storing only as ITERATE
h = sys.get_variable_values(variables=[M.h_name]) * 1.25
sys.set_variable_values(h, variables=[M.h_name], to_iterate=True, to_state=False)

FLASH.use_armijo = False
FLASH.flash("isenthalpic", "npipm", "iterate", False, True)
# FLASH.post_process_fractions(False)
FLASH.evaluate_saturations(False)
FLASH.print_state(True)  # print state with temperature values after isenthalpic flash

print("DONE")
