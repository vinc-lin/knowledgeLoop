from dataclasses import dataclass, field
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.config import Config


@dataclass
class ToolDiagnostics:
    """Per-module tool-call instrumentation (Stage 1) to trace non-converging agent loops.

    Distinguishes the candidate causes of the request-budget-exhausting pre-write
    loops: repeated non-core reads (read_code_components count + read-id reuse),
    mermaid-fix cycles (str_replace count), and create attempts.
    """
    counts: dict = field(default_factory=dict)
    _seen_read_ids: set = field(default_factory=set)
    repeat_read_ids: int = 0
    total_read_ids: int = 0

    def record_read(self, component_ids):
        self.counts["read_code_components"] = self.counts.get("read_code_components", 0) + 1
        for cid in component_ids or []:
            self.total_read_ids += 1
            if cid in self._seen_read_ids:
                self.repeat_read_ids += 1
            else:
                self._seen_read_ids.add(cid)

    def record_edit(self, command: str):
        key = f"editor:{command}"
        self.counts[key] = self.counts.get(key, 0) + 1

    def summary(self) -> str:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items())) or "none"
        return f"tool calls [{parts}]; read-id reuse {self.repeat_read_ids}/{self.total_read_ids}"


@dataclass
class CodeWikiDeps:
    absolute_docs_path: str
    absolute_repo_path: str
    registry: dict
    components: dict[str, Node]
    path_to_current_module: list[str]
    current_module_name: str
    module_tree: dict[str, any]
    max_depth: int
    current_depth: int
    config: Config  # LLM configuration
    custom_instructions: str = None
    # Stage 1 diagnostics: per-module tool-call instrumentation (shared down into sub-agents).
    diagnostics: ToolDiagnostics = field(default_factory=ToolDiagnostics)