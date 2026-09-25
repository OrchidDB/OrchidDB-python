import os
import duckdb
import pyarrow as pa
import pytest
from orchiddb import Compiler, DuckDBEngine, Graph, CompilationError

@pytest.fixture
def graph():
    connection = duckdb.connect()
    connection.execute("CREATE TABLE people(id BIGINT, name VARCHAR)")
    connection.execute("INSERT INTO people VALUES (1, 'Ada'), (2, 'Grace'), (3, NULL)")
    connection.create_function("decorate", lambda s: s + "!", ["VARCHAR"], "VARCHAR")
    graph = Graph(Compiler(), DuckDBEngine(connection),
        tables=[{"name":"people","columns":[{"name":"id","data_type":"int64"},{"name":"name","data_type":"string"}]}],
        nodes=[{"label":"Person","table":"people","id":"id","properties":{"name":"name"}}],
        functions=[{"name":"decorate","target":"decorate","parameters":["string"],"returns":"string"}])
    yield graph
    connection.close()

def test_arrow_schema_batches_null_and_retained_batch(graph):
    with graph.query_arrow("MATCH (p:Person) RETURN p.name AS name ORDER BY p.id", batch_size=1) as reader:
        assert isinstance(reader, pa.RecordBatchReader)
        batches = list(reader)
        assert len(batches) == 3
        assert batches[0].column(0).to_pylist() == ["Ada"]
        assert batches[2].column(0).null_count == 1
    assert batches[0].column(0).to_pylist() == ["Ada"]

def test_parameter_udf_and_caller_transaction(graph):
    conn = graph.engine.connection
    conn.execute("BEGIN")
    conn.execute("INSERT INTO people VALUES (4, 'Linus')")
    with graph.query_arrow("MATCH (p:Person) WHERE p.name=$name RETURN decorate(p.name) AS name", parameters={"name":"Linus"}) as reader:
        assert reader.read_all().column(0).to_pylist() == ["Linus!"]
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT count(*) FROM people").fetchone() == (3,)

def test_gremlin_and_failure_cleanup(graph):
    with graph.query_arrow("g.V(1).values('name')", language="gremlin") as reader:
        assert reader.read_all().column(0).to_pylist() == ["Ada"]
        with pytest.raises(RuntimeError, match="already active"):
            with graph.query_arrow("RETURN 1"):
                pass
    with pytest.raises(CompilationError):
        graph.plan("MATCH (p:Person) DELETE p")
    with graph.query_arrow("RETURN 42 AS answer") as reader:
        assert reader.read_all().column(0).to_pylist() == [42]

def test_injection_is_literal(graph):
    with graph.query_arrow("MATCH (p:Person) WHERE p.name=$name RETURN p.name", parameters={"name":"Ada'; DROP TABLE people; --"}) as reader:
        assert reader.read_all().num_rows == 0
    assert graph.engine.connection.execute("SELECT count(*) FROM people").fetchone() == (3,)

def test_sparql_constant(graph):
    with graph.query_arrow("SELECT (42 AS ?answer) WHERE {}", language="sparql") as reader:
        assert reader.read_all().num_rows == 1

def test_consumer_exception_and_database_error_release_lease(graph):
    with pytest.raises(ZeroDivisionError):
        with graph.query_arrow("RETURN 1") as reader:
            reader.read_next_batch()
            1 / 0
    graph.engine.connection.execute("DROP TABLE people")
    with pytest.raises(duckdb.Error):
        with graph.query_arrow("MATCH (p:Person) RETURN p.name"):
            pass
    with graph.query_arrow("RETURN 42 AS answer") as reader:
        assert reader.read_all().column(0).to_pylist() == [42]
