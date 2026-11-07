"""Attach to an existing remote debugpy endpoint."""

from debugpilot.debugger.remote_attach import RemoteAttachSession


class PythonAttachSession(RemoteAttachSession):
    """Python inspection API over an existing loopback debugpy endpoint.

    Breakpoints and stack frames are translated by the base session, so debugpy only
    ever sees target paths and needs no pathMappings.
    """

    attach_field = 'python_attach'
    config_name = 'pythonAttach'
    language = 'Python'
    target_name = 'Python/debugpy'
    adapter_id = 'python'

    def _attach_arguments(self, name, attach):
        return {'name': name, 'type': 'debugpy', 'request': 'attach',
                'justMyCode': True, 'subProcess': False}
