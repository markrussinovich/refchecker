#!/usr/bin/env python3
"""
RefChecker Package Builder

This script builds and optionally publishes the RefChecker package to PyPI.
It handles all the necessary steps for packaging, including cleaning old builds,
building the package, and optionally uploading to PyPI or TestPyPI.

Usage:
    python build_package.py --clean          # Clean only
    python build_package.py --build          # Clean and build
    python build_package.py --test-upload    # Clean, build, and upload to TestPyPI
    python build_package.py --upload         # Clean, build, and upload to PyPI
    python build_package.py --check          # Check package without building
"""

import os
import sys
import subprocess
import shutil
import argparse
from pathlib import Path


class PackageBuilder:
    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root or os.getcwd())
        self.dist_dir = self.project_root / "dist"
        self.build_dir = self.project_root / "build"
        self.egg_info_dirs = list(self.project_root.rglob("*.egg-info"))
        
    def print_status(self, message: str, status: str = "INFO"):
        """Print colored status messages"""
        colors = {
            "INFO": "\033[94m",  # Blue
            "SUCCESS": "\033[92m",  # Green
            "WARNING": "\033[93m",  # Yellow
            "ERROR": "\033[91m",  # Red
            "ENDC": "\033[0m"  # End color
        }
        print(f"{colors.get(status, '')}{status}: {message}{colors['ENDC']}")
    
    def run_command(self, command: list, description: str) -> bool:
        """Run a command and return success status"""
        self.print_status(f"{description}...")
        try:
            result = subprocess.run(
                command, 
                cwd=self.project_root,
                capture_output=True, 
                text=True, 
                check=True
            )
            if result.stdout.strip():
                print(result.stdout)
            self.print_status(f"{description} completed successfully", "SUCCESS")
            return True
        except subprocess.CalledProcessError as e:
            self.print_status(f"{description} failed: {e}", "ERROR")
            if e.stdout:
                print("STDOUT:", e.stdout)
            if e.stderr:
                print("STDERR:", e.stderr)
            return False
    
    def clean_build_artifacts(self):
        """Clean all build artifacts"""
        self.print_status("Cleaning build artifacts...")
        
        # Remove dist directory
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)
            self.print_status(f"Removed {self.dist_dir}")
        
        # Remove build directory
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
            self.print_status(f"Removed {self.build_dir}")
        
        # Remove egg-info directories
        for egg_info in self.egg_info_dirs:
            if egg_info.exists():
                shutil.rmtree(egg_info)
                self.print_status(f"Removed {egg_info}")
        
        # Remove __pycache__ directories
        for pycache in self.project_root.rglob("__pycache__"):
            if pycache.is_dir():
                shutil.rmtree(pycache)
        
        self.print_status("Build artifacts cleaned", "SUCCESS")
    
    def check_prerequisites(self) -> bool:
        """Check if all prerequisites are installed"""
        self.print_status("Checking prerequisites...")
        
        required_packages = ["build", "twine"]
        missing_packages = []
        
        for package in required_packages:
            try:
                subprocess.run([sys.executable, "-c", f"import {package}"], 
                             capture_output=True, check=True)
            except subprocess.CalledProcessError:
                missing_packages.append(package)
        
        if missing_packages:
            self.print_status(f"Missing required packages: {', '.join(missing_packages)}", "ERROR")
            self.print_status("Install with: pip install build twine", "INFO")
            return False
        
        self.print_status("All prerequisites available", "SUCCESS")
        return True
    
    def validate_package_config(self) -> bool:
        """Validate package configuration"""
        self.print_status("Validating package configuration...")
        
        pyproject_file = self.project_root / "pyproject.toml"
        if not pyproject_file.exists():
            self.print_status("pyproject.toml not found", "ERROR")
            return False
        
        # Check for required files
        required_files = ["README.md", "LICENSE"]
        for file in required_files:
            if not (self.project_root / file).exists():
                self.print_status(f"Required file missing: {file}", "ERROR")
                return False
        
        # Check src/refchecker directory structure (proper namespace)
        refchecker_pkg = self.project_root / "src" / "refchecker"
        if not refchecker_pkg.exists():
            self.print_status("src/refchecker/ package directory not found", "ERROR")
            return False
        
        self.print_status("Package configuration valid", "SUCCESS")
        return True
    
    def build_package(self) -> bool:
        """Build the package using python -m build"""
        self.print_status("Building package...")
        
        # Create dist directory
        self.dist_dir.mkdir(exist_ok=True)
        
        # Build the package
        return self.run_command(
            [sys.executable, "-m", "build"],
            "Building wheel and source distribution"
        )
    
    def check_package(self) -> bool:
        """Check the built package with twine"""
        if not self.dist_dir.exists() or not list(self.dist_dir.glob("*")):
            self.print_status("No packages found to check. Build first.", "ERROR")
            return False
        
        return self.run_command(
            [sys.executable, "-m", "twine", "check", "dist/*"],
            "Checking package integrity"
        )
    
    def upload_to_testpypi(self) -> bool:
        """Upload package to TestPyPI"""
        self.print_status("Uploading to TestPyPI...", "WARNING")
        self.print_status("You will be prompted for TestPyPI credentials", "INFO")
        
        return self.run_command(
            [sys.executable, "-m", "twine", "upload", "--repository", "testpypi", "dist/*"],
            "Uploading to TestPyPI"
        )
    
    def upload_to_pypi(self) -> bool:
        """Upload package to PyPI"""
        self.print_status("Uploading to PyPI...", "WARNING")
        self.print_status("You will be prompted for PyPI credentials", "INFO")
        
        # Confirm upload
        response = input("Are you sure you want to upload to PyPI? (yes/no): ")
        if response.lower() != "yes":
            self.print_status("Upload cancelled by user", "WARNING")
            return False
        
        return self.run_command(
            [sys.executable, "-m", "twine", "upload", "dist/*"],
            "Uploading to PyPI"
        )
    
    def show_package_info(self):
        """Show information about built packages"""
        if not self.dist_dir.exists():
            self.print_status("No packages found", "WARNING")
            return
        
        packages = list(self.dist_dir.glob("*"))
        if not packages:
            self.print_status("No packages found", "WARNING")
            return
        
        self.print_status("Built packages:")
        for package in packages:
            size = package.stat().st_size / 1024  # KB
            self.print_status(f"  {package.name} ({size:.1f} KB)")


