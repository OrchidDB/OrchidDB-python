# OrchidDB for Python

Compile Cypher, Gremlin and SPARQL to SQL, execute through a caller-owned engine,
and consume Arrow batches. No DuckDB driver is bundled or imported by the library.
The compiler does not touch your data. Graph mapping and schema metadata are explicit.

```sh
python -m pip install -e '.[test]'
export ORCHIDDB_NATIVE_LIBRARY=/absolute/path/liborchiddb_compiler.dylib
python examples/people.py
pytest
```

Build the matching native compiler from [OrchidDB-native](https://github.com/OrchidDB/OrchidDB-native)
using `NATIVE_REVISION` and its pinned `CORE_REVISION`. Release wheels bundle this
compiler for their platform; source installs require the explicit library path.
No network downloads happen at import time. ABI and core revision are validated. An explicit development library may report
the pinned revision with a `-dirty` suffix; bundled release libraries require an exact match.

```python
from orchiddb import Compiler, DuckDBEngine, Graph
# connection is your existing DuckDB connection; see examples/people.py for mapping.
graph = Graph(Compiler(), DuckDBEngine(connection), tables=tables, nodes=nodes)
with graph.query_arrow("MATCH (p:Person) WHERE p.name=$name RETURN p.name AS name",
                       parameters={"name": "Ada"}, batch_size=65536) as reader:
    print(reader.schema)
    for batch in reader:
        consume(batch)  # pyarrow.RecordBatch; no row or JSON conversion
```

The reader closes on context exit, including exceptions. Retained PyArrow batches
own their buffers. The adapter never closes the borrowed connection, commits,
rolls back, configures extensions, or installs UDFs. Do not reuse that connection
until the reader is closed. Overlapping readers through the same adapter fail.
Register UDFs yourself and pass their compiler signatures via `functions`.

`graph.plan(query)` returns SQL without executing it. `Compiler.compile(request)`
accepts the shared v1 JSON-shaped request; use `language="gremlin"` or `"sparql"`
with `Graph` for those languages. SQL support is deliberately narrower than the
managed engine's conformance suite. Parameters are specialized into SQL; recompile
when values or metadata change. Unsupported queries raise `CompilationError`.

Implement the `ArrowEngine` protocol for another backend: provide `dialect` and a
context manager yielding a `pyarrow.RecordBatchReader`. PostgreSQL SQL rendering
is supported by core; cross-engine federation is not implemented. Caller controls
connections, Arrow allocation, caches and transaction boundaries.

## Releases

CI builds pinned native code and runs real Arrow/DuckDB tests. The manual release
workflow requires a matching `v0.1.0` tag, builds platform wheels, and publishes to
PyPI via trusted publishing. Configure PyPI's `orchiddb` trusted publisher for this
repository, workflow `release.yml`, environment `pypi`. The package name was
unregistered when checked; this does not reserve it. No release is published until
maintainers configure the registry and dispatch the workflow.

Licensed under [the OrchidDB GPL-3.0-only license](LICENSE.md).

DuckDB Arrow export follows its [Python Arrow API](https://duckdb.org/docs/current/guides/python/export_arrow).
Arrow batching does not itself guarantee that an engine streams query execution;
execution buffering and cancellation remain backend-specific.
