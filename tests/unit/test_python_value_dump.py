"""The helper debugpy runs in the program to copy a whole Python value."""

from dataclasses import dataclass

from debugpilot.debugger.python import VALUE_DUMP


def dump(value):
    namespace = {}
    exec(VALUE_DUMP, namespace)
    return namespace['dump'](value)


class Address:
    def __init__(self):
        self.city = 'Lima'


class Customer:
    def __init__(self):
        self.name = 'Ana'
        self.address = Address()


class Shown:
    def __repr__(self):
        return 'Shown!'


@dataclass
class Item:
    sku: str


class Lazy:
    def __init__(self):
        self.ready = True

    @property
    def boom(self):
        raise AssertionError('a property ran')


def test_plain_objects_show_their_attributes_and_containers_go_deep():
    value = {'customer': Customer(), 'items': [{'sku': 'book'}], 'pair': (1,), 'tags': {'a'}}
    assert dump(value) == ("{'customer': Customer(name='Ana', address=Address(city='Lima')), "
                           "'items': [{'sku': 'book'}], 'pair': (1,), 'tags': {'a'}}")


def test_an_own_repr_is_kept_and_properties_never_run():
    assert dump([Shown(), Item('pen'), Lazy()]) == "[Shown!, Item(sku='pen'), Lazy(ready=True)]"


def test_cycles_and_deep_nesting_stop():
    loop = []
    loop.append(loop)
    assert dump(loop) == '[...]'
    deep = [[[[[[[[[[1]]]]]]]]]]
    assert dump(deep) == '[' * 9 + '...' + ']' * 9
