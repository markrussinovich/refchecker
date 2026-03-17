import subprocess, sys
result = subprocess.run(
    ['git', 'add', '-A'],
    cwd=r'c:\source\refchecker',
    capture_output=True, text=True
)
print('add:', result.returncode, result.stdout, result.stderr)

result = subprocess.run(
    ['git', 'commit', '-m', 'Format bulk hallucination output to match single-paper style'],
    cwd=r'c:\source\refchecker',
    capture_output=True, text=True
)
print('commit:', result.returncode, result.stdout, result.stderr)
