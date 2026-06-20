from repo_atlas import cli


def test_eval_parser():
    args = cli.build_parser().parse_args(["eval", "--tasks", "/t", "--out", "/o.md"])
    assert args.cmd == "eval" and args.tasks == "/t" and args.out == "/o.md"
