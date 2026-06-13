import asyncio
import logging
import os
import json
import re
from typing import Dict, List, Any
from copy import deepcopy
import traceback

# Configure logging and monitoring
logger = logging.getLogger(__name__)

# Local imports
from codewiki.src.be.dependency_analyzer import DependencyGraphBuilder
from codewiki.src.be.backend import LLMBackend, get_backend
from codewiki.src.be.prompt_template import (
    REPO_OVERVIEW_PROMPT,
    MODULE_OVERVIEW_PROMPT,
)
from codewiki.src.be.cluster_modules import (
    cluster_modules,
    get_clustering_input_token_count,
)
from codewiki.src.config import (
    Config,
    FIRST_MODULE_TREE_FILENAME,
    MODULE_TREE_FILENAME,
    OVERVIEW_FILENAME
)
from codewiki.src.utils import file_manager


def canonical_doc_name(node_key: str) -> str:
    """The on-disk doc filename for a module-tree node.

    Sanitize only the filesystem path separators (``/`` and ``\\``); keep the
    rest of the key raw (spaces, ``#``). This is the contract the wiki nav uses
    (its JS ``slug()`` applies the identical rule).
    """
    return re.sub(r"[\\/]", "_", node_key) + ".md"


def _norm_name(s: str) -> str:
    """Casefold + drop non-alphanumerics, for matching keys to filenames."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _first_h1(path: str) -> str:
    """Return the text of the first markdown ``# `` heading, or ''."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return ""


def canonicalize_doc_filenames(working_dir: str, module_tree: dict) -> list:
    """Rename each module-tree node's doc to ``canonical_doc_name(key)``.

    Resolution is two-phase so a normalized-name match always beats a weaker
    H1-title match regardless of tree order. Renames files only (the nav derives
    filenames from node keys, so the tree is untouched). Idempotent. Returns the
    list of ``(old_name, new_name)`` renames performed.

    Note: two distinct keys that canonicalize to the same filename (e.g. ``A/B``
    and ``A_B`` both → ``A_B.md``) cannot both resolve — the second is skipped
    without clobbering the first (its nav link stays broken). The H1 fallback is
    a substring heuristic; very short keys could mis-bind, but the collision
    guard prevents data loss and ambiguity is logged.
    """
    keys = []

    def _walk(t):
        for name, info in t.items():
            if not isinstance(info, dict):
                continue
            if info.get("components"):  # only nodes with components have generated docs
                keys.append(name)
            _walk(info.get("children") or {})

    _walk(module_tree)

    md_files = [f for f in os.listdir(working_dir)
                if f.endswith(".md") and f != OVERVIEW_FILENAME]
    by_norm = {}
    for f in md_files:
        by_norm.setdefault(_norm_name(f[:-3]), []).append(f)

    claimed = set()
    resolved = {}

    # Phase 1: normalized-name match.
    for key in keys:
        if key in resolved:
            continue
        nk = _norm_name(key)
        if not nk:  # a key with no alphanumerics can't be matched safely
            continue
        for f in by_norm.get(nk, []):
            if f not in claimed:
                resolved[key] = f
                claimed.add(f)
                break

    # Phase 2: H1-title fallback for still-unresolved nodes.
    for key in keys:
        if key in resolved:
            continue
        nk = _norm_name(key)
        if not nk:
            continue
        matches = [f for f in md_files
                   if f not in claimed and nk in _norm_name(_first_h1(os.path.join(working_dir, f)))]
        if len(matches) == 1:
            resolved[key] = matches[0]
            claimed.add(matches[0])
        elif matches:
            logger.warning("canonicalize: ambiguous node %r (candidates=%s)", key, matches)
        else:
            logger.debug("canonicalize: no doc found for node %r", key)

    renames = []
    for key, f in resolved.items():
        target = canonical_doc_name(key)
        if f == target:
            continue
        src = os.path.join(working_dir, f)
        dst = os.path.join(working_dir, target)
        if os.path.exists(dst):
            if not os.path.samefile(src, dst):
                logger.warning("canonicalize: target %r exists (different file); skipping %r", target, f)
                continue
            # case/separator-only difference on a case-insensitive FS: two-step rename.
            tmp = src + ".tmprename"
            os.rename(src, tmp)
            os.rename(tmp, dst)
        else:
            os.rename(src, dst)
        renames.append((f, target))
        logger.info("canonicalize: %s -> %s", f, target)
    return renames


