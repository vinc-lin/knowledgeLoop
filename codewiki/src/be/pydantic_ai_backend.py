"""PydanticAIBackend — the existing API-key based path.

This backend is a thin adapter over :func:`call_llm` and the pydantic-ai
``Agent`` machinery.  Behaviour is preserved exactly; this file only
repackages it behind the :class:`LLMBackend` interface so the rest of
CodeWiki can be backend-agnostic.
"""

from __future__ import annotations

import logging
import os
import traceback
from typing import Any, Dict, List

from pydantic_ai import Agent
from pydantic_ai.exceptions import IncompleteToolCall

from codewiki.src.be.agent_tools.deps import CodeWikiDeps
from codewiki.src.be.agent_tools.generate_sub_module_documentations import (
    generate_sub_module_documentation_tool,
)
from codewiki.src.be.agent_tools.read_code_components import read_code_components_tool
from codewiki.src.be.agent_tools.str_replace_editor import str_replace_editor_tool
from codewiki.src.be.backend import LLMBackend
from codewiki.src.be.dependency_analyzer.models.core import Node
from codewiki.src.be.llm_services import build_usage_limits, call_llm, create_fallback_models
from codewiki.src.be.prompt_template import (
    format_leaf_system_prompt,
    format_system_prompt,
    format_user_prompt,
)
from codewiki.src.be.utils import is_complex_module
from codewiki.src.config import MODULE_TREE_FILENAME, OVERVIEW_FILENAME, Config
from codewiki.src.utils import file_manager

logger = logging.getLogger(__name__)


class PydanticAIBackend(LLMBackend):
    """API-key based backend using pydantic-ai + openai/litellm clients."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._fallback_models = create_fallback_models(config)
        self._custom_instructions = config.get_prompt_addition()

    def complete(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        return call_llm(prompt, self._config, model=model, temperature=temperature)

    @staticmethod
    def _should_escalate(exc: BaseException, *, doc_exists: bool,
                         decompose_on_overflow: bool, already_complex: bool,
                         escalated: bool) -> bool:
        """A leaf agent overflowed the output cap mid-write and we may retry as decompose."""
        return (
            isinstance(exc, IncompleteToolCall)
            and not doc_exists
            and decompose_on_overflow
            and not already_complex
            and not escalated
        )

    @staticmethod
    def _tools_for(complex_: bool) -> list:
        """Toolset for a module agent. Complex modules also get the decomposition tool."""
        base = [read_code_components_tool, str_replace_editor_tool]
        if complex_:
            return base + [generate_sub_module_documentation_tool]
        return base

    def _build_agent(self, module_name: str, *, complex_: bool) -> Agent:
        """Build the leaf or complex documentation agent for a module."""
        system_prompt = (
            format_system_prompt(module_name, self._custom_instructions)
            if complex_
            else format_leaf_system_prompt(module_name, self._custom_instructions)
        )
        return Agent(
            self._fallback_models,
            name=module_name,
            deps_type=CodeWikiDeps,
            tools=self._tools_for(complex_),
            system_prompt=system_prompt,
        )

    async def run_module_agent(
        self,
        module_name: str,
        components: Dict[str, Node],
        core_component_ids: List[str],
        module_path: List[str],
        working_dir: str,
        module_tree_path: str = None,
    ) -> Dict[str, Any]:
        config = self._config
        module_tree_path = module_tree_path or os.path.join(working_dir, MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)

        overview_docs_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_docs_path):
            logger.info("✓ Overview docs already exists at %s", overview_docs_path)
            return module_tree
        docs_path = os.path.join(working_dir, f"{module_name}.md")
        if os.path.exists(docs_path):
            logger.info("✓ Module docs already exists at %s", docs_path)
            return module_tree

        complex_ = is_complex_module(components, core_component_ids)
        agent = self._build_agent(module_name, complex_=complex_)

        deps = CodeWikiDeps(
            absolute_docs_path=working_dir,
            absolute_repo_path=str(os.path.abspath(config.repo_path)),
            registry={},
            components=components,
            path_to_current_module=module_path,
            current_module_name=module_name,
            module_tree=module_tree,
            max_depth=config.max_depth,
            current_depth=1,
            config=config,
            custom_instructions=self._custom_instructions,
        )

        try:
            await agent.run(
                format_user_prompt(
                    module_name=module_name,
                    core_component_ids=core_component_ids,
                    components=components,
                    module_tree=deps.module_tree,
                ),
                deps=deps,
                usage_limits=build_usage_limits(config),
            )
            logger.info("module %s diagnostics: %s", module_name, deps.diagnostics.summary())
            file_manager.save_json(deps.module_tree, module_tree_path)
            return deps.module_tree
        except Exception as e:
            logger.info("module %s diagnostics (on raise): %s", module_name, deps.diagnostics.summary())
            # Small-output models (e.g. DeepSeek, 8K output cap) can raise *after*
            # the module's documentation is already written to disk, when the agent
            # attempts one extra oversized tool call that exceeds the output limit.
            # If the doc file exists, the deliverable is done — treat the module as
            # complete and persist its module-tree entry instead of failing it.
            docs_path = os.path.join(working_dir, f"{module_name}.md")
            if os.path.exists(docs_path):
                logger.warning(
                    "Module %s agent raised after writing docs (%s); treating as complete",
                    module_name, e,
                )
                file_manager.save_json(deps.module_tree, module_tree_path)
                return deps.module_tree
            logger.error("Error processing module %s: %s", module_name, e)
            logger.error("Traceback: %s", traceback.format_exc())
            raise
