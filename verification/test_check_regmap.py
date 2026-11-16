from verification import check_regmap

HEAD = "| Offset | Name | Access | Gate | Ports |\n|---|---|---|---|---|\n"
TAIL = "\nEvery word address not in the table ({}) is undefined.\n"
UNMAPPED_OK = "0x03-0x0F, 0x14-0x7F"
ROWS_OK = (
    "| 0x00 | STATUS | RO | - | `busy` |\n"
    "| 0x01 | CTRL | WO | AES | `start` |\n"
    "| 0x02 | DIN | WO | AES | `block_in` |\n"
    "| 0x10-0x13 | DOUT[0..3] | RO | - | `block_out` |\n"
)


def _run(tmp_path, rows=ROWS_OK, unmapped=UNMAPPED_OK):
    p = tmp_path / "rec.md"
    p.write_text(HEAD + rows + TAIL.format(unmapped))
    return check_regmap.check(p)


def test_consistent_table_passes(tmp_path):
    assert _run(tmp_path) == []


def test_overlap_is_reported(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x12 | CLASH | RO | - | `busy` |\n")
    assert any("overlaps" in e for e in errs)


def test_bad_access_and_gate(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x08 | X | RX | FOO | `busy` |\n")
    assert any("access" in e for e in errs) and any("gate" in e for e in errs)


def test_readable_key_port_is_rejected(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x08 | LEAK | RO | - | `aes_key` |\n")
    assert any("readable register wired" in e for e in errs)


BIT_RANGE_SHAPES = ("`aes_key[127:0]`", "`aes_key[63:0]`", "`aes_key[0]`",
                    "`aes_key [127:0]`")


def test_readable_bit_ranged_key_port_is_rejected(tmp_path):
    for spelling in BIT_RANGE_SHAPES:
        errs = _run(tmp_path, ROWS_OK + f"| 0x08 | LEAK | RO | - | {spelling} |\n")
        assert any("readable register wired" in e for e in errs), spelling


def test_bit_ranged_error_names_the_raw_token(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x08 | LEAK | RO | - | `aes_key[127:0]` |\n")
    assert any("aes_key[127:0]" in e for e in errs)


def test_every_key_port_bit_ranged_is_rejected(tmp_path):
    for port, rng in (("hmac_key", "[255:0]"), ("root_key", "[127:0]"),
                      ("ld_data", "[31:0]"), ("seed", "[383:0]")):
        errs = _run(tmp_path, ROWS_OK + f"| 0x08 | LEAK | RO | - | `{port}{rng}` |\n")
        assert any("readable register wired" in e for e in errs), port


def test_write_only_may_use_bit_ranged_key_port(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x08 | LOAD | WO | KDF | `ld_data[31:0]` |\n",
                "0x03-0x07, 0x09-0x0F, 0x14-0x7F")
    assert errs == []


def test_readable_status_flag_names_are_not_key_ports(tmp_path):
    flags = ("`root_key_valid`", "`seeded`", "`slot_valid`", "`slot_locked`",
             "`root_key_valid[3:0]`")
    rows = "".join(f"| 0x{i:02X} | FLAG{i} | RO | - | {f} |\n"
                   for i, f in zip(range(0x70, 0x75), flags))
    errs = _run(tmp_path, ROWS_OK + rows, "0x03-0x0F, 0x14-0x6F, 0x75-0x7F")
    assert errs == []


def test_write_only_may_use_key_port(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x08 | LOAD | WO | KDF | `ld_data` |\n",
                "0x03-0x07, 0x09-0x0F, 0x14-0x7F")
    assert errs == []


def test_array_bounds_must_match(tmp_path):
    errs = _run(tmp_path, ROWS_OK.replace("DOUT[0..3]", "DOUT[0..2]"))
    assert any("array bounds" in e for e in errs)


def test_out_of_space_and_duplicate_name(tmp_path):
    errs = _run(tmp_path, ROWS_OK + "| 0x80 | STATUS | RO | - | `busy` |\n")
    assert any("outside" in e for e in errs) and any("duplicate" in e for e in errs)


def test_stated_unmapped_list_must_match(tmp_path):
    assert any("stated undefined" in e for e in _run(tmp_path, unmapped="0x03-0x0F"))


def test_real_record_is_consistent():
    assert check_regmap.check(check_regmap.DEFAULT_DOC) == []
