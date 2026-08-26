# Debugging Test Failures

Commands shown with pytest defaults. Adapt flags to the discovered test runner.

```bash
# Drop into debugger on failure
<test-runner> --pdb

# Stop on first failure then debug
<test-runner> -x --pdb

# Print stdout during tests
<test-runner> -s

# Show local variables in tracebacks
<test-runner> -l
```

## Flag Comparison

| Flag | Action | pytest | unittest |
|------|--------|--------|----------|
| Debugger on failure | `--pdb` | Yes | `python -m pdb -m unittest` |
| Stop on first failure | `-x` | Yes | `--failfast` |
| Show print output | `-s` | Yes | default |
| Show locals | `-l` | Yes | N/A |
| Shorter tracebacks | `--tb=short` | Yes | N/A |
