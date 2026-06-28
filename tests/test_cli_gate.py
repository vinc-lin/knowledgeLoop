import os
from repo_atlas import cli
from repo_atlas.adoption import NUDGE
from repo_atlas.eval.offline.retriever import StubRetriever


def test_gate_parser():
    args = cli.build_parser().parse_args(["gate", "--prompt", "add X", "--k", "7"])
    assert args.cmd == "gate" and args.prompt == "add X" and args.k == 7


def test_gate_skips_non_coding_prompt(capsys, monkeypatch):
    def _boom():
        raise AssertionError("retriever must not be built for a non-coding prompt")
    monkeypatch.setattr(cli, "_gate_retriever", _boom)
    rc = cli.main(["gate", "--prompt", "what does this function do?"])
    assert rc == 0 and capsys.readouterr().out == ""


def test_gate_fail_open_on_retriever_error(capsys, monkeypatch):
    def _boom():
        raise RuntimeError("no index / server down")
    monkeypatch.setattr(cli, "_gate_retriever", _boom)
    rc = cli.main(["gate", "--prompt", "implement a sepia filter"])
    assert rc == 0 and capsys.readouterr().out == ""


def test_gate_prints_nudge_when_out_of_tree(capsys, monkeypatch, tmp_path):
    (tmp_path / "local.cpp").write_text("x")
    monkeypatch.chdir(tmp_path)
    sr = StubRetriever(hits_by_query={"implement X using the existing helper":
                                      [{"name": "h", "file": "other/x.h", "text": ""}]})
    monkeypatch.setattr(cli, "_gate_retriever", lambda: sr)
    rc = cli.main(["gate", "--prompt", "implement X using the existing helper"])
    assert rc == 0 and capsys.readouterr().out == NUDGE


def test_gate_silent_when_in_tree(capsys, monkeypatch, tmp_path):
    (tmp_path / "local.cpp").write_text("x")
    monkeypatch.chdir(tmp_path)
    sr = StubRetriever(hits_by_query={"implement X using the existing helper":
                                      [{"name": "h", "file": "local.cpp", "text": ""}]})
    monkeypatch.setattr(cli, "_gate_retriever", lambda: sr)
    rc = cli.main(["gate", "--prompt", "implement X using the existing helper"])
    assert rc == 0 and capsys.readouterr().out == ""
