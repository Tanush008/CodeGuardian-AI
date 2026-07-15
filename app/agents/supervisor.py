"""Supervisor Agent graph.

Builds the LangGraph StateGraph: fetch changed files -> fan out to Security
Agent and Quality Agent in parallel -> fan in to the Aggregator -> post the
comment via the GitHub MCP client. Compiled once at import time and reused
across requests (LangGraph graphs are stateless/reentrant; per-run state
lives in the ReviewState dict passed to .ainvoke).
"""
from langgraph.graph import END, StateGraph

from app.agents.aggregator import aggregator_node
from app.agents.quality_agent import quality_agent_node
from app.agents.security_agent import security_agent_node
from app.agents.state import ReviewState
from app.core.config import settings
from app.core.logging_setup import get_logger
from app.mcp_servers.github_mcp_client import GitHubMCPClient

logger = get_logger(__name__)

async def fetch_changed_files_node(state: ReviewState) -> ReviewState:
    """Fan-in point for GitHub data fetch: pulls the diff file list and full
    content for each changed (non-deleted) file via the MCP client, capped
    by MAX_DIFF_FILES/MAX_FILE_BYTES so a huge PR can't blow the run."""
    ctx = state["pr_context"]
    errors = list(state.get("errors", []))

    async with GitHubMCPClient() as client:
        head_sha = await client.call_tool(
            "get_pr_head_sha",
            {
                "installation_id": ctx["installation_id"],
                "owner": ctx["owner"],
                "repo": ctx["repo"],
                "pr_number": ctx["pr_number"],
            },
        )

        files_meta = await client.call_tool(
            "list_changed_files",
            {
                "installation_id": ctx["installation_id"],
                "owner": ctx["owner"],
                "repo": ctx["repo"],
                "pr_number": ctx["pr_number"],
            },
        )
        
        if isinstance(files_meta, dict):
            # If fastmcp returns a single dictionary instead of a list (when only 1 file is changed)
            files_meta = [files_meta]
        elif isinstance(files_meta, str):
            import json
            try:
                files_meta = json.loads(files_meta.replace("'", '"'))
            except Exception:
                files_meta = []

        files_meta = files_meta[: settings.max_diff_files]
        changed_files: dict[str, str] = {}

        for f in files_meta:
            if f["status"] == "removed":
                continue
            try:
                content = await client.call_tool(
                    "get_file_content",
                    {
                        "installation_id": ctx["installation_id"],
                        "owner": ctx["owner"],
                        "repo": ctx["repo"],
                        "path": f["filename"],
                        "ref": head_sha,
                    },
                )
                if isinstance(content, str) and len(content.encode("utf-8")) <= settings.max_file_bytes:
                    changed_files[f["filename"]] = content
            except Exception as exc:
                errors.append(f"could not fetch {f['filename']}: {exc}")
                logger.warning("file_fetch_failed", file=f["filename"], error=str(exc))

    logger.info("changed_files_fetched", count=len(changed_files))
    return {**state, "changed_files": changed_files, "errors": errors}


async def post_comment_node(state: ReviewState) -> ReviewState:
    ctx = state["pr_context"]
    async with GitHubMCPClient() as client:
        result = await client.call_tool(
            "post_review_comment",
            {
                "installation_id": ctx["installation_id"],
                "owner": ctx["owner"],
                "repo": ctx["repo"],
                "pr_number": ctx["pr_number"],
                "body_markdown": state["report_markdown"],
            },
        )
    logger.info("comment_posted", url=result.get("html_url"))
    return {**state, "posted_comment_url": result.get("html_url", "")}


def build_graph():
    graph = StateGraph(ReviewState)

    graph.add_node("fetch_changed_files", fetch_changed_files_node)
    graph.add_node("security_agent", security_agent_node)
    graph.add_node("quality_agent", quality_agent_node)
    graph.add_node("aggregator", aggregator_node)
    graph.add_node("post_comment", post_comment_node)

    graph.set_entry_point("fetch_changed_files")

    # Fan-out: both agents run off the same fetched-files state.
    graph.add_edge("fetch_changed_files", "security_agent")
    graph.add_edge("fetch_changed_files", "quality_agent")

    # Fan-in: aggregator waits for both branches (LangGraph runs the graph
    # in supersteps, so a node with multiple incoming edges only fires once
    # all its predecessors for that step have completed).
    graph.add_edge("security_agent", "aggregator")
    graph.add_edge("quality_agent", "aggregator")

    graph.add_edge("aggregator", "post_comment")
    graph.add_edge("post_comment", END)

    return graph.compile()


review_graph = build_graph()


async def run_review(pr_context: dict) -> ReviewState:
    initial_state: ReviewState = {"pr_context": pr_context, "errors": []}  # type: ignore[typeddict-item]
    logger.info("review_started", pr=pr_context)
    final_state = await review_graph.ainvoke(initial_state)
    logger.info("review_finished", pr=pr_context, comment_url=final_state.get("posted_comment_url"))
    return final_state
