"""Text-only website adapters. Add a factory entry here to support a new site."""
from .base import TextAdapter


def create_adapter(options, root) -> TextAdapter:
    name = options.get('adapter', 'dsh_web')
    if name == 'dsh_web':
        from .dsh_web import DshWebAdapter
        return DshWebAdapter(options, root)
    raise ValueError(f'未安装网页文本适配器：{name}')
