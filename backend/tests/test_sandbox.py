import pandas as pd
import pytest

from app.sandbox.executor import CodeValidationError, netns_available, run_code, validate_code


@pytest.fixture
def data(tmp_path):
    p = tmp_path / "data.csv"
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(p, index=False)
    return p


@pytest.mark.parametrize("src", [
    "import os\nos.system('id')",
    "import subprocess",
    "import socket",
    "open('/etc/passwd').read()",
    "__import__('os')",
    "eval('1+1')",
])
def test_static_validation_blocks(src):
    with pytest.raises(CodeValidationError):
        validate_code(src)


def test_allowed_code_runs(data, tmp_path):
    src = "import ifrt\nimport pandas as pd\ndf = ifrt.load_df()\nifrt.metric('n', float(len(df)))\nifrt.emit()\n"
    r = run_code(src, data, tmp_path / "run")
    assert r.ok, r.stderr or r.error
    assert "n" in str(r.result.get("metrics"))


def test_runtime_file_read_blocked(data, tmp_path):
    # bypass the AST layer by obfuscation: the audit hook must still stop it
    src = "import pandas as pd\npd.read_csv('/etc/passwd')\n"
    r = run_code(src, data, tmp_path / "run2")
    assert not r.ok


def test_timeout(data, tmp_path):
    r = run_code("while True:\n    pass\n", data, tmp_path / "run3", timeout_s=2)
    assert not r.ok
    assert r.timed_out or "cpu" in (r.error or "").lower() or "time" in (r.error or "").lower()


def test_network_isolation_reported(data, tmp_path):
    r = run_code("x = 1\n", data, tmp_path / "run4")
    assert "network" in str(r.isolation).lower() or r.isolation is not None
    assert isinstance(netns_available(), bool)
