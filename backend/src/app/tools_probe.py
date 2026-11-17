"""Temporary tool-only ASGI entry for an explicitly configured isolated test backend."""
import json
import os
import re
from pathlib import Path

from starlette.responses import JSONResponse

_UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


class ToolsOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            method, path = scope['method'], scope['path']
            allowed = (method == 'GET' and path in {'/health','/ready','/api/v1/paper-search'})
            allowed |= method == 'POST' and path == '/api/v1/paper-imports'
            allowed |= method == 'GET' and bool(re.fullmatch('/api/v1/paper-imports/' + _UUID, path))
            allowed |= method == 'GET' and bool(re.fullmatch('/api/v1/papers/' + _UUID + '/file', path))
            if not allowed:
                await JSONResponse({'error':{'code':'NOT_FOUND','message':'Not found','details':{}}},status_code=404)(scope,receive,send)
                return
        await self.app(scope,receive,send)


def settings():
    from app.config import Settings
    # A private generated configuration, never a public HTTP input.
    return Settings(_env_file=None, **json.loads(Path(os.environ['TACC_PROBE_CONFIG']).read_text()))


def create_app():
    from app.main import create_app as create_backend
    return ToolsOnly(create_backend(settings()))
