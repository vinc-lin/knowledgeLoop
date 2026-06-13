import logging

from pydantic_ai import RunContext, Tool
from codewiki.src.be.agent_tools.deps import CodeWikiDeps

logger = logging.getLogger(__name__)


async def read_code_components(ctx: RunContext[CodeWikiDeps], component_ids: list[str]) -> str:
    """Read the code of a given component id

    Args:
        component_ids: The ids of the components to read, e.g. ["sweagent/types.py::AgentRunResult", "auth/middleware.py::verify_token"] where the part before :: is the file path and the part after :: is the component name
    """

    diagnostics = getattr(ctx.deps, "diagnostics", None)
    if diagnostics is not None:
        diagnostics.record_read(component_ids)
        logger.debug(
            "read_code_components(%s) for module %s [%d ids, %d reused]",
            len(component_ids or []), ctx.deps.current_module_name,
            diagnostics.total_read_ids, diagnostics.repeat_read_ids,
        )

    results = []

    for component_id in component_ids:
        if component_id not in ctx.deps.components:
            results.append(f"# Component {component_id} not found")
        else:
            results.append(f"# Component {component_id}:\n{ctx.deps.components[component_id].source_code.strip()}\n\n")

    return "\n".join(results)

read_code_components_tool = Tool(function=read_code_components, name="read_code_components", description="Read the code of a given list of component ids", takes_ctx=True)