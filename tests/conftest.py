"""InkFlow 测试配置和共享 fixture。"""

import pytest


@pytest.fixture
def sample_project_data():
    return {
        "name": "测试小说",
        "genre": "玄幻",
        "language": "zh-CN",
        "target_words": 100000,
    }
