"""InkFlow REST API 路由注册。"""

from inkflow.api.app import app
from inkflow.logging import instrument

# 在此导入并注册各模块路由：
# from inkflow.api import projects, chapters, writing, ...


@app.get("/api/v1/status")
@instrument(caller_type="api")
async def api_status():
    return {"version": "0.1.0", "status": "operational"}
