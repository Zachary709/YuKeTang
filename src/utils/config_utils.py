from pathlib import Path
from typing import Any, Dict

from src.utils.logging_utils import log_warning


_CONFIG_CACHE: Dict[str, Any] | None = None


def _parse_simple_yaml(path: Path) -> Dict[str, Any]:
    """
    非常简易的 YAML 解析器，只支持：

    key: value

    这种一行一个 KV 的形式，value 可选用引号包裹。
    足够覆盖本项目的简单配置使用场景。
    """
    result: Dict[str, Any] = {}
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            # 去掉包裹的单/双引号
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            result[key] = value
    return result


def load_config() -> Dict[str, Any]:
    """
    读取项目根目录下的 config.yml，结果缓存在内存中。
    如文件不存在或解析失败，返回空字典。
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    try:
        project_root = Path(__file__).resolve().parents[2]
        cfg_path = project_root / "config.yml"
        if not cfg_path.exists():
            _CONFIG_CACHE = {}
            return _CONFIG_CACHE

        _CONFIG_CACHE = _parse_simple_yaml(cfg_path)
        return _CONFIG_CACHE
    except Exception as exc:
        log_warning(f"加载 config.yml 失败，将使用默认配置。原因：{exc}")
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE


def get_config_value(key: str, default: Any | None = None) -> Any:
    """
    获取指定配置项，不存在则返回 default。
    """
    cfg = load_config()
    return cfg.get(key, default)


def get_default_comment() -> str:
    """
    获取默认评论内容。
    """
    return str(
        get_config_value(
            "default_comment",
            "None",
        )
    )


def get_dashscope_api_key() -> str | None:
    """
    获取用于调用 DashScope(OpenAI 兼容) 接口的 API Key。
    """
    key = str(get_config_value("DASHSCOPE_API_KEY", "") or "").strip()
    return key or None


def get_llm_model_name() -> str:
    """
    获取用于生成评论的 LLM 模型名称。
    """
    return str(
        get_config_value(
            "LLM_MODEL",
            "qwen3-30b-a3b-thinking-2507",
        )
    )


def get_llm_base_url() -> str:
    """
    获取 OpenAI 兼容接口的 base_url。
    """
    return str(
        get_config_value(
            "LLM_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )


