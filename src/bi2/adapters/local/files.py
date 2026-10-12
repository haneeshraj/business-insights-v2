"""A run's files, such as screenshots and logos, kept in a folder on this machine."""

import asyncio
from pathlib import Path, PurePosixPath


class LocalFiles:
    """Saves and reads files under one output folder. Paths are relative to it and can't
    reach outside it."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _place(self, path: str) -> Path:
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"{path!r} isn't a path inside the output folder")
        return self._root.joinpath(*relative.parts)

    async def save(self, path: str, data: bytes) -> str:
        place = self._place(path)

        def write() -> None:
            place.parent.mkdir(parents=True, exist_ok=True)
            place.write_bytes(data)

        await asyncio.to_thread(write)
        return path

    async def read(self, path: str) -> bytes:
        return await asyncio.to_thread(self._place(path).read_bytes)
