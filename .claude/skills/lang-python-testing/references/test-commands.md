# Test Commands Reference

Commands shown with pytest (the default). Replace with discovered test runner when different.

```bash
# Run all tests
<test-runner>

# Run all tests with verbose output
<test-runner> -v

# Run a specific test file
<test-runner> tests/test_auth.py

# Run a specific test function
<test-runner> tests/test_auth.py::test_login_rejects_expired_token

# Run tests matching a keyword
<test-runner> -k "timeout"

# Run with coverage (branch coverage)
<test-runner> --cov=src/package_name --cov-branch

# Coverage with missing-lines report
<test-runner> --cov=src/package_name --cov-branch --cov-report=term-missing
```

**Note:** Flag syntax varies by runner. The flags above assume pytest. For unittest: `python -m unittest discover`. For coverage.py: `coverage run -m pytest`.
