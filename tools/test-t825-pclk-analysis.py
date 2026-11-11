import importlib.util
from pathlib import Path
import unittest
spec = importlib.util.spec_from_file_location('pclk', Path(__file__).with_name('analyze-t825-pclk.py'))
pclk = importlib.util.module_from_spec(spec); spec.loader.exec_module(pclk)

class PclkAnalysis(unittest.TestCase):
    def test_current_boundary(self):
        stack = '[ 1.0] pclk0_clk_src: rcg didn\'t update its configuration.\n' + '\n'.join('x '+x for x in pclk.REQUIRED)
        result = pclk.classify(stack)
        self.assertEqual(result['warning_count'], 1)
        self.assertTrue(result['all_complete_boundary'])
        self.assertEqual(result['classification'], 'fbcon-dsi-pixel-rate-boundary')
        self.assertFalse(result['cause_proven'])

    def test_unknown_stack_is_not_accepted(self):
        result = pclk.classify('[ 2.0] pclk1_clk_src: rcg didn\'t update its configuration.\n')
        self.assertEqual(result['warning_count'], 1)
        self.assertFalse(result['all_complete_boundary'])
        self.assertFalse(result['hardware_fix_accepted'])

if __name__ == '__main__': unittest.main()
