"""用 unittest 跑测试（python -m unittest tests）时的两件事。

1. 配置只用仓库里的 config.yaml，不读本机的 data/.config.yaml。那份文件放个人设置和密钥，clone 下来的仓库里没有；
   后端的不少模块一导入就会检查它（config.settings.check_config_file），没有就报错。这里先把默认配置放进配置缓存，
   导入时就不再去找它，本机跑出来的结果也不受个人配置影响。
2. 跳过给 pytest 写的上游测试（import pytest 或用 tests.conftest 的文件）。conftest 一导入就全局替换 httpx 等网络库，
   和别的测试一起导入时会漏过去，让 Bot、网关等测试失败。这些文件照旧用 pytest 跑。
"""
from pathlib import Path

from config import settings
from config.config_loader import get_project_dir, read_config
from core.utils.cache.manager import CacheType, cache_manager

settings.config_file_valid = True
cache_manager.set(CacheType.CONFIG, "main_config", read_config(get_project_dir() + "config.yaml"))


def _pytest_only(path):
    source = path.read_text(encoding="utf-8")
    return "import pytest" in source or "tests.conftest" in source


def load_tests(loader, standard_tests, pattern):
    root = Path(__file__).parent
    for path in sorted(root.rglob(pattern or "test*.py")):
        if _pytest_only(path):
            continue
        name = ".".join(path.relative_to(root.parent).with_suffix("").parts)
        standard_tests.addTests(loader.loadTestsFromName(name))
    return standard_tests
