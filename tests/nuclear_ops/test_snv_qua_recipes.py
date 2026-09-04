import importlib.util
import unittest

from qudi.logic.nuclear_ops.models import ExperimentSpec, ReadoutStep, ScanAxis
from qudi.logic.nuclear_ops.recipes import RecipeContext, RecipeRegistry
from qudi.logic.nuclear_ops.scan_planner import ScanPlanner
from qudi.logic.nuclear_ops.snv_qua_recipes import register_recipes
from qudi.logic.nuclear_ops.thresholds import ThresholdRegistry


@unittest.skipUnless(importlib.util.find_spec("qm"), "QM QUA SDK is not installed")
class SnVQuaRecipeTest(unittest.TestCase):
    def test_all_builtin_recipes_generate_qua_against_the_setup_configuration(self):
        from qm import generate_qua_script
        from qudi.hardware.OPX.configuration import config

        axes = {
            "nuclear_rabi": ScanAxis("pulse_length", (100, 200), unit="ns", execution="qua"),
            "ramsey": ScanAxis("tau", (100, 200), unit="ns", execution="qua"),
            "hahn_echo": ScanAxis("tau", (100, 200), unit="ns", execution="qua"),
            "t1": ScanAxis("readout_delay", (1_000, 2_000), unit="ns", execution="qua"),
            "pulsed_odmr": ScanAxis("MW_f", (190_000_000, 191_000_000), unit="Hz", execution="qua"),
            "ssr_calibration": ScanAxis("sweeps", (0, 1), execution="qua"),
        }
        registry = RecipeRegistry()
        register_recipes(registry)

        self.assertEqual(set(registry.names), set(axes))
        for name, axis in axes.items():
            recipe = registry.get(name)
            experiment = ExperimentSpec(
                recipe=name,
                name=name,
                scan_axes=(axis,),
                parameters={"integrations": 2},
                readout=(ReadoutStep("ssr", "ssr_e1", "result_counts"),),
            )
            recipe.validate(experiment)
            block = ScanPlanner(recipe.axis_policies).plan(experiment).blocks[0]
            bundle = recipe.build_program(
                RecipeContext(
                    experiment=experiment,
                    block=block,
                    thresholds=ThresholdRegistry().snapshot_for_experiment(experiment),
                )
            )
            source = generate_qua_script(bundle.program, config)
            self.assertIn("result_counts", source)


if __name__ == "__main__":
    unittest.main()
