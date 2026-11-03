from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from logisim_mcp.config import SETTINGS
from logisim_mcp.tools.builder_tools import add_component, add_gate, add_pin, connect
from logisim_mcp.tools.describe_tools import check_circuit_drc
from logisim_mcp.tools.io_tools import create_circuit_file
from logisim_mcp.tools.sim_tools import (
    _count_testbenches,
    _parse_test_vector_output,
    count_components,
    format_truth_table,
    run_test_circuit,
    run_test_vector,
    simulate_sequential,
    vector_succeeded,
    verify_truth_table,
)


requires_logisim = pytest.mark.skipif(
    not SETTINGS.logisim_jar.exists(),
    reason="Logisim JAR not installed",
)


def test_vector_success_requires_rows_that_actually_ran() -> None:
    silent = {"passed": 0, "failed": 0, "reported": False}
    assert vector_succeeded(silent, "", "Circuit 'nosuch' not found.", True) is False
    assert vector_succeeded(silent, "", "Error loading test vector: bad bit", True) is False
    ran = {"passed": 4, "failed": 0, "reported": True}
    assert vector_succeeded(ran, "Passed: 4, Failed: 0\n", "", True) is True
    zero = {"passed": 0, "failed": 0, "reported": True}
    assert vector_succeeded(zero, "Passed: 0, Failed: 0\n", "", True) is False


def _bench_project(tmp_path: Path, bench: bool) -> Path:
    p = tmp_path / "lab.circ"
    create_circuit_file(str(p))
    if bench:
        # What Logisim Evolution's --test-circuit flow actually saves: a
        # dedicated circuit named logisim_test_verif (driven through its
        # test_bench_done_o / test_bench_ok_o output pins).
        bench_circuit = (
            '  <circuit name="logisim_test_verif">\n'
            '    <a name="circuit" val="logisim_test_verif"/>\n'
            '    <comp lib="0" loc="(100,100)" name="Pin">\n'
            '      <a name="facing" val="west"/>\n'
            '      <a name="output" val="true"/>\n'
            '      <a name="label" val="test_bench_ok_o"/>\n'
            "    </comp>\n"
            "  </circuit>\n"
        )
        text = p.read_text()
        p.write_text(text.replace("</project>", bench_circuit + "</project>"))
    return p


def test_run_test_circuit_refuses_projects_without_a_testbench(tmp_path: Path) -> None:
    p = _bench_project(tmp_path, bench=False)
    # The guard must fire before any java invocation, so this passes on
    # machines with no Logisim JAR at all.
    with pytest.raises(ValueError) as excinfo:
        run_test_circuit(str(p))
    msg = str(excinfo.value)
    assert "simulate_tty" in msg and "verify_truth_table" in msg
    assert "logisim_test_verif" in msg


@pytest.mark.parametrize(
    ("exit_code", "timed_out"),
    [(0, False), (100, False), (0, True)],
)
def test_run_test_circuit_reports_reason_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int, timed_out: bool
) -> None:
    from logisim_mcp.runner.java import JavaResult

    p = _bench_project(tmp_path, bench=True)
    captured: dict[str, Any] = {}

    def fake_run_java(args: list[str], timeout: int | None = None):
        captured["args"] = args
        return JavaResult(
            args=args,
            exit_code=exit_code,
            stdout="" if exit_code != 0 else "bench output",
            stderr="",
            timed_out=timed_out,
        )

    monkeypatch.setattr(
        "logisim_mcp.tools.sim_tools.run_java", fake_run_java
    )
    res = run_test_circuit(str(p))
    assert captured["args"] == ["--test-circuit", str(p)]
    assert res["testbenches"] >= 1
    assert res["stderr"] == ""
    assert res["stdout"] == ("bench output" if exit_code == 0 else "")
    if timed_out:
        assert res["ok"] is False
        assert "timed out" in res["reason"]
    elif exit_code == 0:
        assert res["ok"] is True
        assert "signalled OK" in res["reason"]
    else:
        assert res["ok"] is False
        assert "(exit 100)" in res["reason"]
        # exit 100 with nothing on either stream — the suffix removes the
        # guesswork that the CLI was given nothing to say
        assert "no console output captured" in res["reason"]


def test_count_testbenches_finds_saved_benches(tmp_path: Path) -> None:
    from logisim_mcp.circ.parser import parse

    bench = _bench_project(tmp_path, bench=True)
    assert _count_testbenches(parse(bench)) == 1
    plain = _bench_project(tmp_path, bench=False)
    assert _count_testbenches(parse(plain)) == 0


def test_empty_sequential_rows_do_not_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logisim_mcp.runner.java import JavaResult

    monkeypatch.setattr(
        "logisim_mcp.tools.sim_tools.run_seq_tester",
        lambda *_args, **_kwargs: JavaResult([], 0, "PASSED=0\nFAILED=0\n", ""),
    )
    result = simulate_sequential(
        str(tmp_path / "unused.circ"), "main", ["A"], ["Y"], []
    )
    assert result["ok"] is False


