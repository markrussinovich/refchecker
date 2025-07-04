#!/usr/bin/env python3
"""
Test runner script
"""

import sys
import os
import subprocess

def main():
    """Run all validation tests"""
    
    # Get the project root directory
    project_root = os.path.dirname(os.path.dirname(__file__))
    tests_dir = os.path.join(project_root, 'tests')
    
    # List of test files to run
    test_files = [
        'validate_refchecker.py',
        'validate_papers.py', 
        'validate_attention_paper.py',
        'validate_local_db.py',
    ]
    
    print("Running RefChecker validation tests...")
    print("=" * 50)
    
    success_count = 0
    total_count = len(test_files)
    
    for test_file in test_files:
        test_path = os.path.join(tests_dir, test_file)
        
        if not os.path.exists(test_path):
            print(f"⚠️  Test file not found: {test_file}")
            continue
            
        print(f"\n🧪 Running {test_file}...")
        try:
            result = subprocess.run([sys.executable, test_path], 
                                  capture_output=True, text=True, cwd=project_root)
            
            if result.returncode == 0:
                print(f"✅ {test_file} passed")
                success_count += 1
            else:
                print(f"❌ {test_file} failed")
                print(f"Error output: {result.stderr}")
                
        except Exception as e:
            print(f"❌ {test_file} failed with exception: {e}")
    
    print("\n" + "=" * 50)
    print(f"Test Results: {success_count}/{total_count} tests passed")
    
    if success_count == total_count:
        print("🎉 All tests passed!")
        return 0
    else:
        print("😞 Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())