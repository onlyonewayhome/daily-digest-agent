import copy

import pytest
import yaml


@pytest.fixture
def valid_config():
    return copy.deepcopy(yaml.safe_load(open("config/example.yaml", encoding="utf-8")))
