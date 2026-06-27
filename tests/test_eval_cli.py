from repo_atlas import cli


def test_eval_parser():
    args = cli.build_parser().parse_args(["eval", "--tasks", "/t", "--out", "/o.md"])
    assert args.cmd == "eval" and args.tasks == "/t" and args.out == "/o.md"


def test_eval_arms_parser():
    args = cli.build_parser().parse_args(
        ["eval-arms", "--tasks", "/t", "--arms", "control,forced-inject", "--proxy-k", "8"])
    assert args.cmd == "eval-arms"
    assert args.tasks == "/t"
    assert args.arms == "control,forced-inject"
    assert args.proxy_k == 8
    assert args.timeout == 900                  # default per-run timeout


def test_eval_arms_parser_timeout_override():
    args = cli.build_parser().parse_args(["eval-arms", "--tasks", "/t", "--timeout", "300"])
    assert args.timeout == 300
