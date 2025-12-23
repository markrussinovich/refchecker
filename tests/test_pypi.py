"""
Unit tests for PyPI package installation verification.

Tests verify that the academic-refchecker package is correctly structured
for both editable development installs and regular PyPI installations.
"""

import sys
import subprocess
import unittest
import importlib.metadata


class TestPackageInstallation(unittest.TestCase):
    """Test package installation location and structure."""

    def test_package_location(self):
        """Test that refchecker package is installed in correct location."""
        import refchecker
        loc = refchecker.__file__
        
        # Accept both editable and regular installs
        is_editable = '/refchecker/refchecker/' in loc
        is_regular = 'site-packages/refchecker/' in loc
        
        self.assertTrue(
            is_editable or is_regular,
            f"Package installed in unexpected location: {loc}"
        )
        
        if is_editable:
            print(f"\n   ℹ Editable install detected: {loc}")
        else:
            print(f"\n   ✓ Regular install detected: {loc}")


class TestNamespacePollution(unittest.TestCase):
    """Test that package doesn't pollute top-level namespace."""

    def test_no_top_level_pollution(self):
        """Test that submodules are not importable at top level."""
        # These should not exist as top-level modules in site-packages
        bad_modules = ['checkers', 'config', 'core', 'utils', 'llm', 'services']
        polluted = []
        
        for mod_name in bad_modules:
            try:
                m = __import__(mod_name)
                # Only consider it pollution if it's in site-packages at top level
                if hasattr(m, '__file__') and f'site-packages/{mod_name}' in m.__file__:
                    polluted.append(mod_name)
            except ImportError:
                pass  # Good - not importable
        
        self.assertEqual(
            polluted, [],
            f"Found top-level pollution in site-packages: {polluted}"
        )


class TestSubmoduleImports(unittest.TestCase):
    """Test that all submodules can be imported correctly."""

    def test_checkers_module(self):
        """Test importing checkers submodule."""
        from refchecker.checkers import semantic_scholar
        self.assertTrue(hasattr(semantic_scholar, '__file__'))
        self.assertIn('refchecker', semantic_scholar.__file__)

    def test_config_module(self):
        """Test importing config submodule."""
        from refchecker.config import settings
        self.assertTrue(hasattr(settings, '__file__'))
        self.assertIn('refchecker', settings.__file__)

    def test_core_module(self):
        """Test importing core submodule."""
        from refchecker.core import refchecker as rc
        self.assertTrue(hasattr(rc, '__file__'))
        self.assertIn('refchecker', rc.__file__)

    def test_utils_module(self):
        """Test importing utils submodule."""
        from refchecker.utils import text_utils
        self.assertTrue(hasattr(text_utils, '__file__'))
        self.assertIn('refchecker', text_utils.__file__)

    def test_llm_module(self):
        """Test importing llm submodule."""
        from refchecker.llm import base
        self.assertTrue(hasattr(base, '__file__'))
        self.assertIn('refchecker', base.__file__)

    def test_all_submodules_under_refchecker(self):
        """Test that all submodules are under refchecker namespace."""
        test_modules = [
            'refchecker.checkers.semantic_scholar',
            'refchecker.checkers.crossref',
            'refchecker.config.settings',
            'refchecker.core.refchecker',
            'refchecker.utils.text_utils',
            'refchecker.llm.base',
        ]
        
        for mod_name in test_modules:
            with self.subTest(module=mod_name):
                __import__(mod_name)
                m = sys.modules[mod_name]
                self.assertTrue(
                    'site-packages/refchecker/' in m.__file__ or '/refchecker/refchecker/' in m.__file__,
                    f"Module {mod_name} not under refchecker namespace: {m.__file__}"
                )


class TestCLIEntryPoint(unittest.TestCase):
    """Test CLI entry point functionality."""

    def test_cli_command_exists(self):
        """Test that academic-refchecker CLI command works."""
        result = subprocess.run(
            ['academic-refchecker', '--help'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        self.assertEqual(result.returncode, 0, "CLI command failed")
        self.assertIn('academic-refchecker', result.stdout, "CLI help output missing")

    def test_cli_version(self):
        """Test that CLI version command works."""
        result = subprocess.run(
            ['academic-refchecker', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Either succeeds or shows version in stderr
        self.assertTrue(
            result.returncode == 0 or 'Refchecker v' in result.stdout + result.stderr,
            "CLI version command failed"
        )


class TestMainClassImport(unittest.TestCase):
    """Test main class imports."""

    def test_arxiv_reference_checker_import(self):
        """Test that main ArxivReferenceChecker class can be imported."""
        from refchecker.core.refchecker import ArxivReferenceChecker
        
        self.assertTrue(callable(ArxivReferenceChecker))
        self.assertEqual(ArxivReferenceChecker.__module__, 'refchecker.core.refchecker')


class TestPackageMetadata(unittest.TestCase):
    """Test package metadata."""

    def test_package_metadata_exists(self):
        """Test that package metadata is accessible."""
        try:
            metadata = importlib.metadata.metadata('academic-refchecker')
            
            self.assertEqual(metadata['Name'], 'academic-refchecker')
            self.assertIsNotNone(metadata.get('Version'))
            
            print(f"\n   ✓ Package: {metadata['Name']} v{metadata['Version']}")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("Package metadata not found (not installed)")


def print_summary():
    """Print installation summary after tests."""
    print("\n" + "="*70)
    print(" 📦 Package Installation Summary")
    print("="*70)
    print("   PyPI name:    academic-refchecker")
    print("   Import name:  refchecker")
    print("   CLI command:  academic-refchecker")
    print("   Namespace:    refchecker.checkers, refchecker.core, etc.")
    print("\n💡 Users install with:")
    print("   pip install academic-refchecker")
    print("\n   And use with:")
    print("   import refchecker")
    print("   from refchecker.core.refchecker import ArxivReferenceChecker")
    print("   academic-refchecker --help")
    print("="*70)


if __name__ == '__main__':
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    
    # Print summary if all tests passed
    if result.wasSuccessful():
        print_summary()
    
    sys.exit(0 if result.wasSuccessful() else 1)