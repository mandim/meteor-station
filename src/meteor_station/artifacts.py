from __future__ import annotations

from io import BytesIO
from pathlib import Path


def normalize_output_path(path: str | Path) -> Path:
    normalized = Path(path).expanduser()
    normalized.parent.mkdir(parents=True, exist_ok=True)
    return normalized.resolve(strict=False)


def save_figure_png(fig, out_path: str | Path, *, dpi: int = 120) -> Path:
    destination = normalize_output_path(out_path)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=dpi)
    destination.write_bytes(buffer.getvalue())
    return destination
