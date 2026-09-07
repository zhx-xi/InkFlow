"""#1011 候选 A（自愈依赖同源异常）永久证伪守护锁（GREEN）。

缺陷背景（#1011，已终裁）
-------------------------
服务层自愈链（_extraction_rag.py:489 ``except VectorStoreError``）成立的前提是：store 层
抛出的 VectorStoreError 与服务层捕捉的 VectorStoreError 是 **同一个类对象**。若 PyInstaller
打包时双加载 ``inkflow.domain.ports.extraction_errors``（或任何导入改道），store/服务层各自
持不同的 VectorStoreError 类 → ``except VectorStoreError`` 兜不住 → 自愈恒不触发，且该
分裂在「想当然」下不可见。

本文件把「三者 ``is`` 同一对象 + extraction_errors 模块仅一份实例」锁成守护锁：
- 这是 **GREEN 义务**：现行为（main@）三者已同源 → 全 PASS；
- 若未来任一导入改道 / PyInstaller 双加载 / 复制类对象 → FAIL 报警。

这同时是「候选 A」修复方案的**永久证伪**：若尝试用「强行统一异常类」解决 #1011，本锁会
拦下任何把异常身份改碎的做法；正确解法是走写侧落盘（见 test_vector_write_flush_1011），
而非动异常身份。
"""

from __future__ import annotations

import importlib
import sys

import pytest

_CANONICAL = "inkflow.domain.ports.extraction_errors"
_RAG_MODULE = "inkflow.infrastructure.rag.langchain_vector_store"
_SERVICE_MODULE = "inkflow.domain.services._extraction_rag"


def test_three_modules_share_same_vse_object():
    """store / 服务层 / canonical 三处 VectorStoreError 是同一个类对象。

    依序 import 三个模块后取模块级属性，三者必须 `is` 同一对象——任何一个指向复制类
    （PyInstaller 双加载 / 复制定义）即 FAIL。
    """
    canonical_mod = importlib.import_module(_CANONICAL)
    rag_mod = importlib.import_module(_RAG_MODULE)
    service_mod = importlib.import_module(_SERVICE_MODULE)

    assert rag_mod.VectorStoreError is canonical_mod.VectorStoreError
    assert service_mod.VectorStoreError is canonical_mod.VectorStoreError
    # 额外互证：store 与服务层两处非空且同源（防两个都偏离 canonical 且彼此一致）
    assert rag_mod.VectorStoreError is service_mod.VectorStoreError


def test_extraction_errors_module_single_instance():
    """sys.modules 中 extraction_errors 模块恰好一份实例（防 PyInstaller 双加载）。

    同名字的模块对象在 sys.modules 里理论上唯一，但打包环境可能既注册标准名又注册派生名；
    本用例只认「名为 canonical 的模块恰好 1 个且 id 唯一」。
    """
    instances = [m for m in sys.modules.values() if getattr(m, "__name__", None) == _CANONICAL]
    assert len(instances) == 1, f"extraction_errors 模块应恰好一份实例，实际 {len(instances)}"
    assert len({id(m) for m in instances}) == 1


def test_no_duplicate_vse_class_across_derived_modules():
    """防双加载兜底：任何名字派生自 extraction_errors 的模块，其 VectorStoreError 都必须
    是同一对象（或不存在）。

    遍历 sys.modules，凡模块名 == canonical 或以 ``.extraction_errors`` 结尾且定义了
    VectorStoreError 属性者，该属性必须 `is` canonical 的 VectorStoreError；若存在指向
    **不同**类对象的条目 → 说明出现复制类（双加载），FAIL。
    """
    canonical_mod = sys.modules[_CANONICAL]
    vse = canonical_mod.VectorStoreError

    for name, mod in list(sys.modules.items()):
        modname = getattr(mod, "__name__", "")
        is_derived = modname == _CANONICAL or modname.endswith(".extraction_errors")
        if not is_derived:
            continue
        attr = getattr(mod, "VectorStoreError", None)
        if attr is not None:
            assert (
                attr is vse
            ), f"模块 {name!r} 定义了不同的 VectorStoreError 类对象（异常身份分裂/双加载）"


@pytest.mark.parametrize("module_name", [_RAG_MODULE, _SERVICE_MODULE])
def test_module_actually_exposes_vse_attribute(module_name):
    """前置守护：两个模块都真实暴露 VectorStoreError 属性（防止 import 拉空导致误绿）。"""
    mod = importlib.import_module(module_name)
    assert getattr(mod, "VectorStoreError", None) is not None
    assert mod.__file__ is not None  # 真源文件加载（非 stub）
