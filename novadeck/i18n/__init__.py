import json
from importlib.resources import files


def translations(language: str = "es") -> dict[str, str]:
    if language not in ("es", "en"):
        raise ValueError("unsupported_language")
    return json.loads(files(__package__).joinpath(f"{language}.json").read_text(encoding="utf-8"))
