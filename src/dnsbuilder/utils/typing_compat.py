try:
    # Python 3.12+
    from typing import override  # type: ignore
except Exception:
    try:
        from typing_extensions import override  # type: ignore
    except Exception:
        def override(func):  # type: ignore
            return func