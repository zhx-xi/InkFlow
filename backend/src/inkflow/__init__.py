"""InkFlow — AI 辅助小说创作工具."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# ⚠️ spec §2.4 版本单一来源：从 dist-info 动态读取（tag 注入 → pyproject → dist-info）。
#    PyInstaller 冻结环境经 copy_metadata('inkflow') 携带元数据；
#    源码树直接运行（未安装）时 fallback "0.0.0"（防御性，不抛错）。
try:
    __version__ = _pkg_version("inkflow")
except PackageNotFoundError:
    __version__ = "0.0.0"