class DocumentationGenerator:
    """Main documentation generation orchestrator."""

    def __init__(self, config: Config, commit_id: str = None, backend: LLMBackend = None):
        self.config = config
        self.commit_id = commit_id
        self.graph_builder = DependencyGraphBuilder(config)
        self.backend: LLMBackend = backend or get_backend(config)
    
    def create_documentation_metadata(self, working_dir: str, components: Dict[str, Any], num_leaf_nodes: int):
        """Create a metadata file with documentation generation information."""
        from datetime import datetime
        
        metadata = {
            "generation_info": {
                "timestamp": datetime.now().isoformat(),
                "main_model": self.config.main_model,
                "generator_version": "1.0.1",
                "repo_path": self.config.repo_path,
                "commit_id": self.commit_id
            },
            "statistics": {
                "total_components": len(components),
                "leaf_nodes": num_leaf_nodes,
                "max_depth": self.config.max_depth
            },
            "files_generated": [
                "overview.md",
                "module_tree.json",
                "first_module_tree.json"
            ]
        }
        
        # Add generated markdown files to the metadata
        try:
            for file_path in os.listdir(working_dir):
                if file_path.endswith('.md') and file_path not in metadata["files_generated"]:
                    metadata["files_generated"].append(file_path)
        except Exception as e:
            logger.warning(f"Could not list generated files: {e}")
        
        metadata_path = os.path.join(working_dir, "metadata.json")
        file_manager.save_json(metadata, metadata_path)

    
    def get_processing_order(self, module_tree: Dict[str, Any], parent_path: List[str] = []) -> List[tuple[List[str], str]]:
        """Get the processing order using topological sort (leaf modules first)."""
        processing_order = []
        
        def collect_modules(tree: Dict[str, Any], path: List[str]):
            for module_name, module_info in tree.items():
                current_path = path + [module_name]
                
                # If this module has children, process them first
                if module_info.get("children") and isinstance(module_info["children"], dict) and module_info["children"]:
                    collect_modules(module_info["children"], current_path)
                    # Add this parent module after its children
                    processing_order.append((current_path, module_name))
                else:
                    # This is a leaf module, add it immediately
                    processing_order.append((current_path, module_name))
        
        collect_modules(module_tree, parent_path)
        return processing_order

    def is_leaf_module(self, module_info: Dict[str, Any]) -> bool:
        """Check if a module is a leaf module (has no children or empty children)."""
        children = module_info.get("children", {})
        return not children or (isinstance(children, dict) and len(children) == 0)

    def build_overview_structure(self, module_tree: Dict[str, Any], module_path: List[str],
                                 working_dir: str) -> Dict[str, Any]:
        """Build structure for overview generation with 1-depth children docs and target indicator."""
        
        processed_module_tree = deepcopy(module_tree)
        module_info = processed_module_tree
        for path_part in module_path:
            module_info = module_info[path_part]
            if path_part != module_path[-1]:
                module_info = module_info.get("children", {})
            else:
                module_info["is_target_for_overview_generation"] = True

        if "children" in module_info:
            module_info = module_info["children"]

        for child_name, child_info in module_info.items():
            child_docs_path = self._resolve_child_docs_path(working_dir, child_name)
            if child_docs_path is not None:
                child_info["docs"] = file_manager.load_text(child_docs_path)
            else:
                logger.warning(f"Module docs not found at {os.path.join(working_dir, f'{child_name}.md')}")
                child_info["docs"] = ""

        return processed_module_tree

    @staticmethod
    def _resolve_child_docs_path(working_dir: str, child_name: str) -> str | None:
        """Resolve the on-disk path for a child module's .md doc.

        Sub-agents sometimes save files under a sanitized variant of the
        module name (spaces → underscores, lowercased, etc.) rather than the
        exact key in the module tree. Try a small set of common variants
        before giving up so the overview prompt still gets the children's
        content as context.
        """
        candidates = []
        seen = set()
        base_variants = [
            child_name,
            child_name.replace(" ", "_"),
            child_name.replace(" ", "-"),
            child_name.replace(" ", ""),
        ]
        for variant in base_variants:
            for cased in (variant, variant.lower()):
                if cased not in seen:
                    seen.add(cased)
                    candidates.append(f"{cased}.md")

        for filename in candidates:
            candidate_path = os.path.join(working_dir, filename)
            if os.path.exists(candidate_path):
                return candidate_path
        return None

    def _iter_tree_nodes(self, tree: Dict[str, Any], path: List[str] = None):
        """Yield (module_path, module_name, module_info) for every node in the tree."""
        path = path or []
        for name, info in tree.items():
            if not isinstance(info, dict):
                continue
            node_path = path + [name]
            yield node_path, name, info
            children = info.get("children", {})
            if isinstance(children, dict) and children:
                yield from self._iter_tree_nodes(children, node_path)

    async def _fill_missing_docs(self, components: Dict[str, Any], working_dir: str,
                                 module_tree_path: str) -> None:
        """Stage 4: deterministically regenerate any tree node whose .md is absent.

        Converts the "parent already finished, so no parent-recovery" gap into a
        guaranteed second pass. Reuses ``run_module_agent``'s own "already exists"
        skip, so nodes that DO have a doc are untouched. With profile-derived
        granularity sized to the model's output cap (Stage 2), oversized leaves are
        already split, so this sweep is a safety net rather than the primary fix.
        """
        module_tree = file_manager.load_json(module_tree_path)
        missing = [
            (node_path, node_name, info)
            for node_path, node_name, info in self._iter_tree_nodes(module_tree)
            if info.get("components") and self._resolve_child_docs_path(working_dir, node_name) is None
        ]
        if not missing:
            return
        logger.info(
            "Missing-doc sweep: %d node(s) without a doc: %s",
            len(missing), ", ".join(n for _, n, _ in missing),
        )
        for node_path, node_name, info in missing:
            try:
                logger.info("↻ Regenerating missing doc for: %s", "/".join(node_path))
                await self.backend.run_module_agent(
                    module_name=node_name,
                    components=components,
                    core_component_ids=info["components"],
                    module_path=node_path,
                    working_dir=working_dir,
                )
            except Exception as e:
                logger.error("Missing-doc sweep failed for %s: %s", node_name, e)
                continue

    @staticmethod
    def _navigate(tree: Dict[str, Any], module_path: List[str]) -> Dict[str, Any]:
        """Return the node at *module_path* (mirrors the sequential loop's navigation)."""
        node = tree
        for path_part in module_path:
            node = node[path_part]
            if path_part != module_path[-1]:
                node = node.get("children", {})
        return node

    @staticmethod
    def _sanitize_name(name: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in name)

    @staticmethod
    def _merge_module_trees(base: Dict[str, Any], results: List) -> Dict[str, Any]:
        """Graft each module's isolated (updated) subtree back into a copy of *base*.

        Concurrently-processed top-level modules occupy disjoint paths, so grafting
        each module's node at its path is conflict-free and equivalent to the
        sequential result (modulo iteration order).
        """
        merged = deepcopy(base)
        for module_path, updated_tree in results:
            src, dst = updated_tree, merged
            for part in module_path[:-1]:
                src = src[part]["children"]
                dst = dst[part]["children"]
            key = module_path[-1]
            if key in src:
                dst[key] = src[key]
        return merged

    async def _process_modules_concurrent(self, processing_order, components, working_dir,
                                          module_tree_path, concurrency: int) -> Dict[str, Any]:
        """Document disjoint top-level leaf modules concurrently with per-module tree isolation.

        Each module runs against a deep-copied isolated module-tree file; results are
        merged into the canonical tree after the barrier. Used only when every entry is
        a leaf and module names are unique (caller guarantees this).
        """
        base_tree = file_manager.load_json(module_tree_path)
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def run_one(module_path, module_name):
            async with semaphore:
                iso_path = os.path.join(working_dir, f"module_tree.{self._sanitize_name(module_name)}.json")
                file_manager.save_json(deepcopy(base_tree), iso_path)
                try:
                    logger.info(f"📄 [concurrent] Processing leaf module: {'/'.join(module_path)}")
                    updated = await self.backend.run_module_agent(
                        module_name=module_name,
                        components=components,
                        core_component_ids=self._navigate(base_tree, module_path)["components"],
                        module_path=module_path,
                        working_dir=working_dir,
                        module_tree_path=iso_path,
                    )
                    return module_path, updated
                finally:
                    if os.path.exists(iso_path):
                        os.remove(iso_path)

        results = await asyncio.gather(
            *(run_one(mp, mn) for mp, mn in processing_order), return_exceptions=True
        )
        ok = [r for r in results if isinstance(r, tuple)]
        for r in results:
            if isinstance(r, Exception):
                logger.error("Concurrent module failed: %s", r)
        merged = self._merge_module_trees(base_tree, ok)
        file_manager.save_json(merged, module_tree_path)
        return merged

    async def generate_module_documentation(self, components: Dict[str, Any], leaf_nodes: List[str]) -> str:
        """Generate documentation for all modules using dynamic programming approach."""
        # Prepare output directory
        working_dir = os.path.abspath(self.config.docs_dir)
        file_manager.ensure_directory(working_dir)

        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        first_module_tree_path = os.path.join(working_dir, FIRST_MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)
        first_module_tree = file_manager.load_json(first_module_tree_path)
        
        # Get processing order (leaf modules first)
        processing_order = self.get_processing_order(first_module_tree)

        
        # Process modules in dependency order
        final_module_tree = module_tree
        processed_modules = set()

        # Stage 5: opt-in concurrent processing of disjoint top-level leaf modules.
        # Guarded to the safe case (all leaves + unique names); otherwise sequential.
        concurrency = getattr(self.config, "concurrency", 1) or 1
        names = [n for _, n in processing_order]
        unique_names = len(set(names)) == len(names)
        all_leaves = all(self.is_leaf_module(self._navigate(module_tree, p)) for p, _ in processing_order) if module_tree else False

        if len(module_tree) > 0 and concurrency > 1 and all_leaves and unique_names:
            logger.info("Processing %d modules with concurrency=%d (per-module tree isolation)", len(processing_order), concurrency)
            final_module_tree = await self._process_modules_concurrent(
                processing_order, components, working_dir, module_tree_path, concurrency
            )
            await self._fill_missing_docs(components, working_dir, module_tree_path)
            logger.info("📚 Generating repository overview")
            final_module_tree = await self.generate_parent_module_docs([], working_dir)
        elif len(module_tree) > 0:
            if concurrency > 1:
                reason = "duplicate module names" if not unique_names else "pre-clustered parent modules present"
                logger.warning("Concurrency disabled (%s); falling back to sequential.", reason)
            for module_path, module_name in processing_order:
                try:
                    # Reload module tree to get latest hierarchical structure from sub-agent modifications
                    module_tree = file_manager.load_json(module_tree_path)
                    
                    # Get the module info from the tree
                    module_info = module_tree
                    for path_part in module_path:
                        module_info = module_info[path_part]
                        if path_part != module_path[-1]:  # Not the last part
                            module_info = module_info.get("children", {})
                    
                    # Skip if already processed
                    module_key = "/".join(module_path)
                    if module_key in processed_modules:
                        continue
                    
                    # Process the module
                    if self.is_leaf_module(module_info):
                        logger.info(f"📄 Processing leaf module: {module_key}")
                        final_module_tree = await self.backend.run_module_agent(
                            module_name=module_name,
                            components=components,
                            core_component_ids=module_info["components"],
                            module_path=module_path,
                            working_dir=working_dir,
                        )
                    else:
                        logger.info(f"📁 Processing parent module: {module_key}")
                        final_module_tree = await self.generate_parent_module_docs(
                            module_path, working_dir
                        )
                    
                    processed_modules.add(module_key)
                    
                except Exception as e:
                    logger.error(f"Failed to process module {module_key}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    continue

            # Stage 4: deterministically fill any sub-module whose doc never materialized
            # (the "large sub-module × parent already finished" gap) before the overview.
            await self._fill_missing_docs(components, working_dir, module_tree_path)

            # Generate repo overview
            logger.info(f"📚 Generating repository overview")
            final_module_tree = await self.generate_parent_module_docs(
                [], working_dir
            )
        else:
            logger.info(f"Processing whole repo because repo can fit in the context window")
            repo_name = os.path.basename(os.path.normpath(self.config.repo_path))
            final_module_tree = await self.backend.run_module_agent(
                module_name=repo_name,
                components=components,
                core_component_ids=leaf_nodes,
                module_path=[],
                working_dir=working_dir,
            )

            # save final_module_tree to module_tree.json
            file_manager.save_json(final_module_tree, os.path.join(working_dir, MODULE_TREE_FILENAME))

            # rename repo_name.md to overview.md
            repo_overview_path = os.path.join(working_dir, f"{repo_name}.md")
            if os.path.exists(repo_overview_path):
                os.rename(repo_overview_path, os.path.join(working_dir, OVERVIEW_FILENAME))
        
        # Canonicalize doc filenames to the nav's ${node-key}.md contract.
        canonicalize_doc_filenames(working_dir, file_manager.load_json(module_tree_path))

        return working_dir

    async def generate_parent_module_docs(self, module_path: List[str],
                                        working_dir: str) -> Dict[str, Any]:
        """Generate documentation for a parent module based on its children's documentation."""
        module_name = module_path[-1] if len(module_path) >= 1 else os.path.basename(os.path.normpath(self.config.repo_path))

        logger.info(f"Generating parent documentation for: {module_name}")
        
        # Load module tree
        module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
        module_tree = file_manager.load_json(module_tree_path)

        # check if overview docs already exists
        overview_docs_path = os.path.join(working_dir, OVERVIEW_FILENAME)
        if os.path.exists(overview_docs_path):
            logger.info(f"✓ Overview docs already exists at {overview_docs_path}")
            return module_tree

        # check if parent docs already exists
        parent_docs_path = os.path.join(working_dir, f"{module_name if len(module_path) >= 1 else OVERVIEW_FILENAME.replace('.md', '')}.md")
        if os.path.exists(parent_docs_path):
            logger.info(f"✓ Parent docs already exists at {parent_docs_path}")
            return module_tree

        # Create repo structure with 1-depth children docs and target indicator
        repo_structure = self.build_overview_structure(module_tree, module_path, working_dir)

        prompt = MODULE_OVERVIEW_PROMPT.format(
            module_name=module_name,
            repo_structure=json.dumps(repo_structure, indent=4)
        ) if len(module_path) >= 1 else REPO_OVERVIEW_PROMPT.format(
            repo_name=module_name,
            repo_structure=json.dumps(repo_structure, indent=4)
        )
        
        try:
            parent_docs = self.backend.complete(prompt)

            # Parse and save parent documentation. Subscription-CLI backends
            # (claude-code / codex) sometimes ignore the <OVERVIEW> wrapper and
            # return raw markdown; fall back to the response as-is in that case
            # rather than crashing with an index error.
            if "<OVERVIEW>" in parent_docs and "</OVERVIEW>" in parent_docs:
                parent_content = parent_docs.split("<OVERVIEW>")[1].split("</OVERVIEW>")[0].strip()
            else:
                logger.warning(
                    f"Overview response for {module_name} missing <OVERVIEW> wrapper; "
                    f"using raw response as markdown."
                )
                parent_content = parent_docs.strip()
            file_manager.save_text(parent_content, parent_docs_path)
            
            logger.debug(f"Successfully generated parent documentation for: {module_name}")
            return module_tree
            
        except Exception as e:
            logger.error(f"Error generating parent documentation for {module_name}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    async def run(self) -> None:
        """Run the complete documentation generation process using dynamic programming."""
        try:
            # Build dependency graph
            components, leaf_nodes = self.graph_builder.build_dependency_graph()

            logger.debug(f"Found {len(leaf_nodes)} leaf nodes")
            # logger.debug(f"Leaf nodes:\n{'\n'.join(sorted(leaf_nodes)[:200])}")
            # exit()
            
            # Cluster modules
            working_dir = os.path.abspath(self.config.docs_dir)
            file_manager.ensure_directory(working_dir)
            first_module_tree_path = os.path.join(working_dir, FIRST_MODULE_TREE_FILENAME)
            module_tree_path = os.path.join(working_dir, MODULE_TREE_FILENAME)
            
            # Check if module tree exists
            if os.path.exists(first_module_tree_path):
                logger.debug(f"Module tree found at {first_module_tree_path}")
                module_tree = file_manager.load_json(first_module_tree_path)
            else:
                logger.debug(f"Module tree not found at {module_tree_path}, clustering modules")
                clustering_tokens = get_clustering_input_token_count(
                    leaf_nodes, components
                )
                logger.info(
                    "Preparing %d leaf nodes for module clustering (%d tokens, threshold %d)",
                    len(leaf_nodes),
                    clustering_tokens,
                    self.config.max_token_per_module,
                )
                # Bind cluster_model into the completer so the backend uses the
                # configured clustering model (separate from main_model) when
                # one is set.  Caw mode's cluster_model is typically empty —
                # complete() falls back to its own _model in that case.
                cluster_model = self.config.cluster_model or None
                module_tree = cluster_modules(
                    leaf_nodes,
                    components,
                    self.config,
                    completer=lambda p: self.backend.complete(p, model=cluster_model),
                )
                file_manager.save_json(module_tree, first_module_tree_path)
            
            file_manager.save_json(module_tree, module_tree_path)
            
            if len(module_tree) == 0:
                logger.info(
                    "Module clustering produced no top-level modules; continuing in "
                    "whole-repository documentation mode"
                )
            else:
                logger.info(
                    "Grouped components into %d top-level modules",
                    len(module_tree),
                )
            
            # Generate module documentation using dynamic programming approach
            # This processes leaf modules first, then parent modules
            working_dir = await self.generate_module_documentation(components, leaf_nodes)
            
            # Create documentation metadata
            self.create_documentation_metadata(working_dir, components, len(leaf_nodes))
            
            logger.debug(f"Documentation generation completed successfully using dynamic programming!")
            logger.debug(f"Processing order: leaf modules → parent modules → repository overview")
            logger.debug(f"Documentation saved to: {working_dir}")
            
        except Exception as e:
            logger.error(f"Documentation generation failed: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
