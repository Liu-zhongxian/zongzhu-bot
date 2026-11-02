"""Test for the auto-import mechanism in plugins_func/loadplugins.py.

We import a real subpackage (`plugins_func.functions`) and verify the
import side-effect runs. This protects against accidentally deleting
`auto_import_modules` from `app.py` startup code.

导入 `plugins_func.functions` 会连带导入 cache_manager 等，以前没有 `data/.config.yaml` 就报错，所以跳过；
现在 tests/__init__.py 先放好了默认配置，不再跳过。
"""
import unittest

from plugins_func.functions import get_time  # noqa: F401


class LoadPluginsTest(unittest.TestCase):
    def test_functions_package_importable(self):
        """If this test runs, plugins_func.functions.__init__.py has been imported."""
        import plugins_func.functions as fns
        self.assertTrue(hasattr(fns, "get_time"))