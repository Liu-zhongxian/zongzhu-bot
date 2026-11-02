"""Tests for the create_instance factories in intent/llm/memory utils.

Each `create_instance(name, ...)` looks up `core/providers/<type>/<name>/<name>.py`
on disk. We only test:
- the ValueError path for unknown names (no providers need to exist)
- that the signature accepts *args / **kwargs (so all three modules work)

导入 `core.utils.intent` 时会调 `setup_logging()`，以前没有 `data/.config.yaml` 就报错，所以整个文件跳过；
现在 tests/__init__.py 先放好了默认配置，不再跳过。
"""
import pytest

from core.utils import intent, llm, memory


@pytest.mark.parametrize("factory,module_type", [
    (intent.create_instance, "intent"),
    (llm.create_instance, "llm"),
    (memory.create_instance, "memory"),
])
def test_create_instance_raises_for_unknown_class(factory, module_type):
    with pytest.raises(ValueError) as exc_info:
        factory("definitely-not-a-real-provider-name-xyz")
    assert "不支持" in str(exc_info.value) or "不支持的" in str(exc_info.value)


@pytest.mark.parametrize("factory,module_type", [
    (intent.create_instance, "intent"),
    (llm.create_instance, "llm"),
    (memory.create_instance, "memory"),
])
def test_create_instance_accepts_args_and_kwargs(factory, module_type):
    """Even when the provider exists, the call must accept *args and **kwargs.

    We don't need to assert successful creation — just that the signature
    is variadic. We use a sentinel that will fail the path check.
    """
    with pytest.raises(ValueError):
        factory("__missing__", "positional-arg", kwarg="value")