def main():
    parser = argparse.ArgumentParser(
        description="Build and publish RefChecker package",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_package.py --build              # Clean and build package
  python build_package.py --test-upload        # Build and upload to TestPyPI
  python build_package.py --upload             # Build and upload to PyPI
  python build_package.py --check              # Just check existing package
  python build_package.py --clean --build      # Clean, then build
        """
    )
    
    parser.add_argument("--clean", action="store_true", 
                       help="Clean build artifacts")
    parser.add_argument("--build", action="store_true",
                       help="Build the package")
    parser.add_argument("--check", action="store_true",
                       help="Check package integrity")
    parser.add_argument("--test-upload", action="store_true",
                       help="Upload to TestPyPI")
    parser.add_argument("--upload", action="store_true",
                       help="Upload to PyPI (production)")
    parser.add_argument("--project-root", type=str,
                       help="Project root directory (default: current directory)")
    
    args = parser.parse_args()
    
    # If no action specified, default to build
    if not any([args.clean, args.build, args.check, args.test_upload, args.upload]):
        args.build = True
    
    builder = PackageBuilder(args.project_root)
    success = True
    
    try:
        # Clean if requested or if building/uploading
        if args.clean or args.build or args.test_upload or args.upload:
            builder.clean_build_artifacts()
        
        # Build if requested or if uploading
        if args.build or args.test_upload or args.upload:
            if not builder.check_prerequisites():
                return 1
            
            if not builder.validate_package_config():
                return 1
            
            if not builder.build_package():
                return 1
        
        # Check package
        if args.check or args.test_upload or args.upload:
            if not builder.check_package():
                success = False
        
        # Upload to TestPyPI
        if args.test_upload:
            if not builder.upload_to_testpypi():
                success = False
        
        # Upload to PyPI
        if args.upload:
            if not builder.upload_to_pypi():
                success = False
        
        # Show package information
        builder.show_package_info()
        
        if success:
            builder.print_status("All operations completed successfully!", "SUCCESS")
            return 0
        else:
            builder.print_status("Some operations failed", "ERROR")
            return 1
            
    except KeyboardInterrupt:
        builder.print_status("Operation cancelled by user", "WARNING")
        return 1
    except Exception as e:
        builder.print_status(f"Unexpected error: {e}", "ERROR")
        return 1


if __name__ == "__main__":
    sys.exit(main())