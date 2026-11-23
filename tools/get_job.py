from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from jobo_client.glue import raise_tool_error, service_from_credentials


class GetJobTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        service = service_from_credentials(self.runtime.credentials)
        try:
            result = service.get_job(
                tool_parameters.get("job_id"),
                include_description=tool_parameters.get("include_description", True)
                is not False,
            )
        except Exception as error:
            raise_tool_error(error)
        yield self.create_text_message(result.text)
        yield self.create_json_message(result.data)
