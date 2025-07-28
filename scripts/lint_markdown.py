import sys
import subprocess

def main():
    # Lint all markdown files in the repo using pymarkdown
    result = subprocess.run([
        "pymarkdown", "scan", "--config-file", ".github/markdownlint.config.yaml", "."
    ])
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
