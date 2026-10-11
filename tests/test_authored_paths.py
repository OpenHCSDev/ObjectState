from dataclasses import dataclass, field

from objectstate import LazyDataclassFactory, retain_only_authored_paths


@dataclass
class InnerAuthored:
    depth: int = 1
    width: int = 2


@dataclass
class OuterAuthored:
    name: str = "a"
    inner: InnerAuthored = field(default_factory=InnerAuthored)


def test_retain_only_authored_paths_keeps_values_and_marks_only_authored_fields():
    lazy_inner = LazyDataclassFactory.make_lazy_simple(InnerAuthored)
    lazy_outer = LazyDataclassFactory.make_lazy_simple(OuterAuthored)
    rebuilt = lazy_outer(name="b", inner=lazy_inner(depth=5, width=None))

    projected = retain_only_authored_paths(rebuilt, {"inner.depth"})

    assert object.__getattribute__(projected, "name") == "b"
    assert object.__getattribute__(projected.inner, "depth") == 5
    assert object.__getattribute__(projected.inner, "width") is None
    assert projected._explicitly_set_fields == {"inner"}
    assert projected.inner._explicitly_set_fields == {"depth"}
