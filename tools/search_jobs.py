from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from jobo_client.glue import raise_tool_error, service_from_credentials


class SearchJobsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        service = service_from_credentials(self.runtime.credentials)
        try:
            result = service.search_jobs(tool_parameters)
        except Exception as error:
            raise_tool_error(error)
        yield self.create_text_message(result.text)
        yield self.create_json_message(result.data)
