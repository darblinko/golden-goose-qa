import pytest
from gg_synthdata.cli import cmd_generate


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("corpus")
    assert cmd_generate(out_dir, seed=42) == 0
    return out_dir / "corpus"
