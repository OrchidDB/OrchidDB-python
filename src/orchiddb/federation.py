"""Execute SQL islands with query-scoped data; no database objects are created."""
from contextlib import contextmanager
from .compiler import CompiledQuery

@contextmanager
def query_federated(compiler, request, engines, batch_size=65536):
    plan = compiler.compile(request)
    target_id = plan.diagnostics.get("execution_engine")
    if target_id is None:
        raise ValueError("Federated execution requires execution_engine")
    transfers = plan.diagnostics.get("transfers", [])
    routes = [(target_id, plan.dialect)] + [(t["source_engine"], t["source_dialect"]) for t in transfers]
    for name, dialect in routes:
        if name not in engines or engines[name].dialect != dialect:
            raise ValueError(f"Missing engine or dialect mismatch: {name}")
    for transfer in transfers:
        source = CompiledQuery(transfer["sql"], tuple(c["name"] for c in transfer["columns"]), transfer["source_dialect"], diagnostics={"field_types": [c["data_type"] for c in transfer["columns"]]})
        with engines[transfer["source_engine"]].query_arrow(source, batch_size) as reader:
            plan = compiler.bind_arrow(plan, transfer["target_relation"], reader)
    with engines[target_id].query_arrow(plan, batch_size) as result:
        yield result
