import pytest

from peakrdl_check.canonical import (ADDR_HEX_WIDTH, Decl, addr_to_hex,
                                 canonical_json, content_hash, hex_to_addr)


def test_addr_roundtrip():
    for v in (0, 1, 0xFFFF_FFFF, 1 << 63, (1 << 96) + 12345):
        assert hex_to_addr(addr_to_hex(v)) == v


def test_addr_hex_is_order_preserving():
    values = [0, 5, 0x10, 1 << 32, (1 << 64) + 1, (1 << 90)]
    encoded = [addr_to_hex(v) for v in values]
    assert encoded == sorted(encoded)


def test_addr_beyond_128bit_rejected():
    with pytest.raises(ValueError):
        addr_to_hex(1 << (4 * ADDR_HEX_WIDTH))
    with pytest.raises(ValueError):
        addr_to_hex(-1)


def test_no_floats_anywhere_in_canonical_json():
    body = {"regwidth": 32, "reset": "ff", "addr": addr_to_hex(1 << 70)}
    assert "." not in canonical_json(body)


def test_content_hash_deterministic():
    a = {"fields": [{"name": "x", "lsb": 0}], "desc": "d"}
    b = {"desc": "d", "fields": [{"lsb": 0, "name": "x"}]}
    assert content_hash(a) == content_hash(b)  # key order irrelevant
    assert content_hash(a) != content_hash({**a, "desc": "e"})


def test_decl_element_addressing():
    d = Decl(decl_id=1, parent_id=None, kind="reg", name="r", path="r",
             def_hash="h", addr=0x1000, offset=0, size=4,
             array_dims=[8], array_stride=0x10)
    assert d.total_elements == 8
    assert d.element_addr(0) == 0x1000
    assert d.element_addr(7) == 0x1000 + 7 * 0x10
    assert d.addr_span_end == 0x1000 + 7 * 0x10 + 3
    with pytest.raises(IndexError):
        d.element_addr(8)


def test_scalar_decl_addressing():
    d = Decl(decl_id=1, parent_id=None, kind="reg", name="r", path="r",
             def_hash="h", addr=0x20, offset=0x20, size=4)
    assert d.total_elements == 1
    assert d.addr_span_end == 0x23
    with pytest.raises(IndexError):
        d.element_addr(1)


def test_bit_range_precision_beyond_64_bits(compile_model):
    model = compile_model("""
addrmap wide {
    reg {
        regwidth = 128;
        field { sw = rw; hw = r; reset = 0x1; } lo[63:0];
        field { sw = rw; hw = r; reset = 0x2; } hi[127:64];
    } big @ 0x0;
};
""")
    body = next(iter(model.definitions.values())).body
    hi = [f for f in body["fields"] if f["name"] == "hi"][0]
    assert hi["msb"] == 127 and hi["lsb"] == 64
