import uuid
import socket
import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
import json
from workflow.graph import create_graph

try:
    from urllib3.exceptions import NotOpenSSLWarning

    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass

app = FastAPI(title="Cycling Agent Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

graph = create_graph()


class PlanRequest(BaseModel):
    intent: str
    user_id: str = "default_user"


class FinalizeRequest(BaseModel):
    thread_id: str
    route_id: str


# ─────────────────────────────────────────────
# SSE Stream: Phase 1 – propose route options
# ─────────────────────────────────────────────

async def event_generator(request: PlanRequest, thread_id: str):
    initial_state = {
        "user_intent": request.intent,
        "user_profile": {},
        "messages": [],
        "plan": [],
        "route_data": {},
        "weather_info": {},
        "poi_info": [],
        "safety_warnings": [],
        "final_plan_markdown": "",
        "route_research_context": "",
        "intent_type": "TYPE_A",
        "lifestyle_context": {},
        "parsed_constraints": {},
        "analysis_summary": {},
    }

    config = {"configurable": {"thread_id": thread_id}}

    node_labels = {
        "demand_parser": "🧩 解析自然语言地点 & 输出路线函数参数...",
        "intent_research": "🔍 分析骑行意图 & 生活化偏好感知...",
        "geospatial_analysis": "🛰️ 解析区域、别名和地理锚点...",
        "coordinate_control": "📌 核验起终点坐标 & 锁定路线骨架...",
        "planner":         "📍 生成可执行候选路线...",
        "executor":        "📡 实时获取路网 / 天气 / POI 数据...",
        "route_policy":    "🚲 校验自行车路权规则 & 过滤高风险道路...",
        "lifestyle":       "🌅 计算日落时刻 & 评估骑行体验...",
        "physics":         "⚡ 物理引擎推演（体能 / 爬升 / 卡路里）...",
        "explainability":  "🧭 生成分段说明 / 关键道路 / 可视化摘要...",
    }
    node_progress = {
        "demand_parser": 8,
        "intent_research": 16,
        "geospatial_analysis": 24,
        "coordinate_control": 36,
        "planner": 44,
        "executor": 56,
        "route_policy": 70,
        "lifestyle": 82,
        "physics": 92,
        "explainability": 100,
    }

    try:
        async for event in graph.astream(initial_state, config):
            for node_name, output in event.items():
                label = node_labels.get(node_name, f"⚙️ {node_name}...")
                data = {
                    "node": node_name,
                    "label": label,
                    "type": "progress",
                    "progress": node_progress.get(node_name, 0),
                }

                if node_name == "explainability":
                    routes = output.get("route_data", {}).get("routes", [])
                    data["type"] = "routes_ready"
                    data["routes"] = routes
                    data["analysis"] = output.get("analysis_summary", {})
                    # Get current state to also read weather from full state
                    try:
                        full_state = graph.get_state(config).values
                        data["weather"] = full_state.get("weather_info", {})
                        data["poi"] = full_state.get("poi_info", {})
                        data["constraints"] = full_state.get("parsed_constraints", {})
                        data["analysis"] = full_state.get("analysis_summary", {})
                    except:
                        pass

                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


# ─────────────────────────────────────────────
# SSE Stream: Phase 2 – generate roadbook
# ─────────────────────────────────────────────

async def finalize_generator(request: FinalizeRequest):
    config = {"configurable": {"thread_id": request.thread_id}}

    try:
        full_state = graph.get_state(config).values
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Cannot load state: {e}'})}\n\n"
        return

    all_routes = full_state.get("route_data", {}).get("routes", [])
    selected = next(
        (r for r in all_routes if r.get("metrics", {}).get("id") == request.route_id),
        all_routes[0] if all_routes else {}
    )

    # Inject selected route back
    if selected:
        new_route_data = dict(full_state.get("route_data", {}))
        new_route_data["routes"] = [selected]
        graph.update_state(config, {"route_data": new_route_data})

    node_labels = {
        "rag":           "📚 检索社区骑行经验...",
        "safety_supply": "🛡️ 校验补给点 & 安全评估...",
        "finalizer":     "✍️ 生成专业路书...",
    }
    node_progress = {
        "rag": 35,
        "safety_supply": 70,
        "finalizer": 100,
    }

    try:
        async for event in graph.astream(None, config):
            for node_name, output in event.items():
                label = node_labels.get(node_name, f"⚙️ {node_name}...")
                data = {
                    "node": node_name,
                    "label": label,
                    "type": "progress",
                    "progress": node_progress.get(node_name, 0),
                }

                if "final_plan_markdown" in output and output["final_plan_markdown"]:
                    data["type"] = "roadbook_ready"
                    data["markdown"] = output["final_plan_markdown"]
                    data["route"] = output.get("route_data", {})
                    data["weather"] = full_state.get("weather_info", {})
                    data["poi"] = full_state.get("poi_info", {})
                    data["safety"] = output.get("safety_warnings", [])
                    data["analysis"] = full_state.get("analysis_summary", {})

                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.05)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.post("/api/v1/stream_plan")
async def stream_plan(request: PlanRequest):
    thread_id = str(uuid.uuid4())

    async def wrapper():
        yield f"data: {json.dumps({'type': 'session', 'thread_id': thread_id})}\n\n"
        async for chunk in event_generator(request, thread_id):
            yield chunk

    return StreamingResponse(wrapper(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v1/stream_finalize")
async def stream_finalize(request: FinalizeRequest):
    return StreamingResponse(
        finalize_generator(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.get("/")
async def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import os
    import uvicorn

    def choose_port(preferred: int) -> int:
        for port in [preferred, *range(preferred + 1, preferred + 10)]:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        return preferred

    reload_enabled = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    host = os.getenv("APP_HOST", "127.0.0.1")
    preferred_port = int(os.getenv("APP_PORT", "8000"))
    port = choose_port(preferred_port)
    if port != preferred_port:
        print(f"Port {preferred_port} is occupied, switched to http://127.0.0.1:{port}/")
    else:
        print(f"CycleScope running at http://127.0.0.1:{port}/")
    target = "main:app" if reload_enabled else app
    uvicorn.run(target, host=host, port=port, reload=reload_enabled)
