from typing import Any, List

import aiohttp
from fastapi.responses import StreamingResponse as FastAPIStreamingResponse

from reworkd_platform.schemas import ModelSettings
from reworkd_platform.settings import settings
from reworkd_platform.web.api.agent.tools.stream_mock import stream_string
from reworkd_platform.web.api.agent.tools.tool import Tool
from reworkd_platform.web.api.agent.tools.utils import summarize


# Search google via serper.dev. Adapted from LangChain
# https://github.com/hwchase17/langchain/blob/master/langchain/utilities


async def _google_serper_search_results(
    search_term: str, search_type: str = "search"
) -> dict[str, Any]:
    headers = {
        "X-API-KEY": settings.serp_api_key or "",
        "Content-Type": "application/json",
    }
    params = {
        "q": search_term,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
                    f"https://google.serper.dev/{search_type}", headers=headers, params=params
                ) as response:
            response.raise_for_status()
            return await response.json()


class Search(Tool):
    description = (
        "Search Google for short up to date searches for simple questions "
        "news and people.\n"
        "The argument should be the search query."
    )
    public_description = "Search google for information about current events."

    def __init__(self, model_settings: ModelSettings):
        super().__init__(model_settings)

    @staticmethod
    def available() -> bool:
        return settings.serp_api_key is not None

    async def call(
        self, goal: str, task: str, input_str: str
    ) -> FastAPIStreamingResponse:
        results = await _google_serper_search_results(
            input_str,
        )

        k = 6  # Number of results to return
        max_links = 3  # Number of links to return
        snippets: List[str] = []
        links: List[str] = []

        if results.get("answerBox"):
            answer_values = []
            answer_box = results.get("answerBox", {})
            if answer_box.get("answer"):
                answer_values.append(answer_box.get("answer"))
            elif answer_box.get("snippet"):
                answer_values.append(answer_box.get("snippet").replace("\n", " "))
            elif answer_box.get("snippetHighlighted"):
                answer_values.append(", ".join(answer_box.get("snippetHighlighted")))

            if answer_values:
                return stream_string("\n".join(answer_values), True)

        if results.get("knowledgeGraph"):
            kg = results.get("knowledgeGraph", {})
            title = kg.get("title")
            if entity_type := kg.get("type"):
                snippets.append(f"{title}: {entity_type}.")
            if description := kg.get("description"):
                snippets.append(description)
            snippets.extend(
                f"{title} {attribute}: {value}."
                for attribute, value in kg.get("attributes", {}).items()
            )
        for result in results["organic"][:k]:
            if "snippet" in result:
                snippets.append(result["snippet"])
            if "link" in result and len(links) < max_links:
                links.append(result["link"])
            snippets.extend(
                f"{attribute}: {value}."
                for attribute, value in result.get("attributes", {}).items()
            )
        if not snippets:
            return stream_string("No good Google Search Result was found", True)

        return summarize(self.model_settings, goal, task, snippets)

        # TODO: Stream with formatting
        # return f"{summary}\n\nLinks:\n" + "\n".join([f"- {link}" for link in links])