def test_count_components_keeps_a_component_named_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from logisim_mcp.runner.java import JavaResult

    stdout = (
        "1\t1\tTotalAdder\tlab\n"
        "4\t4\tTOTAL (without project’s sub circuits)\n"
        "4\t4\tTOTAL (with sub circuits)\n"
    )
    monkeypatch.setattr(
        "logisim_mcp.tools.sim_tools.run_java",
        lambda *_args, **_kwargs: JavaResult([], 0, stdout, ""),
    )
    result = count_components("unused.circ")
    assert result["components"]["TotalAdder"] == 1
    assert result["total"] == 4


def test_format_truth_table_appends_sequential_columns() -> None:
    text = format_truth_table(
        ["Clk", "D"],
        ["Q"],
        [["0", "1", "0"], ["1", "1", "1"]],
        sets=[1, 1],
        steps=[1, 2],
    )
    assert text.splitlines()[0] == "Clk D Q <set> <seq>"
    assert text.splitlines()[1:] == ["0 1 0 1 1", "1 1 1 1 2"]


def test_parse_vector_summary() -> None:
    text = (
        'Loading test vector "x".\n'
        "Running 4 vectors…\n"
        "1 \nError on test vector 1:\n  Sum = E (expected 0)\n"
        "2 3 4 \nPassed: 1, Failed: 3\n"
    )
    res = _parse_test_vector_output(text)
    assert res["passed"] == 1
    assert res["failed"] == 3
    assert res["failures"][0]["row"] == 1
    assert res["failures"][0]["details"][0]["signal"] == "Sum"
    assert res["failures"][0]["details"][0]["actual"] == "E"
    assert res["failures"][0]["details"][0]["expected"] == "0"


@requires_logisim
def test_run_test_vector_and_truth_table_against_fixture(fixtures_dir: Path) -> None:
    circ = fixtures_dir / "and_gate.circ"
    vec = fixtures_dir / "and_gate.vec"

    direct = run_test_vector(str(circ), "main", str(vec))
    assert direct["ok"] is True
    assert direct["passed"] == 4
    assert direct["failed"] == 0

    table = verify_truth_table(
        str(circ),
        "main",
        inputs=["A", "B"],
        outputs=["Y"],
        rows=[
            ["0", "0", "0"],
            ["0", "1", "0"],
            ["1", "0", "0"],
            ["1", "1", "1"],
        ],
    )
    assert table["ok"] is True
    assert table["passed"] == 4


@requires_logisim
def test_headless_sequential_reads_pins_and_leds(tmp_path: Path) -> None:
    path = tmp_path / "not.circ"
    create_circuit_file(str(path))
    src = add_pin(str(path), "main", "A", is_output=False, x=100, y=100)
    gate = add_gate(str(path), "main", "NOT", x=180, y=100)
    led = add_component(str(path), "main", "LED", attrs={"label": "L"}, x=260, y=100)
    connect(str(path), "main", src["id"], "tip", gate["id"], "in0")
    connect(str(path), "main", gate["id"], "out", led["id"], "in")
    result = simulate_sequential(
        str(path),
        "main",
        inputs=["A"],
        outputs=["L"],
        rows=[["0", "1"], ["1", "0"]],
    )
    assert result["ok"], result
    report = check_circuit_drc(str(path), probe_errors=True)
    assert report["error_wires"] == 0
    assert report["shorted_nets"] == []


@requires_logisim
def test_error_wires_count_a_short(tmp_path: Path) -> None:
    path = tmp_path / "short.circ"
    create_circuit_file(str(path))
    pin = add_pin(str(path), "main", "A", is_output=False, x=100, y=100)
    const = add_component(
        str(path), "main", "Constant", attrs={"value": "0x1"}, x=100, y=160
    )
    connect(str(path), "main", pin["id"], "tip", const["id"], "tip")
    report = check_circuit_drc(str(path), probe_errors=True)
    assert report["shorted_nets"]
    assert report["error_wires"] >= 1


@requires_logisim
def test_headless_sequential_ticks_a_clock(tmp_path: Path) -> None:
    path = tmp_path / "dff.circ"
    create_circuit_file(str(path))
    ff = add_component(str(path), "main", "D Flip-Flop", x=300, y=200)
    data = add_pin(str(path), "main", "D", is_output=False, x=200, y=210)
    q = add_pin(str(path), "main", "Q", is_output=True, x=450, y=210)
    clock = add_component(str(path), "main", "Clock", x=180, y=250)
    preset = add_component(
        str(path), "main", "Constant", attrs={"value": "0x0"}, x=320, y=140
    )
    clear = add_component(
        str(path), "main", "Constant", attrs={"value": "0x0"}, x=320, y=320
    )
    connect(str(path), "main", data["id"], "tip", ff["id"], "D")
    connect(str(path), "main", clock["id"], "out", ff["id"], "CLK")
    connect(str(path), "main", preset["id"], "tip", ff["id"], "S")
    connect(str(path), "main", clear["id"], "tip", ff["id"], "R")
    connect(str(path), "main", ff["id"], "Q", q["id"], "tip")
    result = simulate_sequential(
        str(path),
        "main",
        inputs=["D", "<tick>"],
        outputs=["Q"],
        rows=[["1", "1", "1"], ["0", "1", "0"]],
    )
    assert result["ok"], result


