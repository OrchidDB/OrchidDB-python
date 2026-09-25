import ctypes
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any

class CompilationError(ValueError):
    pass

@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    fields: tuple[str, ...]
    dialect: str
    version: int = 1

class Compiler:
    """Owns a library handle, never a database. Calls release native strings reliably."""
    def __init__(self, library: str | os.PathLike | None = None):
        name = {"Darwin": "liborchiddb_compiler.dylib", "Linux": "liborchiddb_compiler.so", "Windows": "orchiddb_compiler.dll"}.get(platform.system())
        path = library or os.environ.get("ORCHIDDB_NATIVE_LIBRARY") or Path(__file__).parent / "native" / str(name)
        self._lib = ctypes.CDLL(str(path))
        self._lib.orchiddb_abi_version.restype = ctypes.c_uint32
        if self._lib.orchiddb_abi_version() != 1:
            raise RuntimeError("Incompatible OrchidDB compiler ABI; expected 1")
        self._lib.orchiddb_compile_json.argtypes = [ctypes.c_char_p]
        self._lib.orchiddb_compile_json.restype = ctypes.c_void_p
        self._lib.orchiddb_string_free.argtypes = [ctypes.c_void_p]
        self._lib.orchiddb_string_free.restype = None
        self._lib.orchiddb_core_revision.restype = ctypes.c_char_p
        self.core_revision = self._lib.orchiddb_core_revision().decode()
        pin = Path(__file__).with_name("CORE_REVISION")
        expected = pin.read_text().strip() if pin.exists() else None
        explicit = library or os.environ.get("ORCHIDDB_NATIVE_LIBRARY")
        if expected and self.core_revision != expected and not (explicit and self.core_revision == expected + "-dirty"):
            raise RuntimeError("Compiler core revision does not match this client")

    def compile(self, request: Mapping[str, Any]) -> CompiledQuery:
        payload = json.dumps(dict(request), ensure_ascii=False, allow_nan=False).encode("utf-8")
        pointer = self._lib.orchiddb_compile_json(payload)
        if not pointer:
            raise RuntimeError("Native compiler returned a null pointer")
        try:
            response = json.loads(ctypes.string_at(pointer))
        finally:
            self._lib.orchiddb_string_free(pointer)
        if not response["ok"]:
            raise CompilationError(response["error"])
        result = response["result"]
        if result["version"] != 1:
            raise RuntimeError("Unsupported compiled query protocol")
        return CompiledQuery(result["sql"], tuple(result["fields"]), result["dialect"])
