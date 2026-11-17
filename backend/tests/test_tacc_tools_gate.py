from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.tools_probe import ToolsOnly


def test_only_tool_paths_can_reach_backend():
    app=FastAPI()
    @app.api_route('/{path:path}',methods=['GET','POST','DELETE'])
    def reached(path):return {'reached':True}
    client=TestClient(ToolsOnly(app))
    for method,path in [('GET','/health'),('GET','/ready'),('GET','/api/v1/paper-search'),('POST','/api/v1/paper-imports'),('GET','/api/v1/paper-imports/11111111-1111-4111-8111-111111111111'),('GET','/api/v1/papers/11111111-1111-4111-8111-111111111111/file')]:
        assert client.request(method,path).status_code==200
    for method,path in [('GET','/docs'),('POST','/api/v1/auth/register'),('POST','/api/v1/tasks'),('GET','/api/v1/tasks'),('DELETE','/api/v1/paper-imports'),('GET','/api/v1/papers'),('GET','/api/v1/papers/not-a-uuid/file')]:
        assert client.request(method,path).status_code==404