@requires_logisim
def test_headless_sequential_honours_clock_durations(tmp_path: Path) -> None:
    path = tmp_path / "dff_slow_clock.circ"
    create_circuit_file(str(path))
    ff = add_component(str(path), "main", "D Flip-Flop", x=300, y=200)
    data = add_pin(str(path), "main", "D", is_output=False, x=200, y=210)
    q = add_pin(str(path), "main", "Q", is_output=True, x=450, y=210)
    clock = add_component(
        str(path),
        "main",
        "Clock",
        attrs={"highDuration": "3", "lowDuration": "3"},
        x=180,
        y=250,
    )
    preset = add_component(
        str(path), "main", "Constant", attrs={"value": "0x0"}, x=320, y=140
    )
    clear = add_component(
        str(path), "main", "Constant", attrs={"value": "0x0"}, x=320, y=320
    )
    connect(str(path), "main", data["id"], "tip", ff["id"], "D")
    connect(str(path), "main", clock["id"], "out", ff["id"], "CLK")
    connect(str(path), "main", preset["id"], "tip", ff["id"], "S")
    connect(str(path), "main", clear["id"], "tip", ff["id"], "R")
    connect(str(path), "main", ff["id"], "Q", q["id"], "tip")
    result = simulate_sequential(
        str(path),
        "main",
        inputs=["D", "<tick>"],
        outputs=["Q"],
        rows=[["1", "1", "1"], ["0", "1", "0"], ["1", "1", "1"]],
    )
    assert result["ok"], result
    negative = simulate_sequential(
        str(path),
        "main",
        inputs=["D", "<tick>"],
        outputs=["Q"],
        rows=[["1", "-1", "1"]],
    )
    assert negative["ok"] is False
    assert "negative" in negative["stderr"]


@requires_logisim
def test_sequential_accepts_hex_and_rejects_a_bad_output(tmp_path: Path) -> None:
    path = tmp_path / "buf.circ"
    create_circuit_file(str(path))
    src = add_pin(str(path), "main", "A", is_output=False, x=100, y=100)
    dst = add_pin(str(path), "main", "Y", is_output=True, x=200, y=100)
    connect(str(path), "main", src["id"], "tip", dst["id"], "tip")
    hexed = simulate_sequential(
        str(path),
        "main",
        inputs=["A"],
        outputs=["Y"],
        rows=[["0x1", "1"], ["0b0", "x"]],
    )
    assert hexed["ok"], hexed
    wide = simulate_sequential(
        str(path),
        "main",
        inputs=["A"],
        outputs=["Y"],
        rows=[["2", "0"]],
    )
    assert wide["ok"] is False
    assert "does not fit" in wide["stderr"]
    extra = simulate_sequential(
        str(path),
        "main",
        inputs=["A"],
        outputs=["Y"],
        rows=[["0", "0", "surplus"]],
    )
    assert extra["ok"] is False
    assert "values" in extra["stderr"]
    echoed = simulate_sequential(
        str(path),
        "main",
        inputs=["A"],
        outputs=["A"],
        rows=[["1", "1"]],
    )
    assert echoed["ok"] is False
    assert "input pin" in echoed["stderr"]


@requires_logisim
def test_sequential_accepts_full_width_unsigned_values(tmp_path: Path) -> None:
    cases = [
        (63, ["0x7fffffffffffffff"]),
        (64, ["0x7fffffffffffffff", "0x8000000000000000", "0xffffffffffffffff"]),
    ]
    for width, values in cases:
        path = tmp_path / f"wide{width}.circ"
        create_circuit_file(str(path))
        src = add_pin(
            str(path), "main", "A", is_output=False, bit_width=width, x=100, y=100
        )
        dst = add_pin(
            str(path), "main", "Y", is_output=True, bit_width=width, x=300, y=100
        )
        connect(str(path), "main", src["id"], "tip", dst["id"], "tip")
        result = simulate_sequential(
            str(path),
            "main",
            inputs=["A"],
            outputs=["Y"],
            rows=[[value, value] for value in values],
        )
        assert result["ok"], result


@requires_logisim
def test_verify_does_not_pass_when_nothing_ran(tmp_path: Path) -> None:
    path = tmp_path / "empty.circ"
    create_circuit_file(str(path))
    missing = verify_truth_table(str(path), "nosuch", ["A"], ["Y"], [["0", "0"]])
    assert missing["ok"] is False
    add_pin(str(path), "main", "A", is_output=False, x=80, y=80)
    add_pin(str(path), "main", "Y", is_output=True, x=180, y=80)
    malformed = verify_truth_table(str(path), "main", ["A"], ["Y"], [["2", "0"]])
    assert malformed["ok"] is False
