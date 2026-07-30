"""InkFlow REST API 路由注册。"""

from inkflow.api.app import app

# 在此导入并注册各模块路由：
# from inkflow.api import projects, chapters, writing, ...


@app.get("/api/v1/status")
async def api_status():
    return {"version": "0.1.0", "status": "operational"}
