"""Attach to an existing remote Delve DAP server."""

from debugpilot.debugger.go import GO_EXCEPTION_FILTERS
from debugpilot.debugger.remote_attach import RemoteAttachSession


class GoAttachSession(RemoteAttachSession):
    """Go inspection API over an existing loopback Delve DAP endpoint."""

    VALUE_REPR = False  # Delve cannot run code to serialize a value.
    EXCEPTION_FILTERS = GO_EXCEPTION_FILTERS

    attach_field = 'go_attach'
    config_name = 'goAttach'
    language = 'Go'
    target_name = 'Go/Delve'
    adapter_id = 'go'

    def _attach_arguments(self, name, attach):
        return {
            'name': name, 'type': 'go', 'request': 'attach', 'mode': 'remote',
            'host': attach.host, 'port': attach.port,
            'substitutePath': [{'from': str(self._local_root), 'to': attach.remote_root}],
        }
