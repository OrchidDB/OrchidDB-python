from contextlib import contextmanager
from threading import Lock
from typing import Protocol, ContextManager, Any
from .compiler import Compiler, CompiledQuery

class ArrowEngine(Protocol):
    dialect: str
    def query_arrow(self, query: CompiledQuery, batch_size: int = 65536) -> ContextManager[Any]:
        """Yield an Arrow RecordBatchReader; release only resources owned by the query."""
        ...

class DuckDBEngine:
    """Borrows the exact caller connection; never commits, rolls back, or closes it.

    Do not use the connection directly while this adapter has an open result.
    The lock prevents overlapping results through this adapter only.
    """
    dialect = "duckdb"
    def __init__(self, connection):
        self.connection = connection
        self._lease = Lock()

    @contextmanager
    def query_arrow(self, query: CompiledQuery, batch_size: int = 65536):
        if query.dialect != self.dialect:
            raise ValueError("Compiled query dialect does not match engine")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if not self._lease.acquire(blocking=False):
            raise RuntimeError("An Arrow reader is already active on this engine")
        reader = None
        try:
            # execute uses the original connection, preserving transactions and UDFs.
            reader = self.connection.execute(query.sql).to_arrow_reader(batch_size)
            yield reader
        finally:
            try:
                if reader is not None:
                    reader.close()
            finally:
                self._lease.release()

class Graph:
    def __init__(self, compiler: Compiler, engine: ArrowEngine, *, tables, nodes, edges=(), functions=(), ontology=None):
        import copy
        self.compiler, self.engine = compiler, engine
        self.metadata = copy.deepcopy(dict(tables=tables, nodes=nodes, edges=list(edges), functions=list(functions), ontology=ontology or {}))

    def plan(self, query: str, *, language="cypher", parameters=None):
        return self.compiler.compile(dict(self.metadata, version=1, dialect=self.engine.dialect, language=language, query=query, parameters=parameters or {}))

    def query_arrow(self, query: str, *, language="cypher", parameters=None, batch_size=65536):
        return self.engine.query_arrow(self.plan(query, language=language, parameters=parameters), batch_size)
