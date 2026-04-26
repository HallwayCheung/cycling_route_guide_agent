"""
Nationwide cycling planning workflow nodes.
Focus:
1. Understand colloquial cycling intents and constraints.
2. Resolve nationwide places/regions more reliably.
3. Score routes using real geometry, elevation, road context, and timing goals.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from datetime import datetime, timedelta

import httpx

from .cache import get_cached_json, set_cached_json
from .llm import get_llm
from .mcp_client import CyclingMcpClient
from .route_knowledge import build_preset_variants, choose_waypoints, detect_route_preset, get_route_preset, lookup_anchor_point, normalize_route_text
from .state import GraphState

llm = get_llm()
mcp_client = CyclingMcpClient()

KNOWN_POINT_ALIASES = {
    "山东科技大学青岛": ("山东科技大学青岛校区", 120.1234, 36.0052),
    "山东科技大学": ("山东科技大学青岛校区", 120.1234, 36.0052),
    "山科大青岛": ("山东科技大学青岛校区", 120.1234, 36.0052),
    "中国石油大学华东唐岛湾": ("中国石油大学华东唐岛湾校区", 120.1728, 35.9444),
    "中国石油大学华东": ("中国石油大学华东唐岛湾校区", 120.1728, 35.9444),
    "石油大学唐岛湾": ("中国石油大学华东唐岛湾校区", 120.1728, 35.9444),
    "星光岛": ("星光岛", 120.1920, 35.8990),
    "东方影都星光岛": ("星光岛", 120.1920, 35.8990),
    "大珠山": ("大珠山风景区", 120.0548, 35.7556),
    "大珠山风景区": ("大珠山风景区", 120.0548, 35.7556),
    "石门寺": ("大珠山石门寺游客中心", 120.0358, 35.7426),
    "珠山秀谷": ("珠山秀谷景区", 120.0768, 35.7762),
    "东方绿舟": ("东方绿舟", 121.0152, 31.1074),
    "朱家角": ("朱家角古镇", 121.0480, 31.1075),
    "朱家角古镇": ("朱家角古镇", 121.0480, 31.1075),
    "淀山湖": ("淀山湖", 120.9700, 31.0950),
    "淀山湖大道": ("淀山湖大道", 121.0718, 31.1333),
    "环湖大道": ("环湖大道", 120.9715, 31.0820),
    "金泽": ("金泽古镇", 120.9138, 31.0430),
    "金泽古镇": ("金泽古镇", 120.9138, 31.0430),
    "练塘": ("练塘古镇", 121.0070, 30.9997),
    "练塘古镇": ("练塘古镇", 121.0070, 30.9997),
    "松江大学城": ("松江大学城", 121.2155, 31.0538),
    "佘山": ("佘山国家森林公园", 121.1930, 31.0961),
    "佘山国家森林公园": ("佘山国家森林公园", 121.1930, 31.0961),
    "辰山植物园": ("辰山植物园", 121.1794, 31.0833),
}

KNOWN_REGION_ALIASES = {
    "上海": {
        "name": "上海市",
        "center": {"lat": 31.2304, "lon": 121.4737},
        "bbox": [30.67, 31.88, 120.85, 122.12],
    },
    "上海市": {
        "name": "上海市",
        "center": {"lat": 31.2304, "lon": 121.4737},
        "bbox": [30.67, 31.88, 120.85, 122.12],
    },
    "青浦": {
        "name": "上海市青浦区",
        "center": {"lat": 31.1500, "lon": 121.1242},
        "bbox": [30.95, 31.30, 120.85, 121.35],
    },
    "青浦区": {
        "name": "上海市青浦区",
        "center": {"lat": 31.1500, "lon": 121.1242},
        "bbox": [30.95, 31.30, 120.85, 121.35],
    },
    "上海市青浦区淀山湖": {
        "name": "上海市青浦区淀山湖",
        "center": {"lat": 31.0950, "lon": 120.9700},
        "bbox": [31.02, 31.17, 120.87, 121.08],
    },
    "山东省青岛市黄岛区大珠山": {
        "name": "山东省青岛市黄岛区大珠山",
        "center": {"lat": 35.7556, "lon": 120.0548},
        "bbox": [35.68, 35.82, 119.98, 120.11],
    },
}


def _cache_key(prefix: str, payload: str) -> str:
    return f"{prefix}:{payload}"


def _safe_json_load(raw: str, fallback: dict) -> dict:
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)
    except Exception:
        return fallback


def _call_llm_json(prompt: str, fallback: dict) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        response = llm.invoke(
            [
                SystemMessage(content="Return JSON only. Do not include markdown fences."),
                HumanMessage(content=prompt),
            ]
        )
        return _safe_json_load(response.content, fallback)
    except Exception:
        return fallback


DEMAND_PARSE_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_cycling_demand",
        "description": "Parse a natural-language cycling request into executable route planning arguments.",
        "parameters": {
            "type": "object",
            "properties": {
                "route_mode": {
                    "type": "string",
                    "enum": ["point_to_point", "round_trip", "loop"],
                    "description": "Route mode: point-to-point, out-and-back, or loop.",
                },
                "region": {"type": "string", "description": "City, district, scenic region, or empty string."},
                "target_distance_km": {
                    "type": ["number", "null"],
                    "description": "Target ride distance in kilometers if specified.",
                },
                "route_alias": {"type": "string", "description": "Known route name, such as 环大珠山."},
                "origin": {"type": "string", "description": "Real searchable origin place name."},
                "destination": {"type": "string", "description": "Real searchable destination or turnaround place name."},
                "waypoints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Real searchable intermediate places.",
                },
                "route_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered route skeleton including origin and destination.",
                },
                "return_to_origin": {"type": "boolean"},
                "must_avoid": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Road or safety constraints, not places.",
                },
                "notes": {"type": "string", "description": "Very short route intent note."},
            },
            "required": [
                "route_mode",
                "region",
                "target_distance_km",
                "route_alias",
                "origin",
                "destination",
                "waypoints",
                "route_points",
                "return_to_origin",
                "must_avoid",
                "notes",
            ],
            "additionalProperties": False,
        },
    },
}


def _call_llm_tool_json(prompt: str, tool_schema: dict, tool_name: str, fallback: dict) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        tool_llm = llm.bind(
            tools=[tool_schema],
            tool_choice={"type": "function", "function": {"name": tool_name}},
        )
        response = tool_llm.invoke(
            [
                SystemMessage(content="Use the provided tool. Do not answer in free text."),
                HumanMessage(content=prompt),
            ]
        )
        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            args = tool_calls[0].get("args", {})
            return args if isinstance(args, dict) else fallback
        raw_calls = (getattr(response, "additional_kwargs", {}) or {}).get("tool_calls", [])
        if raw_calls:
            raw_args = raw_calls[0].get("function", {}).get("arguments", "{}")
            return _safe_json_load(raw_args, fallback)
        return _safe_json_load(getattr(response, "content", "") or "", fallback)
    except Exception:
        return fallback


async def _call_mcp_json(tool_name: str, arguments: dict) -> dict | None:
    try:
        raw = await mcp_client.call_tool(tool_name, arguments)
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _extract_constraints(intent: str) -> dict:
    text = normalize_route_text(intent)
    round_trip = any(token in text for token in ["再返回", "返回起点", "回到起点", "回原点", "往返", "折返", "再回来", "回来"])

    order_preference = None
    if "先多爬升后平路" in text or ("先爬升" in text and "后平路" in text):
        order_preference = "climb_then_flat"
    elif "先平路后爬升" in text or ("先平路" in text and "后爬升" in text):
        order_preference = "flat_then_climb"

    bike_lane_mode = "prefer_bike_lane"

    traffic_mode = "neutral"
    if any(token in text for token in ["避开快速路", "避开主路", "少车", "不走大车", "避开机动车"]):
        traffic_mode = "avoid_motor_traffic"

    scenic_goal = None
    if any(token in text for token in ["日落", "落日", "晚霞"]):
        scenic_goal = "sunset"
    elif "日出" in text:
        scenic_goal = "sunrise"

    return {
        "is_loop": any(token in text for token in ["环", "一圈", "绕圈", "环线"]),
        "round_trip": round_trip,
        "wants_weekend": "周末" in text,
        "order_preference": order_preference,
        "bike_lane_mode": bike_lane_mode,
        "hard_avoid_highways": True,
        "traffic_mode": traffic_mode,
        "scenic_goal": scenic_goal,
        "wants_sunset": scenic_goal == "sunset",
        "wants_sunrise": scenic_goal == "sunrise",
        "surface_preference": "asphalt" if any(token in text for token in ["铺装", "公路车", "柏油"]) else None,
        "training_goal": "climb" if "爬升" in text or "拉练" in text else None,
    }


def _extract_target_distance_km(intent: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|KM|公里|千米)", intent or "")
    if not match:
        return None
    try:
        value = float(match.group(1))
    except Exception:
        return None
    return value if 1 <= value <= 600 else None


def _clean_route_phrase(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip(" ，。；;,:：")
    cleaned = re.sub(r"^(请|帮我|想要|我想|我想要|重新规划|规划一下|骑车|骑行|路线|从|到|去|前往)+", "", cleaned).strip(" ，。；;,:：")
    cleaned = re.sub(r"(骑车|骑行|路线规划|重新规划|一下)$", "", cleaned).strip(" ，。；;,:：")
    return cleaned


def _sanitize_place_name(text: str) -> str:
    cleaned = _clean_route_phrase(text)
    cleaned = re.sub(r"^(这?周末|周末|今天|明天|晚上|下午|上午|早上)?(想|我想|骑车|骑行|出发)?", "", cleaned).strip(" ，。；;,:：")
    cleaned = re.sub(r"(看日落|看落日|看晚霞|看日出|拍照|顺便|再返回|返回|往返|折返|回来|后返回|然后返回).*$", "", cleaned).strip(" ，。；;,:：")
    cleaned = re.sub(r"(尽量|最好|希望|要求|不要|避开|优先).*$", "", cleaned).strip(" ，。；;,:：")
    return cleaned


def _split_waypoint_text(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[\\/／|｜,，;；、\n]+", text)
    result = []
    for part in parts:
        cleaned = _sanitize_place_name(part)
        if cleaned:
            result.append(cleaned)
    return result[:6]


def _extract_explicit_route_points(intent: str) -> dict:
    text = (intent or "").strip()
    result = {"origin": "", "destination": "", "waypoints": [], "mode": ""}
    if not text:
        return result

    origin_match = re.search(r"起点[：:]\s*(.+?)(?=\s*(终点|目的地|途经点|途径点|附加要求|补充要求)[：:]|$)", text, re.S)
    destination_match = re.search(r"(终点|目的地)[：:]\s*(.+?)(?=\s*(起点|途经点|途径点|附加要求|补充要求)[：:]|$)", text, re.S)
    waypoint_match = re.search(r"(途经点|途径点)[：:]\s*(.+?)(?=\s*(起点|终点|目的地|附加要求|补充要求)[：:]|$)", text, re.S)

    if origin_match:
        result["origin"] = _sanitize_place_name(origin_match.group(1))
    if destination_match:
        result["destination"] = _sanitize_place_name(destination_match.group(2))
    if waypoint_match:
        result["waypoints"] = _split_waypoint_text(waypoint_match.group(2))

    if result["origin"] or result["destination"]:
        result["mode"] = "structured_fields"
        return result

    from_to_match = re.search(
        r"(?:从|由)\s*(.+?)\s*(?:到|去|前往)\s*(.+?)(?=(?:，|。|,|\.|；|;|并且|然后|再|途经|经过|路过|要求|不要|优先|尽量|最好|$))",
        text,
        re.S,
    )
    if from_to_match:
        result["origin"] = _sanitize_place_name(from_to_match.group(1))
        result["destination"] = _sanitize_place_name(from_to_match.group(2))
        result["mode"] = "from_to"

    if not result["origin"] or not result["destination"]:
        simple_to_match = re.search(
            r"(.+?)\s*(?:到|去|前往)\s*(.+?)(?=(?:，|。|,|\.|；|;|并且|然后|再|途经|经过|路过|要求|不要|优先|尽量|最好|$))",
            text,
            re.S,
        )
        if simple_to_match:
            possible_origin = _sanitize_place_name(simple_to_match.group(1))
            possible_destination = _sanitize_place_name(simple_to_match.group(2))
            if possible_origin and possible_destination and not any(token in possible_origin for token in ["环", "一圈", "绕圈"]):
                result["origin"] = possible_origin
                result["destination"] = possible_destination
                result["mode"] = "simple_to"

    pass_match = re.search(r"(?:途经|经过|路过)(?!点)\s*(.+?)(?=(?:，|。|,|\.|；|;|并且|然后|再|要求|不要|优先|尽量|最好|$))", text, re.S)
    if pass_match:
        result["waypoints"] = _split_waypoint_text(pass_match.group(1))

    return result


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _parse_coord_string(coord_string: str) -> tuple[float, float]:
    lon, lat = map(float, coord_string.split(","))
    return lon, lat


def _format_coord(lon: float, lat: float) -> str:
    return f"{lon:.6f},{lat:.6f}"


def _parse_literal_coord(query: str) -> tuple[float, float] | None:
    if not query:
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", query)
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    if -180 <= lon <= 180 and -90 <= lat <= 90:
        return lon, lat
    return None


def _lookup_known_point(query: str, region_info: dict | None = None) -> dict | None:
    normalized = normalize_route_text(query)
    region_text = normalize_route_text((region_info or {}).get("name", ""))
    for alias, (name, lon, lat) in KNOWN_POINT_ALIASES.items():
        alias_text = normalize_route_text(alias)
        if alias_text and (alias_text in normalized or normalized in alias_text):
            if alias_text in {"山东科技大学", "山科大青岛"} and region_text and "青岛" not in region_text and "黄岛" not in region_text:
                continue
            return {
                "name": name,
                "lat": lat,
                "lon": lon,
                "coord": _format_coord(lon, lat),
            }
    return None


def _dedupe_named_points(points: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for point in points:
        key = (round(float(point["lat"]), 5), round(float(point["lon"]), 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(point)
    return unique


def _sample_geometry_points(geometry: dict, limit: int = 8) -> list[tuple[float, float]]:
    coords = geometry.get("coordinates", []) if isinstance(geometry, dict) else []
    if not coords:
        return []
    if len(coords) <= limit:
        return [(float(c[1]), float(c[0])) for c in coords]
    step = max(1, len(coords) // limit)
    sampled = [coords[i] for i in range(0, len(coords), step)][:limit]
    if sampled[-1] != coords[-1]:
        sampled[-1] = coords[-1]
    return [(float(c[1]), float(c[0])) for c in sampled]


async def _search_nominatim(query: str, limit: int = 5) -> list[dict]:
    if not query:
        return []
    key = _cache_key("nominatim", f"{query}|{limit}")
    cached = get_cached_json(key)
    if cached is not None:
        return cached
    url = (
        "https://nominatim.openstreetmap.org/search?"
        f"q={urllib.parse.quote(query)}&format=jsonv2&addressdetails=1"
        f"&limit={limit}&countrycodes=cn"
    )
    async with httpx.AsyncClient(
        timeout=12.0,
        headers={"User-Agent": "CyclingAgent/2.0"},
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            payload = data if isinstance(data, list) else []
            set_cached_json(key, payload, ttl_seconds=60 * 60 * 24 * 14)
            return payload
        except Exception:
            return get_cached_json(key, allow_stale=True) or []


async def _resolve_region(region_hint: str, intent: str) -> dict:
    normalized_region = normalize_route_text(region_hint)
    normalized_intent = normalize_route_text(intent)
    for alias, region in sorted(KNOWN_REGION_ALIASES.items(), key=lambda item: len(normalize_route_text(item[0])), reverse=True):
        alias_text = normalize_route_text(alias)
        if alias_text and (alias_text in normalized_region or alias_text in normalized_intent):
            return dict(region)

    candidates = []
    search_terms = []
    if region_hint:
        search_terms.append(region_hint)
    llm_guess = _call_llm_json(
        f"""
用户骑行需求："{intent}"
请从中提取最适合做地图定位的区域名，优先输出到区县/城市级。
返回 JSON：
{{
  "region_queries": ["区域1", "区域2"]
}}
""",
        {"region_queries": []},
    )
    search_terms.extend(llm_guess.get("region_queries", []))

    deduped = []
    for term in search_terms:
        if term and term not in deduped:
            deduped.append(term)

    for term in deduped[:3]:
        results = await _search_nominatim(term, limit=3)
        if results:
            candidates.extend(results)

    if candidates:
        best = max(candidates, key=lambda c: _score_candidate(c, None, region_hint or intent))
        lat = float(best["lat"])
        lon = float(best["lon"])
        bbox = [float(v) for v in best.get("boundingbox", [lat, lat, lon, lon])]
        return {
            "name": best.get("display_name", region_hint or intent),
            "center": {"lat": lat, "lon": lon},
            "bbox": bbox,
        }

    return {
        "name": region_hint or "中国",
        "center": {"lat": 35.8617, "lon": 104.1954},
        "bbox": [17.0, 54.0, 73.0, 135.0],
    }


def _score_candidate(candidate: dict, region_info: dict | None, query: str | None = None) -> float:
    score = float(candidate.get("importance", 0))
    if query:
        query_text = normalize_route_text(query)
        display_text = normalize_route_text(candidate.get("display_name", ""))
        candidate_type = str(candidate.get("type", "")).lower()
        candidate_class = str(candidate.get("class", "")).lower()
        address_type = str(candidate.get("addresstype", "")).lower()
        is_admin_area = (
            candidate_class == "boundary"
            or candidate_type in {"administrative", "province", "city", "county"}
            or address_type in {"country", "state", "province", "city", "county", "municipality"}
        )
        is_route_like = candidate_class in {"highway", "railway"} or candidate_type in {
            "motorway",
            "trunk",
            "primary",
            "secondary",
            "tertiary",
            "residential",
            "road",
        }
        wants_specific_place = any(
            keyword in query_text
            for keyword in ["大学", "学院", "公园", "景区", "广场", "车站", "码头", "游客中心", "村", "湾", "岛", "山", "古镇", "植物园"]
        )
        if query_text and query_text in display_text:
            score += 24 + min(12, len(query_text) / 2)

        token_candidates = [
            token
            for token in re.split(r"[\s,/]+", query)
            if token
            and token
            not in {
                "中国",
                "山东省",
                "江苏省",
                "浙江省",
                "湖北省",
                "云南省",
                "上海市",
                "青岛市",
                "黄岛区",
                "青浦区",
                "松江区",
                "杭州市",
                "武汉市",
                "南京市",
                "昆明市",
            }
        ]
        matched_tokens = 0
        for token in token_candidates:
            token_text = normalize_route_text(token)
            if len(token_text) >= 2 and token_text in display_text:
                score += 8
                matched_tokens += 1
        strong_tokens = [
            token
            for token in token_candidates
            if len(normalize_route_text(token)) >= 3
            and token
            not in {
                "山东",
                "山东省",
                "江苏",
                "江苏省",
                "浙江",
                "浙江省",
                "湖北",
                "湖北省",
                "云南",
                "云南省",
                "上海",
                "上海市",
                "青岛",
                "青岛市",
                "黄岛",
                "黄岛区",
                "青浦",
                "青浦区",
                "松江",
                "松江区",
            }
        ]
        if strong_tokens and matched_tokens == 0:
            score -= 45
        if is_admin_area and wants_specific_place:
            score -= 35
        if is_route_like and wants_specific_place and not any(keyword in query_text for keyword in ["路", "大道", "绿道", "环湖"]):
            score -= 22
        if any(keyword in display_text for keyword in ["高速公路", "高架", "快速路", "立交"]):
            score -= 30

    if not region_info:
        return score
    center = region_info.get("center", {})
    lat = float(candidate.get("lat", 0))
    lon = float(candidate.get("lon", 0))
    dist = _haversine_km(center.get("lat", lat), center.get("lon", lon), lat, lon)
    score += max(0.0, 18.0 - min(dist, 18.0))
    if dist > 80:
        score -= min(60.0, (dist - 80) / 4)
    bbox = region_info.get("bbox") or []
    if len(bbox) == 4:
        south, north, west, east = bbox
        if south <= lat <= north and west <= lon <= east:
            score += 14
        else:
            score -= 18
    return score


async def _resolve_point(query: str, region_info: dict | None) -> dict | None:
    if not query:
        return None
    literal = _parse_literal_coord(query)
    if literal:
        lon, lat = literal
        return {
            "name": f"地图点选({lat:.5f},{lon:.5f})",
            "lat": lat,
            "lon": lon,
            "coord": _format_coord(lon, lat),
        }
    known_point = _lookup_known_point(query, region_info)
    if known_point:
        return known_point

    region_name = (region_info or {}).get("name", "")
    search_variants = []
    if region_name and region_name not in query:
        search_variants.append(f"{query} {region_name}")
    search_variants.append(query)
    search_variants.extend(
        [
            part
            for part in re.split(r"[\s/]+", query)
            if len(part.strip()) >= 2
            and normalize_route_text(part) not in {"中国", "山东", "山东省", "青岛", "青岛市", "黄岛", "黄岛区"}
        ]
    )

    candidates: list[dict] = []
    deduped_terms = []
    for term in search_variants:
        if term and term not in deduped_terms:
            deduped_terms.append(term)

    for term in deduped_terms[:4]:
        candidates.extend(await _search_nominatim(term, limit=6))

    if not candidates:
        return None

    best = max(candidates, key=lambda c: _score_candidate(c, region_info, query))
    if _score_candidate(best, region_info, query) < -10:
        return None
    return {
        "name": best.get("display_name", query),
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
        "coord": _format_coord(float(best["lon"]), float(best["lat"])),
    }


async def _fetch_route(coords_string: str, allow_driving_fallback: bool = True) -> dict:
    key = _cache_key("route", f"{coords_string}|allow_driving={int(bool(allow_driving_fallback))}")
    cached = get_cached_json(key)
    if cached is not None:
        return cached

    mcp_payload = await _call_mcp_json(
        "get_cycling_route",
        {
            "coords_sequence": coords_string,
            "allow_driving_fallback": bool(allow_driving_fallback),
        },
    )
    if mcp_payload and mcp_payload.get("routes"):
        mcp_payload["_source"] = "mcp:get_cycling_route"
        set_cached_json(key, mcp_payload, ttl_seconds=60 * 60 * 24)
        return mcp_payload

    async with httpx.AsyncClient(timeout=30.0) as client:
        last_error = None
        profiles = ["bicycle"] + (["driving"] if allow_driving_fallback else [])
        for profile in profiles:
            url = (
                f"http://router.project-osrm.org/route/v1/{profile}/"
                + coords_string
                + "?overview=full&geometries=geojson&alternatives=3&steps=true&annotations=false"
            )
            try:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                if payload.get("routes"):
                    payload["_profile"] = profile
                    set_cached_json(key, payload, ttl_seconds=60 * 60 * 24)
                    return payload
                last_error = f"{profile}: empty routes"
            except Exception as exc:
                last_error = str(exc)
                continue
    return get_cached_json(key, allow_stale=True) or {"routes": [], "error": last_error or "no route"}


async def _fetch_weather(lat: float, lon: float) -> dict:
    key = _cache_key("weather", f"{lat:.4f},{lon:.4f}")
    cached = get_cached_json(key)
    if cached is not None:
        return cached

    mcp_payload = await _call_mcp_json("get_weather", {"lat": lat, "lon": lon})
    if mcp_payload and (mcp_payload.get("current") or mcp_payload.get("daily")):
        mcp_payload["_source"] = "mcp:get_weather"
        set_cached_json(key, mcp_payload, ttl_seconds=60 * 30)
        return mcp_payload

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,wind_speed_10m,wind_direction_10m,precipitation"
        "&daily=sunrise,sunset"
        "&timezone=auto&forecast_days=2"
    )
    async with httpx.AsyncClient(timeout=12.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            set_cached_json(key, payload, ttl_seconds=60 * 30)
            return payload
        except Exception as exc:
            return get_cached_json(key, allow_stale=True) or {"current": {}, "error": str(exc)}


async def _run_overpass_query(query: str, timeout: float = 18.0) -> list[dict]:
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    headers = {
        "User-Agent": "CyclingAgent/2.0",
        "Accept": "application/json,text/plain,*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }
    last_error = None
    async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
        for endpoint in endpoints:
            try:
                response = await client.post(endpoint, content=f"data={urllib.parse.quote(query)}")
                response.raise_for_status()
                return response.json().get("elements", [])
            except Exception as exc:
                last_error = exc
                continue
    if last_error:
        raise last_error
    return []


async def _fetch_pois(lat: float, lon: float, radius: int = 2500) -> dict:
    key = _cache_key("pois", f"{lat:.4f},{lon:.4f}|{radius}")
    cached = get_cached_json(key)
    if cached is not None:
        return cached

    mcp_payload = await _call_mcp_json("search_pois_osm", {"lat": lat, "lon": lon, "radius": radius})
    if mcp_payload and isinstance(mcp_payload.get("elements"), list):
        mcp_payload["_source"] = "mcp:search_pois_osm"
        set_cached_json(key, mcp_payload, ttl_seconds=60 * 60 * 8)
        return mcp_payload

    query = f"""
    [out:json][timeout:18];
    (
      node(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|convenience|bicycle_parking|drinking_water|toilets|pharmacy|hospital|fuel"];
      node(around:{radius},{lat},{lon})["shop"~"bicycle|sports|supermarket"];
      node(around:{radius},{lat},{lon})["tourism"~"viewpoint|attraction"];
      node(around:{radius},{lat},{lon})["leisure"~"park|fitness_station"];
    );
    out 40;
    """
    try:
        payload = {"elements": await _run_overpass_query(query, timeout=18.0)}
        set_cached_json(key, payload, ttl_seconds=60 * 60 * 8)
        return payload
    except Exception as exc:
        return get_cached_json(key, allow_stale=True) or {"elements": [], "error": str(exc)}


async def _fetch_route_landmarks(region_info: dict) -> list[dict]:
    center = region_info.get("center", {})
    lat = center.get("lat")
    lon = center.get("lon")
    if lat is None or lon is None:
        return []
    key = _cache_key("landmarks", f"{lat:.4f},{lon:.4f}")
    cached = get_cached_json(key)
    if cached is not None:
        return cached
    query = f"""
    [out:json][timeout:18];
    (
      node(around:18000,{lat},{lon})["tourism"~"viewpoint|attraction"];
      node(around:18000,{lat},{lon})["leisure"~"park"];
      node(around:18000,{lat},{lon})["amenity"="parking"];
      node(around:18000,{lat},{lon})["natural"~"peak|bay|beach"];
    );
    out center 60;
    """
    try:
        payload = await _run_overpass_query(query, timeout=20.0)
        set_cached_json(key, payload, ttl_seconds=60 * 60 * 24 * 3)
        return payload
    except Exception:
        return get_cached_json(key, allow_stale=True) or []


async def _fetch_elevation_samples(points: list[tuple[float, float]]) -> list[float]:
    if not points:
        return []
    key = _cache_key(
        "elevation",
        "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points),
    )
    cached = get_cached_json(key)
    if cached is not None:
        return cached
    mcp_payload = await _call_mcp_json(
        "get_elevation",
        {"points": [{"lat": lat, "lon": lon} for lat, lon in points]},
    )
    if mcp_payload and isinstance(mcp_payload.get("results"), list):
        elevations = [float(item.get("elevation", 0)) for item in mcp_payload.get("results", [])]
        if len(elevations) == len(points):
            set_cached_json(key, elevations, ttl_seconds=60 * 60 * 24 * 7)
            return elevations

    chunks = [points[i : i + 50] for i in range(0, len(points), 50)]
    elevations: list[float] = []
    async with httpx.AsyncClient(timeout=20.0) as client:
        for chunk in chunks:
            locations = "|".join(f"{lat},{lon}" for lat, lon in chunk)
            url = f"https://api.open-elevation.com/api/v1/lookup?locations={locations}"
            try:
                response = await client.get(url)
                response.raise_for_status()
                elevations.extend([float(item.get("elevation", 0)) for item in response.json().get("results", [])])
            except Exception:
                elevations.extend([0.0] * len(chunk))
    set_cached_json(key, elevations, ttl_seconds=60 * 60 * 24 * 7)
    return elevations


async def _fetch_lane_context(geometry: dict) -> dict:
    points = _sample_geometry_points(geometry, limit=6)
    if not points:
        return {
            "cycleway_hits": 0,
            "bike_friendly_hits": 0,
            "primary_hits": 0,
            "motorway_hits": 0,
            "forbidden_hits": 0,
            "named_cycleways": [],
            "bike_friendly_names": [],
        }
    key = _cache_key(
        "lane_context",
        "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points),
    )
    cached = get_cached_json(key)
    if cached is not None:
        return cached

    around_queries = "\n".join(
        [
            f'way["highway"="cycleway"](around:120,{lat},{lon});'
            f'way["cycleway"~"lane|track"](around:120,{lat},{lon});'
            f'way["highway"~"residential|living_street|service|tertiary|secondary|unclassified"](around:120,{lat},{lon});'
            f'way["highway"~"primary|primary_link"](around:120,{lat},{lon});'
            f'way["highway"~"trunk|trunk_link|motorway|motorway_link"](around:120,{lat},{lon});'
            for lat, lon in points
        ]
    )
    query = f"""
    [out:json][timeout:18];
    (
      {around_queries}
    );
    out tags;
    """
    try:
        elements = await _run_overpass_query(query, timeout=20.0)
    except Exception:
        elements = []

    cycleway_hits = 0
    bike_friendly_hits = 0
    primary_hits = 0
    motorway_hits = 0
    fast_road_hits = 0
    forbidden_hits = 0
    named_cycleways: list[str] = []
    bike_friendly_names: list[str] = []
    for el in elements:
        tags = el.get("tags", {})
        highway = tags.get("highway")
        if highway == "cycleway" or tags.get("cycleway") in {"lane", "track"}:
            cycleway_hits += 1
            if tags.get("name"):
                named_cycleways.append(tags["name"])
        if highway in {"residential", "living_street", "service", "tertiary", "secondary", "unclassified"}:
            bike_friendly_hits += 1
            if tags.get("name"):
                bike_friendly_names.append(tags["name"])
        if highway in {"primary", "primary_link"}:
            primary_hits += 1
        if highway in {"trunk", "trunk_link"}:
            fast_road_hits += 1
        if highway in {"motorway", "motorway_link"}:
            motorway_hits += 1
            forbidden_hits += 1

    payload = {
        "cycleway_hits": cycleway_hits,
        "bike_friendly_hits": bike_friendly_hits,
        "primary_hits": primary_hits,
        "motorway_hits": motorway_hits,
        "fast_road_hits": fast_road_hits,
        "forbidden_hits": forbidden_hits,
        "named_cycleways": sorted(list(set(named_cycleways)))[:8],
        "bike_friendly_names": sorted(list(set(bike_friendly_names)))[:8],
    }
    set_cached_json(key, payload, ttl_seconds=60 * 60 * 24 * 3)
    return payload


def _fallback_pois_from_preset(route_preset_key: str | None) -> dict:
    preset = get_route_preset(route_preset_key)
    if not preset or not preset.fallback_pois:
        return {"elements": [], "error": ""}
    elements = []
    for index, poi in enumerate(preset.fallback_pois):
        elements.append(
            {
                "id": index + 1,
                "lat": poi.lat,
                "lon": poi.lon,
                "tags": {
                    "name": poi.name,
                    poi.tag_key: poi.tag_value,
                },
            }
        )
    return {"elements": elements, "error": ""}


async def _fetch_route_corridor_pois(routes: list[dict], radius: int = 900) -> dict:
    samples: list[tuple[float, float]] = []
    for route in routes[:3]:
        for lat, lon in _sample_geometry_points(route.get("geometry", {}), limit=8):
            rounded = (round(lat, 4), round(lon, 4))
            if rounded not in samples:
                samples.append(rounded)

    if not samples:
        return {"elements": [], "error": ""}

    key = _cache_key("corridor_pois", "|".join(f"{lat:.4f},{lon:.4f}" for lat, lon in samples))
    cached = get_cached_json(key)
    if cached is not None:
        return cached

    around_queries = "\n".join(
        [
            f'node(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|convenience|bicycle_parking|drinking_water|toilets|pharmacy|hospital|fuel"];'
            f'node(around:{radius},{lat},{lon})["shop"~"bicycle|sports|supermarket"];'
            f'node(around:{radius},{lat},{lon})["tourism"~"viewpoint|attraction"];'
            f'node(around:{radius},{lat},{lon})["leisure"~"park|fitness_station"];'
            for lat, lon in samples[:18]
        ]
    )
    query = f"""
    [out:json][timeout:20];
    (
      {around_queries}
    );
    out center 120;
    """
    try:
        elements = await _run_overpass_query(query, timeout=20.0)
        deduped = []
        seen = set()
        for item in elements:
            lat = item.get("lat", item.get("center", {}).get("lat"))
            lon = item.get("lon", item.get("center", {}).get("lon"))
            if lat is None or lon is None:
                continue
            key_item = (
                round(float(lat), 5),
                round(float(lon), 5),
                (item.get("tags", {}) or {}).get("name", ""),
                (item.get("tags", {}) or {}).get("amenity", ""),
                (item.get("tags", {}) or {}).get("tourism", ""),
                (item.get("tags", {}) or {}).get("shop", ""),
            )
            if key_item in seen:
                continue
            seen.add(key_item)
            item["lat"] = float(lat)
            item["lon"] = float(lon)
            deduped.append(item)
        payload = {"elements": deduped[:120], "error": ""}
        set_cached_json(key, payload, ttl_seconds=60 * 60 * 8)
        return payload
    except Exception as exc:
        return get_cached_json(key, allow_stale=True) or {"elements": [], "error": str(exc)}


def _select_loop_points(landmarks: list[dict], region_info: dict, order_preference: str | None) -> list[dict]:
    center = region_info.get("center", {})
    c_lat = center.get("lat", 0.0)
    c_lon = center.get("lon", 0.0)
    scored = []
    for item in landmarks:
        lat = float(item.get("lat", item.get("center", {}).get("lat", c_lat)))
        lon = float(item.get("lon", item.get("center", {}).get("lon", c_lon)))
        dist = _haversine_km(c_lat, c_lon, lat, lon)
        name = item.get("tags", {}).get("name")
        if not name or dist < 2:
            continue
        eastness = lon - c_lon
        northness = lat - c_lat
        scenic_bonus = 1 if item.get("tags", {}).get("tourism") == "viewpoint" else 0
        scored.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "dist": dist,
                "eastness": eastness,
                "northness": northness,
                "score": dist + scenic_bonus,
            }
        )

    if not scored:
        return []

    east = max(scored, key=lambda x: (x["eastness"], x["score"]))
    west = min(scored, key=lambda x: (x["eastness"], -x["score"]))
    north = max(scored, key=lambda x: (x["northness"], x["score"]))
    south = min(scored, key=lambda x: (x["northness"], -x["score"]))

    ordered = [east, south, west, north]
    if order_preference == "climb_then_flat":
        ordered = sorted(ordered, key=lambda x: (-x["northness"], -x["dist"]))
    elif order_preference == "flat_then_climb":
        ordered = sorted(ordered, key=lambda x: (x["northness"], x["dist"]))

    seen = set()
    result = []
    for item in ordered:
        key = (round(item["lat"], 4), round(item["lon"], 4))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result[:4]


def _compute_elevation_gain(elevations: list[float]) -> float:
    gain = 0.0
    for prev, curr in zip(elevations, elevations[1:]):
        if curr > prev:
            gain += curr - prev
    return gain


def _estimate_arrival_plan(
    distance_km: float,
    avg_speed_kmh: float,
    weather: dict,
    constraints: dict,
) -> dict:
    daily = weather.get("daily", {})
    sunset_values = daily.get("sunset", [])
    sunrise_values = daily.get("sunrise", [])
    scenic_goal = constraints.get("scenic_goal")
    result = {}
    if scenic_goal == "sunset" and sunset_values:
        sunset_time = sunset_values[0][-5:]
        ride_minutes = int((distance_km / max(avg_speed_kmh, 10)) * 60)
        target = datetime.strptime(sunset_time, "%H:%M") - timedelta(minutes=max(40, min(ride_minutes // 3, 70)))
        depart = target - timedelta(minutes=ride_minutes)
        result = {
            "target_time": target.strftime("%H:%M"),
            "depart_time": depart.strftime("%H:%M"),
            "goal": "sunset",
            "reference_time": sunset_time,
        }
    elif scenic_goal == "sunrise" and sunrise_values:
        sunrise_time = sunrise_values[0][-5:]
        ride_minutes = int((distance_km / max(avg_speed_kmh, 10)) * 60)
        target = datetime.strptime(sunrise_time, "%H:%M") - timedelta(minutes=15)
        depart = target - timedelta(minutes=ride_minutes)
        result = {
            "target_time": target.strftime("%H:%M"),
            "depart_time": depart.strftime("%H:%M"),
            "goal": "sunrise",
            "reference_time": sunrise_time,
        }
    return result


def _build_route_brief(route_metrics: dict, route_data: dict, constraints: dict) -> str:
    bits = [
        f"{route_metrics.get('distance_km', 'N/A')} km",
        f"爬升 {route_metrics.get('climb_m', 'N/A')} m",
        f"约 {route_metrics.get('est_hours', 'N/A')} 小时",
    ]
    if route_metrics.get("is_fallback"):
        bits.append("当前为骨架回退路线")
    if constraints.get("order_preference") == "climb_then_flat":
        bits.append("按先爬后放松的节奏组织路线")
    elif constraints.get("order_preference") == "flat_then_climb":
        bits.append("按先巡航后上强度的节奏组织路线")
    if route_data.get("route_notes"):
        bits.append(route_data["route_notes"])
    return "，".join(bits)


def _maneuver_text(step: dict) -> str:
    maneuver = step.get("maneuver", {}) or {}
    road_name = step.get("name") or "无名道路"
    modifier = maneuver.get("modifier", "")
    type_name = maneuver.get("type", "continue")
    action_map = {
        "depart": "从此处出发",
        "arrive": "到达终点",
        "roundabout": "经环岛通过",
        "turn": "转向",
        "merge": "汇入前方道路",
        "fork": "在岔路处选择方向",
        "end of road": "道路尽头转向",
        "continue": "继续前进",
        "new name": "道路名称变更后继续前进",
        "notification": "留意前方道路变化",
    }
    modifier_map = {
        "left": "左转",
        "right": "右转",
        "slight left": "向左前方",
        "slight right": "向右前方",
        "sharp left": "急左转",
        "sharp right": "急右转",
        "straight": "直行",
        "uturn": "掉头",
    }
    action = action_map.get(type_name, "继续前进")
    modifier_text = modifier_map.get(modifier, "")
    if modifier_text and action == "转向":
        action = modifier_text
    elif modifier_text and action not in {"到达终点", "从此处出发"}:
        action = f"{action}后{modifier_text}"
    return f"{action}进入 {road_name}"


def _segment_route(route: dict) -> list[dict]:
    segments = []
    step_index = 1
    for leg_index, leg in enumerate(route.get("legs", []) or []):
        leg_steps = leg.get("steps", []) or []
        for step in leg_steps:
            distance_km = round(float(step.get("distance", 0)) / 1000, 1)
            if float(step.get("distance", 0) or 0) < 20:
                continue
            duration_min = max(1, round(float(step.get("duration", 0)) / 60))
            segments.append(
                {
                    "index": step_index,
                    "leg_index": leg_index,
                    "title": _maneuver_text(step),
                    "distance_km": distance_km,
                    "duration_min": duration_min,
                    "road_name": step.get("name") or "无名道路",
                    "mode": step.get("mode", "cycling"),
                    "start_location": (step.get("maneuver", {}) or {}).get("location"),
                    "geometry": (step.get("geometry", {}) or {}).get("coordinates", []),
                }
            )
            step_index += 1
    return segments


def _route_policy_snapshot(lane: dict, route: dict | None = None, avoid_keywords: list[str] | None = None) -> dict:
    cycleway_hits = int(lane.get("cycleway_hits", 0) or 0)
    bike_friendly_hits = int(lane.get("bike_friendly_hits", 0) or 0)
    primary_hits = int(lane.get("primary_hits", 0) or 0)
    fast_road_hits = int(lane.get("fast_road_hits", 0) or 0)
    forbidden_hits = int(lane.get("forbidden_hits", 0) or 0)
    segments = _segment_route(route or {})
    if cycleway_hits == 0 and bike_friendly_hits == 0 and segments:
        for segment in segments:
            road_name = segment.get("road_name") or ""
            if any(keyword in road_name for keyword in ["自行车", "骑行", "绿道"]):
                cycleway_hits += 1
            elif any(keyword in road_name for keyword in ["滨海", "景观", "公园", "山川路", "环湖", "海滨", "旅游路"]):
                bike_friendly_hits += 1
            elif any(keyword in road_name for keyword in ["大道", "中路", "路"]) and not any(keyword in road_name for keyword in ["高速", "快速路", "高架"]):
                bike_friendly_hits += 0.5
        bike_friendly_hits = int(round(bike_friendly_hits))
    route_avoid_keywords = [keyword for keyword in (avoid_keywords or []) if keyword]
    route_profile = str((route or {}).get("route_profile") or "").strip().lower()
    profile_risk_hits = 0 if route_profile in {"", "bicycle"} else 1
    hard_keyword_hits = sum(
        1
        for segment in segments
        if any(
            keyword in (segment.get("road_name") or "")
            for keyword in [
                "高速",
                "封闭",
                "禁行",
                "禁止通行",
                "收费站",
                "收费口",
                "收费广场",
                "专用通道",
                "机动车专用",
                *route_avoid_keywords,
            ]
        )
    )
    soft_keyword_hits = sum(
        1
        for segment in segments
        if any(keyword in (segment.get("road_name") or "") for keyword in ["快速路", "高架", "匝道", "隧道"])
    )

    policy_score = max(
        0,
        min(
            100,
            58
            + cycleway_hits * 14
            + bike_friendly_hits * 7
            - primary_hits * 6
            - fast_road_hits * 10
            - forbidden_hits * 45
            - hard_keyword_hits * 40
            - soft_keyword_hits * 8
            - profile_risk_hits * 8,
        ),
    )
    if forbidden_hits > 0 or hard_keyword_hits > 0:
        summary = "命中高速、封闭或明确禁行道路，已作为不可取方案处理"
    elif fast_road_hits > 0 or soft_keyword_hits > 0:
        summary = "包含快速路/高架/隧道等风险道路，已降权但保留为可选方案"
    elif profile_risk_hits > 0:
        summary = "当前未命中纯骑行路由，已用普通道路结果辅助规划，建议现场复核"
    elif cycleway_hits > 0:
        summary = "包含明确自行车道或骑行设施，优先级最高"
    elif bike_friendly_hits > 0:
        summary = "以较适合骑行的城市道路为主，可作为次优方案"
    elif primary_hits > 0:
        summary = "包含较多主干道路段，仅作为兜底参考"
    else:
        summary = "道路类型识别有限，建议现场结合导航复核"

    return {
        "policy_score": policy_score,
        "summary": summary,
        "is_compliant": (
            forbidden_hits == 0
            and hard_keyword_hits == 0
        ),
        "cycleway_hits": cycleway_hits,
        "bike_friendly_hits": bike_friendly_hits,
        "primary_hits": primary_hits,
        "fast_road_hits": fast_road_hits,
        "forbidden_hits": forbidden_hits,
        "hard_keyword_hits": hard_keyword_hits,
        "soft_keyword_hits": soft_keyword_hits,
        "profile_risk_hits": profile_risk_hits,
    }


def _road_focus_from_segments(segments: list[dict]) -> list[str]:
    names = []
    for segment in segments:
        road_name = (segment.get("road_name") or "").strip()
        if not road_name or road_name == "无名道路":
            continue
        if road_name not in names:
            names.append(road_name)
    return names[:6]


def _bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _wind_relation_label(route_bearing: float, wind_direction: float | None) -> str:
    if wind_direction is None:
        return "风况待定"
    delta = abs((route_bearing - wind_direction + 180) % 360 - 180)
    if delta <= 35:
        return "逆风段"
    if delta >= 145:
        return "顺风段"
    return "侧风段"


def _segment_anchor(segment: dict) -> tuple[float, float] | None:
    geometry = segment.get("geometry") or []
    if geometry:
        mid = geometry[len(geometry) // 2]
        return float(mid[1]), float(mid[0])
    start = segment.get("start_location") or []
    if len(start) >= 2:
        return float(start[1]), float(start[0])
    return None


def _segment_bearing(segment: dict) -> float | None:
    geometry = segment.get("geometry") or []
    if len(geometry) >= 2:
        first = geometry[0]
        last = geometry[-1]
        return _bearing_degrees(float(first[1]), float(first[0]), float(last[1]), float(last[0]))
    return None


def _poi_bucket_name(tags: dict) -> tuple[str, str] | None:
    amenity = tags.get("amenity")
    shop = tags.get("shop")
    tourism = tags.get("tourism")
    if amenity in {"restaurant", "cafe", "convenience"}:
        return "food", tags.get("name", "补给点")
    if amenity == "drinking_water":
        return "water", tags.get("name", "饮水点")
    if shop == "bicycle":
        return "repair", tags.get("name", "维修点")
    if tourism in {"viewpoint", "attraction"}:
        return "scenic", tags.get("name", "观景点")
    if amenity in {"pharmacy", "hospital"}:
        return "medical", tags.get("name", "医疗点")
    if amenity in {"toilets", "bicycle_parking"} or tags.get("leisure") in {"park", "fitness_station"}:
        return "rest", tags.get("name", "休整点")
    if shop == "supermarket":
        return "food", tags.get("name", "商超补给")
    return None


async def _enrich_segments(segments: list[dict], poi_elements: list[dict], weather: dict) -> list[dict]:
    if not segments:
        return segments

    current = weather.get("current", {}) if isinstance(weather, dict) else {}
    wind_direction = current.get("wind_direction_10m")
    enriched = []

    for segment in segments:
        segment_copy = dict(segment)
        anchor = _segment_anchor(segment_copy)
        nearby_names: dict[str, list[str]] = {"food": [], "water": [], "repair": [], "scenic": [], "medical": [], "rest": []}
        if anchor:
            lat, lon = anchor
            for element in poi_elements[:80]:
                el_lat = element.get("lat")
                el_lon = element.get("lon")
                if el_lat is None or el_lon is None:
                    continue
                if _haversine_km(lat, lon, float(el_lat), float(el_lon)) > 1.6:
                    continue
                bucket = _poi_bucket_name(element.get("tags", {}) or {})
                if not bucket:
                    continue
                key, name = bucket
                if name not in nearby_names[key]:
                    nearby_names[key].append(name)

        geometry = segment_copy.get("geometry") or []
        climb_points = [(float(pt[1]), float(pt[0])) for pt in geometry[:8]] if geometry else []
        elevations = await _fetch_elevation_samples(climb_points) if climb_points else []
        climb_m = round(_compute_elevation_gain(elevations)) if elevations else 0

        bearing = _segment_bearing(segment_copy)
        wind_label = _wind_relation_label(bearing, float(wind_direction)) if bearing is not None and wind_direction is not None else "风况待定"
        risk_flags = []
        road_name = segment_copy.get("road_name") or ""
        if any(keyword in road_name for keyword in ["高速", "快速路", "高架", "隧道"]):
            risk_flags.append("注意道路风险")
        if "左转" in segment_copy.get("title", "") or "右转" in segment_copy.get("title", ""):
            risk_flags.append("注意转向口")

        supply_bits = []
        if nearby_names["food"]:
            supply_bits.append(f"餐饮 {nearby_names['food'][0]}")
        if nearby_names["water"]:
            supply_bits.append(f"饮水 {nearby_names['water'][0]}")
        if nearby_names["repair"]:
            supply_bits.append(f"维修 {nearby_names['repair'][0]}")
        if nearby_names["rest"]:
            supply_bits.append(f"休整 {nearby_names['rest'][0]}")

        segment_copy["climb_m"] = climb_m
        segment_copy["wind_label"] = wind_label
        segment_copy["supply_preview"] = " / ".join(supply_bits[:2]) if supply_bits else "补给较少"
        segment_copy["supply_detail"] = "；".join(
            [
                f"餐饮：{' / '.join(nearby_names['food'][:3])}" if nearby_names["food"] else "",
                f"饮水：{' / '.join(nearby_names['water'][:3])}" if nearby_names["water"] else "",
                f"维修：{' / '.join(nearby_names['repair'][:2])}" if nearby_names["repair"] else "",
                f"休整：{' / '.join(nearby_names['rest'][:2])}" if nearby_names["rest"] else "",
                f"观景：{' / '.join(nearby_names['scenic'][:2])}" if nearby_names["scenic"] else "",
            ]
        ).strip("；")
        segment_copy["risk_detail"] = "；".join(risk_flags) if risk_flags else "暂无明显高风险道路提示"
        enriched.append(segment_copy)

    return enriched


def _make_path_candidate(label: str, points: list[dict], reason: str) -> dict:
    closes_loop = len(points) >= 2 and points[0].get("coord") == points[-1].get("coord")
    cleaned = _dedupe_named_points(points[:-1]) + [points[-1]] if closes_loop else _dedupe_named_points(points)
    return {
        "label": label,
        "reason": reason,
        "points": cleaned,
        "coord_sequence": ";".join([point["coord"] for point in cleaned]),
        "point_names": [point["name"] for point in cleaned],
    }


def _offset_coord(lat: float, lon: float, dlat: float, dlon: float, name: str) -> dict:
    next_lat = lat + dlat
    next_lon = lon + dlon
    return {
        "name": name,
        "lat": next_lat,
        "lon": next_lon,
        "coord": _format_coord(next_lon, next_lat),
    }


def _build_loop_scaffold(origin: dict, order_preference: str | None = None) -> list[dict]:
    lat = float(origin["lat"])
    lon = float(origin["lon"])
    east = _offset_coord(lat, lon, 0.020, 0.055, f"{origin['name']} 东侧骑行段")
    south = _offset_coord(lat, lon, -0.035, 0.020, f"{origin['name']} 南侧过渡段")
    west = _offset_coord(lat, lon, -0.012, -0.052, f"{origin['name']} 西侧收尾段")
    north = _offset_coord(lat, lon, 0.028, -0.018, f"{origin['name']} 北侧回接段")

    if order_preference == "climb_then_flat":
        return [east, south, west, north]
    if order_preference == "flat_then_climb":
        return [west, north, east, south]
    return [east, south, west]


def _generate_candidate_paths(
    origin: dict,
    destination: dict,
    waypoints: list[dict],
    loop_landmarks: list[dict],
    landmarks: list[dict],
    constraints: dict,
    route_notes: str,
    preset_variants: list[dict] | None = None,
) -> list[dict]:
    candidates = []
    strict_point_to_point = bool(constraints.get("strict_point_to_point")) and not constraints.get("is_loop")
    scaffold_waypoints = list(waypoints)
    if constraints.get("is_loop") and len(_dedupe_named_points([origin] + scaffold_waypoints + [destination])) < 2:
        scaffold_waypoints = _build_loop_scaffold(origin, constraints.get("order_preference"))
    base_points = [origin] + scaffold_waypoints + [destination]
    candidates.append(_make_path_candidate("主推荐", base_points, route_notes or "按原始需求生成的主路线"))

    for variant in preset_variants or []:
        variant_points = variant.get("points") or []
        if not variant_points:
            continue
        points = [origin] + variant_points + [origin if constraints.get("is_loop") else destination]
        candidates.append(_make_path_candidate(variant.get("label", "社区推荐"), points, variant.get("note", "参考社区常见走法生成")))

    if constraints.get("is_loop") and scaffold_waypoints:
        reversed_waypoints = list(reversed(scaffold_waypoints))
        candidates.append(_make_path_candidate("反向环线", [origin] + reversed_waypoints + [origin], "反转环线方向，便于用户比较顺逆时针体感"))
        if len(scaffold_waypoints) >= 3:
            rotated = scaffold_waypoints[1:] + scaffold_waypoints[:1]
            candidates.append(_make_path_candidate("节奏重排", [origin] + rotated + [origin], "调整环线路段顺序，尝试不同的爬升与巡航分布"))

    if strict_point_to_point:
        return candidates[:1]

    scenic_candidates = []
    for item in landmarks:
        tags = item.get("tags", {})
        name = tags.get("name")
        lat = float(item.get("lat", item.get("center", {}).get("lat", origin["lat"])))
        lon = float(item.get("lon", item.get("center", {}).get("lon", origin["lon"])))
        if not name:
            continue
        scenic_candidates.append(
            {
                "name": name,
                "lat": lat,
                "lon": lon,
                "coord": _format_coord(lon, lat),
                "kind": tags.get("tourism") or tags.get("natural") or tags.get("leisure") or "landmark",
            }
        )

    scenic_candidates = _dedupe_named_points(scenic_candidates)

    if not constraints.get("is_loop"):
        for scenic in scenic_candidates[:2]:
            mid_waypoints = waypoints[:1] + [scenic] + waypoints[1:]
            candidates.append(
                _make_path_candidate(
                    f"风景绕行 · {scenic['name']}",
                    [origin] + mid_waypoints + [destination],
                    f"额外串联 {scenic['name']}，适合休闲骑行或拍照停靠",
                )
            )
    elif loop_landmarks:
        landmark_points = []
        for item in loop_landmarks[:4]:
            landmark_points.append(
                {
                    "name": item["name"],
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "coord": _format_coord(float(item["lon"]), float(item["lat"])),
                }
            )
        if landmark_points:
            candidates.append(
                _make_path_candidate(
                    "地标环线",
                    [origin] + landmark_points + [origin],
                    "优先串联区域关键地标，增强路线辨识度和可游玩性",
                )
            )

    unique = []
    seen = set()
    for candidate in candidates:
        key = candidate["coord_sequence"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique[:5]


def _build_fallback_route(candidate: dict, is_loop: bool = False) -> dict:
    points = candidate.get("points", []) or []
    if len(points) < 2:
        return {}

    coordinates = [[float(point["lon"]), float(point["lat"])] for point in points]
    total_distance_m = 0.0
    legs = []
    point_names = candidate.get("point_names", []) or [point.get("name", f"点 {idx + 1}") for idx, point in enumerate(points)]

    for index in range(len(points) - 1):
        current = points[index]
        nxt = points[index + 1]
        segment_distance_m = _haversine_km(
            float(current["lat"]),
            float(current["lon"]),
            float(nxt["lat"]),
            float(nxt["lon"]),
        ) * 1000
        total_distance_m += segment_distance_m
        road_name = f"{point_names[index]} -> {point_names[index + 1]}"
        step_geometry = {
            "type": "LineString",
            "coordinates": [
                [float(current["lon"]), float(current["lat"])],
                [float(nxt["lon"]), float(nxt["lat"])],
            ],
        }
        legs.append(
            {
                "distance": segment_distance_m,
                "duration": segment_distance_m / 5.2,
                "summary": road_name,
                "steps": [
                    {
                        "distance": segment_distance_m,
                        "duration": segment_distance_m / 5.2,
                        "name": road_name,
                        "mode": "cycling",
                        "maneuver": {
                            "type": "depart" if index == 0 else ("arrive" if index == len(points) - 2 else "turn"),
                            "modifier": "straight",
                            "location": [float(current["lon"]), float(current["lat"])],
                        },
                        "geometry": step_geometry,
                    }
                ],
            }
        )

    return {
        "distance": total_distance_m,
        "duration": total_distance_m / 5.2,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "legs": legs,
        "candidate_label": candidate.get("label", "回退推荐"),
        "candidate_reason": candidate.get("reason", "外部路由接口失败，已生成可修正骨架路线"),
        "candidate_point_names": point_names,
        "candidate_rank": 0,
        "fallback_generated": True,
        "is_loop": is_loop,
    }


def _summarize_poi_elements(elements: list[dict]) -> dict:
    grouped = {
        "food": [],
        "water": [],
        "repair": [],
        "scenic": [],
        "medical": [],
        "rest": [],
    }
    for item in elements:
        tags = item.get("tags", {})
        name = tags.get("name") or tags.get("amenity") or tags.get("shop") or tags.get("tourism") or "未命名"
        amenity = tags.get("amenity")
        shop = tags.get("shop")
        tourism = tags.get("tourism")
        leisure = tags.get("leisure")
        if amenity in {"restaurant", "cafe", "convenience", "fuel"} or shop == "supermarket":
            grouped["food"].append(name)
        if amenity == "drinking_water":
            grouped["water"].append(name)
        if amenity in {"hospital", "pharmacy"}:
            grouped["medical"].append(name)
        if shop == "bicycle":
            grouped["repair"].append(name)
        if tourism in {"viewpoint", "attraction"}:
            grouped["scenic"].append(name)
        if amenity in {"toilets", "bicycle_parking"} or leisure in {"park", "fitness_station"}:
            grouped["rest"].append(name)

    return {key: list(dict.fromkeys(values))[:6] for key, values in grouped.items()}


async def demand_parser_node(state: GraphState):
    print("--- DEMAND PARSER NODE ---")
    intent = state.get("user_intent", "")
    preset = detect_route_preset(intent)
    heuristic_constraints = _extract_constraints(intent)
    target_distance_km = _extract_target_distance_km(intent)
    regex_points = _extract_explicit_route_points(intent)
    fallback_mode = (
        "round_trip"
        if heuristic_constraints.get("round_trip")
        else "loop"
        if heuristic_constraints.get("is_loop") or preset
        else "point_to_point"
    )
    fallback_region = preset.region_hint if preset else ""

    parsed = _call_llm_tool_json(
        f"""
你是骑行路线需求解析函数。请调用 parse_cycling_demand 工具输出 OpenAI function calling 格式的 arguments，不要自由文本回答。
任务：从用户自然语言中抽取真正的地点字段，不能把“周末、骑车、看日落、再返回、尽量避开”等需求词复制进地点名。

用户需求："{intent}"
已知本地线路别名：{preset.key if preset else ""}

规则：
- “A到B再返回/往返/折返”输出 route_mode=round_trip, origin=A, destination=B, return_to_origin=true。
- “环某地/绕某地一圈”输出 route_mode=loop，route_alias 填线路叫法，并在 route_points 中给出 4-6 个顺序地点。
- “帮我规划某城市周围100km线路/训练线路”也输出 route_mode=loop，target_distance_km 填数字，并直接选择该城市周边常见骑行方向的 4-6 个真实地点作为 route_points。
- 地点名只能是地图能搜索的名词，例如“中国石油大学华东唐岛湾校区”“星光岛”，不要输出“星光岛看日落”。
- 如果不确定，宁可留空，不要把整句塞进去。
""",
        DEMAND_PARSE_TOOL,
        "parse_cycling_demand",
        {
            "route_mode": fallback_mode,
            "region": fallback_region,
            "target_distance_km": target_distance_km,
            "route_alias": preset.key if preset else "",
            "origin": regex_points.get("origin", ""),
            "destination": regex_points.get("destination", ""),
            "waypoints": regex_points.get("waypoints", []),
            "route_points": [],
            "return_to_origin": bool(heuristic_constraints.get("round_trip")),
            "must_avoid": [],
            "notes": "",
        },
    )

    route_mode = parsed.get("route_mode") or fallback_mode
    if route_mode not in {"point_to_point", "round_trip", "loop"}:
        route_mode = fallback_mode
    origin = _sanitize_place_name(parsed.get("origin") or regex_points.get("origin", ""))
    destination = _sanitize_place_name(parsed.get("destination") or regex_points.get("destination", ""))
    waypoints = [
        _sanitize_place_name(item)
        for item in (parsed.get("waypoints") or regex_points.get("waypoints", []))
        if _sanitize_place_name(item)
    ][:6]
    route_points = [
        _sanitize_place_name(item)
        for item in (parsed.get("route_points") or [])
        if _sanitize_place_name(item)
    ][:8]
    if preset and route_mode == "loop" and not (regex_points.get("origin") and regex_points.get("destination")):
        preset_waypoints = choose_waypoints(preset, heuristic_constraints.get("order_preference"))
        route_points = [preset.origin, *preset_waypoints, preset.destination]
    if route_mode == "round_trip" and origin and destination:
        route_points = [origin, *waypoints, destination, origin]
    if not route_points:
        if route_mode == "round_trip" and origin and destination:
            route_points = [origin, destination, origin]
        elif route_mode == "point_to_point" and origin and destination:
            route_points = [origin, *waypoints, destination]
        elif route_mode == "loop" and origin:
            route_points = [origin, *waypoints, origin]
        elif route_mode == "loop" and preset:
            preset_waypoints = choose_waypoints(preset, heuristic_constraints.get("order_preference"))
            route_points = [preset.origin, *preset_waypoints, preset.destination]
    return_to_origin = bool(parsed.get("return_to_origin") or route_mode == "round_trip" or heuristic_constraints.get("round_trip"))
    if return_to_origin and route_mode != "loop":
        route_mode = "round_trip"
    if route_mode == "loop":
        return_to_origin = True
    if return_to_origin and route_points and route_points[0] != route_points[-1]:
        route_points.append(route_points[0])

    region = _sanitize_place_name(parsed.get("region") or fallback_region)
    parsed_distance = parsed.get("target_distance_km") or target_distance_km
    try:
        parsed_distance = float(parsed_distance) if parsed_distance is not None else None
    except Exception:
        parsed_distance = target_distance_km
    route_alias = parsed.get("route_alias") or (preset.key if preset else "")
    semantic_points = {
        "route_mode": route_mode,
        "region": region,
        "target_distance_km": parsed_distance,
        "route_alias": route_alias,
        "origin": origin,
        "destination": destination,
        "waypoints": waypoints,
        "route_points": route_points,
        "return_to_origin": return_to_origin,
        "must_avoid": parsed.get("must_avoid", []),
        "notes": parsed.get("notes", ""),
    }

    constraints = {
        **heuristic_constraints,
        "is_loop": route_mode in {"loop", "round_trip"},
        "round_trip": route_mode == "round_trip",
        "strict_point_to_point": route_mode == "point_to_point" and bool(origin and destination),
        "target_distance_km": parsed_distance,
    }
    if route_mode == "round_trip" and destination:
        constraints["must_pass"] = [destination, *waypoints]
    elif waypoints:
        constraints["must_pass"] = waypoints
    if parsed.get("must_avoid"):
        constraints["must_avoid"] = parsed.get("must_avoid", [])

    analysis_summary = dict(state.get("analysis_summary", {}))
    analysis_summary["demand_parse"] = semantic_points
    analysis_summary["constraint_chips"] = [
        chip
        for chip in [
            region,
            route_alias,
            f"{int(parsed_distance)}km" if parsed_distance else "",
            "往返" if route_mode == "round_trip" else "",
            "环线" if route_mode == "loop" else "",
            "点到点" if route_mode == "point_to_point" else "",
            "需求已结构化",
        ]
        if chip
    ]

    route_data = dict(state.get("route_data", {}))
    route_data.update(
        {
            "region_hint": region,
            "semantic_route_points": semantic_points,
            "explicit_route_points": {
                "origin": origin,
                "destination": destination,
                "waypoints": waypoints,
                "mode": route_mode,
            },
        }
    )

    return {
        "intent_type": "TYPE_B" if route_mode in {"loop", "round_trip"} else "TYPE_A",
        "parsed_constraints": constraints,
        "analysis_summary": analysis_summary,
        "route_data": route_data,
        "messages": [{"role": "assistant", "content": f"需求解析完成：{semantic_points}"}],
    }


async def intent_research_node(state: GraphState):
    print("--- INTENT RESEARCH NODE ---")
    intent = state.get("user_intent", "")
    preset = detect_route_preset(intent)
    route_data_in = state.get("route_data", {}) or {}
    semantic_points = route_data_in.get("semantic_route_points", {}) or {}
    heuristic_constraints = {**_extract_constraints(intent), **(state.get("parsed_constraints", {}) or {})}
    explicit_points = route_data_in.get("explicit_route_points", {}) or _extract_explicit_route_points(intent)

    if explicit_points.get("origin") and explicit_points.get("destination") and not heuristic_constraints.get("round_trip"):
        heuristic_constraints["is_loop"] = False
        heuristic_constraints["strict_point_to_point"] = True

    parsed = _call_llm_json(
        f"""
用户原始需求："{intent}"
请将这条骑行需求解析成结构化意图，尤其注意口语化环线、区域名、约束条件。
返回 JSON：
{{
  "intent_type": "point_to_point 或 loop",
  "region": "最核心的区域名，没有就填空字符串",
  "route_alias": "如 环大珠山/黄岛东西环岛，没有就填空字符串",
  "lifestyle": {{
    "wants_sunset": true,
    "wants_sunrise": false,
    "prefer_bike_lane": false,
    "avoid_bike_lane": false,
    "departure_time": null,
    "riding_speed_kmh": 18
  }},
  "constraints": {{
    "order_preference": "climb_then_flat / flat_then_climb / null",
    "must_pass": [],
    "must_avoid": [],
    "route_style": "scenic / training / commute / loop / null"
  }},
  "search_keyword": "给联网检索的短关键词"
}}
""",
        {
            "intent_type": "point_to_point" if explicit_points.get("origin") and explicit_points.get("destination") and not heuristic_constraints.get("round_trip") else ("loop" if heuristic_constraints.get("is_loop") or heuristic_constraints.get("round_trip") else "point_to_point"),
            "region": "",
            "route_alias": "",
            "lifestyle": {},
            "constraints": {},
            "search_keyword": "",
        },
    )

    region = semantic_points.get("region") or parsed.get("region") or (preset.region_hint if preset else "")
    lifestyle = parsed.get("lifestyle", {}) or {}
    constraints = {**heuristic_constraints, **(parsed.get("constraints", {}) or {})}
    if explicit_points.get("origin") and explicit_points.get("destination"):
        if constraints.get("round_trip"):
            constraints["is_loop"] = True
            constraints["strict_point_to_point"] = False
            constraints["must_pass"] = [explicit_points["destination"], *explicit_points.get("waypoints", [])]
        else:
            constraints["is_loop"] = False
            constraints["strict_point_to_point"] = True
            if explicit_points.get("waypoints"):
                constraints["must_pass"] = explicit_points["waypoints"]
    lifestyle["wants_sunset"] = bool(lifestyle.get("wants_sunset") or constraints.get("wants_sunset"))
    lifestyle["wants_sunrise"] = bool(lifestyle.get("wants_sunrise") or constraints.get("wants_sunrise"))
    lifestyle["prefer_bike_lane"] = True
    lifestyle["avoid_bike_lane"] = False
    lifestyle["riding_speed_kmh"] = lifestyle.get("riding_speed_kmh") or 18

    context = ""
    search_keyword = parsed.get("search_keyword", "")
    if search_keyword:
        try:
            import asyncio
            from duckduckgo_search import DDGS

            def _sync():
                with DDGS() as ddgs:
                    return list(ddgs.text(search_keyword, max_results=5, region="cn-zh"))

            results = await asyncio.to_thread(_sync)
            context = "\n".join(
                [
                    f"- {item.get('title', '')} | {item.get('body', '')}"
                    for item in results
                    if item.get("body") or item.get("title")
                ]
            )
        except Exception:
            context = ""

    resolved_alias = semantic_points.get("route_alias") or ("" if explicit_points.get("origin") and explicit_points.get("destination") and not constraints.get("round_trip") else (preset.key if preset else (parsed.get("route_alias") or "")))
    analysis_summary = {
        "intent_type": "point_to_point" if explicit_points.get("origin") and explicit_points.get("destination") and not constraints.get("round_trip") else parsed.get("intent_type", "loop" if constraints.get("is_loop") else "point_to_point"),
        "region": region,
        "route_alias": resolved_alias,
        "search_keyword": search_keyword,
        "agent_stack": [
            {
                "name": "Intent Agent",
                "status": "done",
                "detail": "完成口语骑行需求理解与约束抽取",
                "capabilities": ["口语意图解析", "约束抽取", "日落/训练识别"],
            },
            {
                "name": "Geo Agent",
                "status": "running",
                "detail": "准备解析区域、地名别名和地理锚点",
                "capabilities": ["城市别名归一", "地理锚点定位", "环线语义理解"],
            },
            {
                "name": "Route Agent",
                "status": "waiting",
                "detail": "等待进行候选路线生成与排序",
                "capabilities": ["候选路线生成", "人工修正回路", "多策略排序"],
            },
            {
                "name": "Policy Agent",
                "status": "waiting",
                "detail": "等待执行自行车路权规则和道路合规筛选",
                "capabilities": ["自行车道优先", "禁骑道路拦截", "危险道路降权"],
            },
            {
                "name": "Lifestyle Agent",
                "status": "waiting",
                "detail": "等待补充日落时间、风况和骑行体验建议",
                "capabilities": ["时间窗规划", "风景目标拟合", "出发时刻建议"],
            },
            {
                "name": "Simulation Agent",
                "status": "waiting",
                "detail": "等待进行爬升、体能和节奏推演",
                "capabilities": ["爬升估算", "体能预算", "配速与热量推演"],
            },
            {
                "name": "Explain Agent",
                "status": "waiting",
                "detail": "等待生成分段说明和关键道路摘要",
                "capabilities": ["分段讲解", "关键道路提炼", "地图阅读摘要"],
            },
            {
                "name": "RAG Agent",
                "status": "waiting",
                "detail": "将在最终路书阶段补充社区骑行情报",
                "capabilities": ["社区情报检索", "封路风险补强", "经验回退提示"],
            },
            {
                "name": "MCP Data Agent",
                "status": "waiting",
                "detail": "将调用路线、天气、POI、海拔等数据",
                "capabilities": ["路线数据", "天气接口", "POI与海拔采集"],
            },
        ],
        "constraint_chips": [
            chip
            for chip in [
                region,
                resolved_alias,
                "环线" if constraints.get("is_loop") else "点到点",
                "自行车道优先",
                "禁用高速/封闭道路",
                "明确起终点" if constraints.get("strict_point_to_point") else "",
                "往返" if constraints.get("round_trip") else "",
                "先爬后平" if constraints.get("order_preference") == "climb_then_flat" else "",
                "先平后爬" if constraints.get("order_preference") == "flat_then_climb" else "",
                "看日落" if lifestyle.get("wants_sunset") else "",
                "看日出" if lifestyle.get("wants_sunrise") else "",
                "避开主路" if constraints.get("traffic_mode") == "avoid_motor_traffic" else "",
            ]
            if chip
        ],
    }

    return {
        "intent_type": "TYPE_B" if analysis_summary["intent_type"] == "loop" or constraints.get("round_trip") else "TYPE_A",
        "route_research_context": context,
        "lifestyle_context": lifestyle,
        "parsed_constraints": constraints,
        "analysis_summary": analysis_summary,
        "route_data": {**route_data_in, "region_hint": region, "explicit_route_points": explicit_points, "semantic_route_points": semantic_points},
        "messages": [{"role": "assistant", "content": f"意图解析完成：{analysis_summary['constraint_chips']}"}],
    }


async def geospatial_analysis_node(state: GraphState):
    print("--- GEOSPATIAL ANALYSIS NODE ---")
    region_hint = state.get("route_data", {}).get("region_hint", "")
    intent = state.get("user_intent", "")
    constraints = state.get("parsed_constraints", {})
    preset = detect_route_preset(intent)

    region_info = await _resolve_region(region_hint, intent)
    if preset and preset.anchor_points:
        lons = [coord[0] for coord in preset.anchor_points.values()]
        lats = [coord[1] for coord in preset.anchor_points.values()]
        region_info = {
            "name": preset.region_hint,
            "center": {"lat": sum(lats) / len(lats), "lon": sum(lons) / len(lons)},
            "bbox": [min(lats), max(lats), min(lons), max(lons)],
        }
    landmarks = await _fetch_route_landmarks(region_info)
    loop_points = _select_loop_points(landmarks, region_info, constraints.get("order_preference"))

    analysis_summary = dict(state.get("analysis_summary", {}))
    analysis_summary["resolved_region"] = region_info.get("name", region_hint)
    analysis_summary["landmark_preview"] = [item["name"] for item in loop_points[:4]]
    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][1]["status"] = "done"
        analysis_summary["agent_stack"][1]["detail"] = f"已锁定区域：{region_info.get('name', region_hint)}"
        analysis_summary["agent_stack"][2]["status"] = "running"
        analysis_summary["agent_stack"][2]["detail"] = "正在构造候选路线与人类可修正方案"

    route_data = dict(state.get("route_data", {}))
    route_data["region_hint"] = region_hint or region_info.get("name", "")
    route_data["region_info"] = region_info
    route_data["loop_landmarks"] = loop_points
    route_data["all_landmarks"] = landmarks[:20]
    route_data["route_preset"] = preset.key if preset else None

    return {
        "analysis_summary": analysis_summary,
        "route_data": route_data,
        "messages": [{"role": "assistant", "content": f"地理解析完成：{region_info.get('name', region_hint)}"}],
    }


async def coordinate_control_node(state: GraphState):
    print("--- COORDINATE CONTROL NODE ---")
    intent = state.get("user_intent", "")
    route_data = dict(state.get("route_data", {}))
    constraints = dict(state.get("parsed_constraints", {}) or {})
    lifestyle = state.get("lifestyle_context", {}) or {}
    region_info = route_data.get("region_info", {})
    semantic_points = route_data.get("semantic_route_points", {}) or {}
    explicit_points = route_data.get("explicit_route_points", {}) or _extract_explicit_route_points(intent)
    preset = detect_route_preset(intent)

    async def resolve_name(name: str, active_preset=None) -> dict | None:
        if not name:
            return None
        anchor = lookup_anchor_point(active_preset, name)
        if anchor:
            lon, lat = anchor
            return {"name": name, "lat": lat, "lon": lon, "coord": _format_coord(lon, lat)}
        return await _resolve_point(name, region_info)

    skeleton = {
        "origin": "",
        "destination": "",
        "waypoints": [],
        "route_notes": "",
        "source": "coordinate_control",
    }

    semantic_route_points = [
        _sanitize_place_name(point)
        for point in (semantic_points.get("route_points") or [])
        if _sanitize_place_name(point)
    ]
    if len(semantic_route_points) >= 2:
        skeleton["origin"] = semantic_route_points[0]
        skeleton["destination"] = semantic_route_points[-1]
        skeleton["waypoints"] = semantic_route_points[1:-1]
        skeleton["route_notes"] = semantic_points.get("notes") or "按需求解析节点直接生成的路线骨架规划。"
        skeleton["source"] = "semantic_route_points"
    elif semantic_points.get("route_mode") == "round_trip" and semantic_points.get("origin") and semantic_points.get("destination"):
        skeleton["origin"] = semantic_points.get("origin", "")
        skeleton["destination"] = semantic_points.get("origin", "")
        skeleton["waypoints"] = [semantic_points.get("destination", ""), *semantic_points.get("waypoints", [])]
        skeleton["route_notes"] = semantic_points.get("notes") or "按需求解析节点输出的起点与折返点规划往返路线。"
        skeleton["source"] = "semantic_round_trip"
    elif semantic_points.get("route_mode") == "point_to_point" and semantic_points.get("origin") and semantic_points.get("destination"):
        skeleton["origin"] = semantic_points.get("origin", "")
        skeleton["destination"] = semantic_points.get("destination", "")
        skeleton["waypoints"] = semantic_points.get("waypoints", [])
        skeleton["route_notes"] = semantic_points.get("notes") or "按需求解析节点输出的明确起终点规划。"
        skeleton["source"] = "semantic_point_to_point"
    elif explicit_points.get("origin") and explicit_points.get("destination"):
        skeleton["origin"] = explicit_points.get("origin", "")
        if constraints.get("round_trip"):
            skeleton["destination"] = explicit_points.get("origin", "")
            skeleton["waypoints"] = [explicit_points.get("destination", ""), *explicit_points.get("waypoints", [])]
            skeleton["route_notes"] = "按明确起点与折返点规划往返路线，终点回到起点。"
            skeleton["source"] = "explicit_round_trip"
        else:
            skeleton["destination"] = explicit_points.get("destination", "")
            skeleton["waypoints"] = explicit_points.get("waypoints", [])
            skeleton["route_notes"] = "按明确起终点进行点到点骑行规划，不额外添加自动绕行途经点。"
            skeleton["source"] = "explicit_point_to_point"
    elif constraints.get("is_loop") or preset:
        anchor_names = list((preset.anchor_points if preset else {}).keys())
        landmark_names = []
        for item in (route_data.get("all_landmarks", []) or [])[:16]:
            name = (item.get("tags", {}) or {}).get("name")
            if name:
                landmark_names.append(name)
        fallback_waypoints = choose_waypoints(preset, constraints.get("order_preference")) if preset else []
        fallback_origin = preset.origin if preset else ""
        llm_skeleton = _call_llm_json(
            f"""
用户骑行需求："{intent}"
已锁定区域："{region_info.get('name', route_data.get('region_hint', ''))}"
可用锚点名称（优先从这里选，不要发明不存在的点）：
{json.dumps(anchor_names, ensure_ascii=False)}
区域候选地标：
{json.dumps(landmark_names, ensure_ascii=False)}
目标距离：{constraints.get("target_distance_km") or "未指定"} km
社区经验参考：
{getattr(preset, 'community_summary', '') if preset else ''}

请像熟悉本地骑行路线的人一样，给出一条可执行环线骨架。
要求：
1. origin 和 destination 必须相同，表示闭环。
2. waypoints 只放 3-5 个真正有路线意义的点，不要塞无关 POI；如果有目标距离，点位跨度要接近该距离。
3. 如果用户说看日落，把观景点放在后段。
4. 返回 JSON，不要 markdown。
{{
  "origin": "起点名",
  "destination": "终点名",
  "waypoints": ["途经点1", "途经点2"],
  "route_notes": "一句话说明路线逻辑"
}}
""",
            {
                "origin": fallback_origin,
                "destination": fallback_origin,
                "waypoints": fallback_waypoints,
                "route_notes": preset.notes if preset else "按区域地标组织闭环路线。",
            },
        )
        skeleton["origin"] = llm_skeleton.get("origin") or fallback_origin
        skeleton["destination"] = llm_skeleton.get("destination") or skeleton["origin"]
        skeleton["waypoints"] = [name for name in (llm_skeleton.get("waypoints") or fallback_waypoints) if name]
        skeleton["route_notes"] = llm_skeleton.get("route_notes") or (preset.notes if preset else "按大模型生成的本地骑行骨架规划环线。")
        skeleton["source"] = "llm_loop_skeleton"
        if lifestyle.get("wants_sunset") and preset and preset.sunset_viewpoint and preset.sunset_viewpoint not in skeleton["waypoints"]:
            skeleton["waypoints"].append(preset.sunset_viewpoint)

    resolved_origin = await resolve_name(skeleton.get("origin", ""), preset)
    resolved_dest = await resolve_name(skeleton.get("destination", ""), preset)
    resolved_waypoints = []
    for name in skeleton.get("waypoints", [])[:6]:
        point = await resolve_name(name, preset)
        if point and point.get("coord") not in {item.get("coord") for item in resolved_waypoints}:
            resolved_waypoints.append(point)

    if constraints.get("is_loop") or constraints.get("round_trip") or skeleton["source"] == "semantic_route_points" and skeleton.get("origin") == skeleton.get("destination"):
        resolved_dest = resolved_origin

    analysis_summary = dict(state.get("analysis_summary", {}))
    if resolved_origin or resolved_dest or resolved_waypoints:
        analysis_summary["coordinate_control"] = {
            "origin": resolved_origin.get("name") if resolved_origin else skeleton.get("origin", ""),
            "destination": resolved_dest.get("name") if resolved_dest else skeleton.get("destination", ""),
            "waypoints": [point["name"] for point in resolved_waypoints],
            "source": skeleton["source"],
        }
        analysis_summary["constraint_chips"] = list(
            dict.fromkeys((analysis_summary.get("constraint_chips", []) or []) + ["坐标已核验"])
        )
    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][1]["detail"] = "已完成区域定位与起终点坐标核验"

    route_data["coordinate_control"] = {
        "origin": resolved_origin,
        "destination": resolved_dest,
        "waypoints": resolved_waypoints,
        "origin_name": skeleton.get("origin", ""),
        "dest_name": skeleton.get("destination", ""),
        "waypoint_names": skeleton.get("waypoints", [])[:6],
        "route_notes": skeleton.get("route_notes", ""),
        "source": skeleton.get("source", "coordinate_control"),
    }

    return {
        "analysis_summary": analysis_summary,
        "route_data": route_data,
        "messages": [{"role": "assistant", "content": "坐标控制完成：起终点与关键点已独立核验。"}],
    }


async def planner_node(state: GraphState):
    print("--- PLANNER NODE ---")
    intent = state.get("user_intent", "")
    lifestyle = state.get("lifestyle_context", {})
    constraints = state.get("parsed_constraints", {})
    research_ctx = state.get("route_research_context", "")
    route_data = dict(state.get("route_data", {}))
    region_info = route_data.get("region_info", {})
    landmarks = route_data.get("all_landmarks", [])
    explicit_points = route_data.get("explicit_route_points", {}) or _extract_explicit_route_points(intent)
    coordinate_control = route_data.get("coordinate_control", {}) or {}
    preset = None if explicit_points.get("origin") and explicit_points.get("destination") and not constraints.get("round_trip") else detect_route_preset(intent)

    origin_name = None
    dest_name = None
    waypoint_names: list[str] = []
    route_notes = ""
    preset_variants: list[dict] = []

    if coordinate_control.get("origin") and coordinate_control.get("destination"):
        origin_name = coordinate_control.get("origin", {}).get("name") or coordinate_control.get("origin_name", "")
        dest_name = coordinate_control.get("destination", {}).get("name") or coordinate_control.get("dest_name", "")
        waypoint_names = [point.get("name", "") for point in coordinate_control.get("waypoints", []) if point.get("name")]
        route_notes = coordinate_control.get("route_notes") or "按坐标控制节点核验后的起终点与关键点规划。"
    elif explicit_points.get("origin") and explicit_points.get("destination"):
        origin_name = explicit_points.get("origin") or ""
        dest_name = explicit_points.get("destination") or ""
        waypoint_names = explicit_points.get("waypoints") or list(constraints.get("must_pass", []) or [])
        route_notes = "按明确起终点进行点到点骑行规划，不额外添加自动绕行途经点。"
    elif preset:
        origin_name = preset.origin
        dest_name = preset.destination
        waypoint_names = choose_waypoints(preset, constraints.get("order_preference"))
        if lifestyle.get("wants_sunset") and preset.sunset_viewpoint and preset.sunset_viewpoint not in waypoint_names:
            waypoint_names.append(preset.sunset_viewpoint)
        route_notes = "；".join(
            [
                preset.notes or "",
                preset.community_summary or "",
                f"优先规避 {', '.join(preset.avoid_roads[:2])}" if preset.avoid_roads else "",
            ]
        ).strip("；")
    else:
        parsed = _call_llm_json(
            f"""
用户需求："{intent}"
已解析区域："{region_info.get('name', route_data.get('region_hint', ''))}"
联网参考：
{research_ctx}

请提取适合路由器执行的起终点和关键途经点。
如果用户说的是环线但没有明确起点，请优先给出一个适合作为骑行集合点/停车点/公园入口的起终点。
返回 JSON：
{{
  "origin": "起点名",
  "destination": "终点名",
  "waypoints": ["途经点1", "途经点2"],
  "route_notes": "一句话说明这条路线怎么满足用户要求"
}}
""",
            {"origin": "", "destination": "", "waypoints": [], "route_notes": ""},
        )
        origin_name = parsed.get("origin") or ""
        dest_name = parsed.get("destination") or ""
        waypoint_names = parsed.get("waypoints", []) or list(constraints.get("must_pass", []) or [])
        route_notes = parsed.get("route_notes", "")

        if constraints.get("is_loop") and not origin_name:
            loop_landmarks = route_data.get("loop_landmarks", [])
            if loop_landmarks:
                start = loop_landmarks[0]
                origin_name = f"{start['name']} {region_info.get('name', '')}".strip()
                dest_name = origin_name
                waypoint_names = [f"{item['name']} {region_info.get('name', '')}".strip() for item in loop_landmarks[1:]]

    origin_anchor = lookup_anchor_point(preset, origin_name or "")
    dest_anchor = lookup_anchor_point(preset, dest_name or "")
    controlled_origin = coordinate_control.get("origin") if coordinate_control.get("origin") else None
    controlled_dest = coordinate_control.get("destination") if coordinate_control.get("destination") else None
    controlled_waypoints = coordinate_control.get("waypoints") or []

    resolved_origin = controlled_origin or (
        {
            "name": origin_name,
            "lat": origin_anchor[1],
            "lon": origin_anchor[0],
            "coord": _format_coord(origin_anchor[0], origin_anchor[1]),
        }
        if origin_anchor and origin_name
        else await _resolve_point(origin_name, region_info) if origin_name else None
    )
    resolved_dest = controlled_dest or (
        {
            "name": dest_name,
            "lat": dest_anchor[1],
            "lon": dest_anchor[0],
            "coord": _format_coord(dest_anchor[0], dest_anchor[1]),
        }
        if dest_anchor and dest_name
        else await _resolve_point(dest_name, region_info) if dest_name else None
    )

    if constraints.get("strict_point_to_point") and (not resolved_origin or not resolved_dest):
        analysis_summary = dict(state.get("analysis_summary", {}))
        analysis_summary["route_resolution"] = {
            "origin": origin_name or "",
            "destination": dest_name or "",
            "waypoints": waypoint_names[:6],
            "preset": "",
        }
        analysis_summary["route_fetch_status"] = "unresolved"
        analysis_summary["route_fetch_note"] = "明确起终点已识别，但有地点未能准确定位，请检查名称或改用地图点选。"
        return {
            "analysis_summary": analysis_summary,
            "route_data": {
                **route_data,
                "origin": "",
                "destination": "",
                "origin_name": origin_name or "",
                "dest_name": dest_name or "",
                "waypoints_names": waypoint_names[:6],
                "osrm_routing_coords": "",
                "route_notes": route_notes,
                "candidate_paths": [],
                "avoid_road_keywords": [],
                "resolution_failed": True,
            },
            "messages": [{"role": "assistant", "content": "起终点已识别，但至少有一个地点暂未成功定位。"}],
        }

    if not resolved_origin:
        center = region_info.get("center", {})
        resolved_origin = {
            "name": region_info.get("name", "区域中心"),
            "lat": center.get("lat", 35.8617),
            "lon": center.get("lon", 104.1954),
            "coord": _format_coord(center.get("lon", 104.1954), center.get("lat", 35.8617)),
        }
    if not resolved_dest:
        resolved_dest = resolved_origin

    resolved_point_cache: dict[str, dict | None] = {}

    async def resolve_named_point(name: str) -> dict | None:
        if name not in resolved_point_cache:
            anchor = lookup_anchor_point(preset, name)
            if anchor:
                lon, lat = anchor
                resolved_point_cache[name] = {
                    "name": name,
                    "lat": lat,
                    "lon": lon,
                    "coord": _format_coord(lon, lat),
                }
            else:
                resolved_point_cache[name] = await _resolve_point(name, region_info)
        return resolved_point_cache[name]

    resolved_waypoints = list(controlled_waypoints[:6])
    if not resolved_waypoints:
        for name in waypoint_names[:6]:
            point = await resolve_named_point(name)
            if point:
                resolved_waypoints.append(point)

    if preset:
        for variant in build_preset_variants(
            preset,
            constraints.get("order_preference"),
            bool(lifestyle.get("wants_sunset")),
        )[:5]:
            resolved_variant_points = []
            for name in variant.waypoints[:6]:
                point = await resolve_named_point(name)
                if point:
                    resolved_variant_points.append(point)
            if resolved_variant_points:
                preset_variants.append(
                    {
                        "label": variant.label,
                        "points": resolved_variant_points,
                        "note": variant.note,
                    }
                )

    if constraints.get("is_loop") and resolved_dest["coord"] != resolved_origin["coord"]:
        resolved_dest = resolved_origin

    osrm_coords = ";".join([resolved_origin["coord"]] + [p["coord"] for p in resolved_waypoints] + [resolved_dest["coord"]])
    candidate_paths = _generate_candidate_paths(
        resolved_origin,
        resolved_dest,
        resolved_waypoints,
        route_data.get("loop_landmarks", []),
        landmarks,
        constraints,
        route_notes,
        preset_variants=preset_variants,
    )

    analysis_summary = dict(state.get("analysis_summary", {}))
    analysis_summary["route_resolution"] = {
        "origin": resolved_origin["name"],
        "destination": resolved_dest["name"],
        "waypoints": [p["name"] for p in resolved_waypoints],
        "preset": preset.key if preset else "",
    }
    analysis_summary["candidate_labels"] = [candidate["label"] for candidate in candidate_paths]
    if preset:
        analysis_summary["community_route_brief"] = preset.community_summary or preset.notes or ""
        analysis_summary["constraint_chips"] = list(
            dict.fromkeys((analysis_summary.get("constraint_chips", []) or []) + ["社区路线骨架", "本地别名已命中"])
        )
    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][2]["status"] = "done"
        analysis_summary["agent_stack"][2]["detail"] = f"已生成 {len(candidate_paths)} 组可执行候选路径"
        analysis_summary["agent_stack"][8]["status"] = "running"
        analysis_summary["agent_stack"][8]["detail"] = "正在拉取路线、天气、POI 与高程数据"

    return {
        "plan": [
            "理解口语化骑行意图",
            "解析全国区域与地理锚点",
            "生成可执行的骑行约束路线",
            "获取真实路网并打分",
        ],
        "analysis_summary": analysis_summary,
        "route_data": {
            **route_data,
            "origin": resolved_origin["coord"],
            "destination": resolved_dest["coord"],
            "origin_name": resolved_origin["name"],
            "dest_name": resolved_dest["name"],
            "waypoints_names": [p["name"] for p in resolved_waypoints],
            "osrm_routing_coords": osrm_coords,
            "route_notes": route_notes,
            "candidate_paths": candidate_paths,
            "avoid_road_keywords": preset.avoid_roads if preset else [],
        },
        "messages": [{"role": "assistant", "content": f"路线规划完成：{resolved_origin['name']} → {resolved_dest['name']}"}],
    }


async def executor_node(state: GraphState):
    print("--- EXECUTOR NODE ---")
    route_data = dict(state.get("route_data", {}))
    strict_point_to_point = bool(state.get("parsed_constraints", {}).get("strict_point_to_point"))
    is_loop = bool(state.get("parsed_constraints", {}).get("is_loop"))
    if route_data.get("resolution_failed"):
        analysis_summary = dict(state.get("analysis_summary", {}))
        analysis_summary["candidate_count"] = 0
        return {
            "route_data": {**route_data, "routes": []},
            "weather_info": {},
            "poi_info": {"elements": [], "error": ""},
            "analysis_summary": analysis_summary,
            "safety_warnings": ["请先修正未识别成功的起点或终点，再重新规划。"],
            "messages": [{"role": "assistant", "content": "地点定位失败，未生成不可用的假路线。"}],
        }
    origin = route_data.get("origin", "116.397389,39.908722")
    lon, lat = _parse_coord_string(origin)
    candidate_paths = route_data.get("candidate_paths") or [
        {
            "label": "主推荐",
            "reason": route_data.get("route_notes", "") or "基础推荐路线",
            "coord_sequence": route_data.get("osrm_routing_coords", origin),
            "point_names": [route_data.get("origin_name", "起点"), *route_data.get("waypoints_names", []), route_data.get("dest_name", "终点")],
        }
    ]

    import asyncio

    route_responses, weather_resp, poi_resp = await asyncio.gather(
        asyncio.gather(
            *[
                _fetch_route(
                    candidate["coord_sequence"],
                    allow_driving_fallback=not strict_point_to_point,
                )
                for candidate in candidate_paths
            ]
        ),
        _fetch_weather(lat, lon),
        _fetch_pois(lat, lon, 5000),
    )

    flattened_routes = []
    successful_candidate_labels = set()
    for candidate, response in zip(candidate_paths, route_responses):
        routes_for_candidate = response.get("routes", [])[:3]
        if routes_for_candidate:
            successful_candidate_labels.add(candidate["label"])
        for route_idx, route in enumerate(routes_for_candidate):
            route["candidate_label"] = candidate["label"]
            route["candidate_reason"] = candidate["reason"]
            route["candidate_point_names"] = candidate["point_names"]
            route["candidate_rank"] = route_idx
            route["route_profile"] = response.get("_profile", "bicycle")
            flattened_routes.append(route)

    seen = set()
    unique_routes = []
    for route in flattened_routes:
        geometry = route.get("geometry", {}).get("coordinates", [])
        if not geometry:
            continue
        start = geometry[0]
        end = geometry[-1]
        key = (
            round(route.get("distance", 0), -2),
            round(start[0], 4),
            round(start[1], 4),
            round(end[0], 4),
            round(end[1], 4),
            route.get("candidate_label"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_routes.append(route)

    if not unique_routes and is_loop:
        for candidate in candidate_paths:
            fallback_route = _build_fallback_route(candidate, is_loop=is_loop)
            if fallback_route:
                unique_routes.append(fallback_route)
    elif unique_routes and is_loop and not strict_point_to_point:
        existing_labels = {route.get("candidate_label") for route in unique_routes}
        for candidate in candidate_paths:
            if candidate["label"] in existing_labels or candidate["label"] in successful_candidate_labels:
                continue
            fallback_route = _build_fallback_route(candidate, is_loop=is_loop)
            if fallback_route:
                unique_routes.append(fallback_route)

    corridor_poi_resp = await _fetch_route_corridor_pois(unique_routes) if unique_routes else {"elements": [], "error": ""}
    base_poi_elements = poi_resp.get("elements", []) if isinstance(poi_resp, dict) else []
    corridor_poi_elements = corridor_poi_resp.get("elements", []) if isinstance(corridor_poi_resp, dict) else []
    fallback_poi_resp = _fallback_pois_from_preset(route_data.get("route_preset"))
    if not base_poi_elements and not corridor_poi_elements:
        poi_resp = fallback_poi_resp
    else:
        poi_resp = {
            "elements": base_poi_elements + corridor_poi_elements,
            "error": (poi_resp.get("error", "") if isinstance(poi_resp, dict) else "") or corridor_poi_resp.get("error", ""),
        }

    merged = {**route_data, "routes": unique_routes}
    merged["origin"] = origin
    merged["destination"] = route_data.get("destination", origin)
    poi_elements = poi_resp.get("elements", []) if isinstance(poi_resp, dict) else []
    poi_summary = _summarize_poi_elements(poi_elements)
    analysis_summary = dict(state.get("analysis_summary", {}))
    analysis_summary["poi_summary"] = poi_summary
    analysis_summary["weather_snapshot"] = weather_resp.get("current", {})
    analysis_summary["candidate_count"] = len(unique_routes)
    if not route_responses or all(not response.get("routes") for response in route_responses):
        if strict_point_to_point:
            analysis_summary["route_fetch_status"] = "no_bike_route"
            analysis_summary["route_fetch_note"] = "当前未找到可执行的自行车路线，系统已拒绝使用机动车或直线骨架冒充结果。建议添加可骑行中转点后重试。"
        else:
            analysis_summary["route_fetch_status"] = "fallback"
            analysis_summary["route_fetch_note"] = "外部路由接口失败，已自动降级为可修正骨架路线"
    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][8]["status"] = "done"
        analysis_summary["agent_stack"][8]["detail"] = (
            "外部接口部分失败，已回退为骨架路线与基础数据"
            if analysis_summary.get("route_fetch_status") == "fallback"
            else "已获取路线、天气、POI 与高程相关数据"
        )
        analysis_summary["agent_stack"][3]["status"] = "running"
        analysis_summary["agent_stack"][3]["detail"] = "正在校验自行车道优先策略与禁骑道路"

    return {
        "route_data": merged,
        "weather_info": weather_resp,
        "poi_info": poi_resp,
        "analysis_summary": analysis_summary,
        "safety_warnings": ["请关注临时施工、夜骑照明和补给间隔。"],
        "messages": [{"role": "assistant", "content": "真实路线、天气和设施数据已获取。"}],
    }


async def route_policy_node(state: GraphState):
    print("--- ROUTE POLICY NODE ---")
    route_payload = dict(state.get("route_data", {}))
    routes = route_payload.get("routes", [])
    analysis_summary = dict(state.get("analysis_summary", {}))
    warnings = list(state.get("safety_warnings", []))
    parsed_constraints = state.get("parsed_constraints", {}) or {}
    strict_point_to_point = bool(
        (
            parsed_constraints.get("strict_point_to_point")
            or (
                state.get("intent_type") == "point_to_point"
                and not parsed_constraints.get("is_loop")
            )
            or (
                route_payload.get("origin_name")
                and route_payload.get("dest_name")
                and route_payload.get("origin_name") != route_payload.get("dest_name")
                and not parsed_constraints.get("is_loop")
            )
        )
    )
    if not routes:
        return {"route_data": route_payload, "analysis_summary": analysis_summary}

    import asyncio

    lane_contexts = await asyncio.gather(*[_fetch_lane_context(route.get("geometry", {})) for route in routes])

    compliant_routes = []
    for route, lane in zip(routes, lane_contexts):
        snapshot = _route_policy_snapshot(lane, route, route_payload.get("avoid_road_keywords", []))
        route["infra_context"] = lane
        route["policy"] = snapshot
        if snapshot["is_compliant"]:
            compliant_routes.append(route)

    if strict_point_to_point and not compliant_routes:
        analysis_summary["bike_policy"] = {
            "mode": "strict_bicycle_priority",
            "summary": "当前仅命中高速、封闭或明确禁行道路，已拒绝生成不可执行路线",
            "forbidden_filtered": len(routes),
            "cycleway_hits": 0,
            "bike_friendly_hits": 0,
            "primary_hits": 0,
            "forbidden_hits": max(
                [
                    (route.get("policy", {}).get("forbidden_hits", 0) + route.get("policy", {}).get("hard_keyword_hits", 0))
                    for route in routes
                ]
                or [0]
            ),
        }
        analysis_summary["candidate_count"] = 0
        analysis_summary["route_fetch_status"] = "unsafe_rejected"
        analysis_summary["route_fetch_note"] = "已识别到明确起终点，但当前只找到包含高速、封闭或明确禁行道路的方案，未输出不可执行路线。"
        if analysis_summary.get("agent_stack"):
            analysis_summary["agent_stack"][3]["status"] = "done"
            analysis_summary["agent_stack"][3]["detail"] = "已拦截高速/封闭道路候选，未输出不可执行路线"
            analysis_summary["agent_stack"][4]["status"] = "done"
            analysis_summary["agent_stack"][4]["detail"] = "当前无可执行路线，时间与体验建议已停止继续扩展"
            analysis_summary["agent_stack"][5]["status"] = "done"
            analysis_summary["agent_stack"][5]["detail"] = "当前无可执行路线，未继续进行体能推演"
            analysis_summary["agent_stack"][6]["status"] = "waiting"
            analysis_summary["agent_stack"][6]["detail"] = "等待用户修正起终点或添加中转点"
        route_payload["routes"] = []
        warnings.append("⛔ 当前仅找到包含高速、封闭或明确禁行道路的路线，系统已拒绝展示。建议改用地图点选中转点后再试。")
        return {
            "route_data": route_payload,
            "analysis_summary": analysis_summary,
            "safety_warnings": warnings,
            "messages": [{"role": "assistant", "content": "已拦截不适合骑行的点到点路线。"}],
        }

    filtered_routes = compliant_routes
    if not filtered_routes:
        filtered_routes = [
            route
            for route in routes
            if route.get("policy", {}).get("forbidden_hits", 0) == 0
            and route.get("policy", {}).get("hard_keyword_hits", 0) == 0
        ]
    if not filtered_routes:
        filtered_routes = routes

    target_distance_km = parsed_constraints.get("target_distance_km")
    try:
        target_distance_km = float(target_distance_km) if target_distance_km else None
    except Exception:
        target_distance_km = None

    def target_distance_penalty(route: dict) -> float:
        if not target_distance_km:
            return 0.0
        actual_km = float(route.get("distance", 0) or 0) / 1000.0
        if actual_km <= 0:
            return 999.0
        return abs(actual_km - target_distance_km) / max(target_distance_km, 1.0)

    filtered_routes.sort(
        key=lambda item: (
            item.get("policy", {}).get("forbidden_hits", 0),
            item.get("policy", {}).get("hard_keyword_hits", 0),
            target_distance_penalty(item),
            item.get("policy", {}).get("fast_road_hits", 0) + item.get("policy", {}).get("soft_keyword_hits", 0),
            -item.get("policy", {}).get("policy_score", 0),
            -item.get("policy", {}).get("cycleway_hits", 0),
            item.get("policy", {}).get("primary_hits", 0),
        )
    )
    route_payload["routes"] = filtered_routes

    top_policy = filtered_routes[0].get("policy", {}) if filtered_routes else {}
    analysis_summary["bike_policy"] = {
        "mode": "strict_bicycle_priority",
        "summary": top_policy.get("summary", "已按自行车道优先策略筛选路线"),
        "forbidden_filtered": max(0, len(routes) - len(filtered_routes)),
        "cycleway_hits": top_policy.get("cycleway_hits", 0),
        "bike_friendly_hits": top_policy.get("bike_friendly_hits", 0),
        "primary_hits": top_policy.get("primary_hits", 0),
        "forbidden_hits": top_policy.get("forbidden_hits", 0)
        + top_policy.get("hard_keyword_hits", 0),
        "risk_hits": top_policy.get("fast_road_hits", 0)
        + top_policy.get("soft_keyword_hits", 0)
        + top_policy.get("profile_risk_hits", 0),
    }
    analysis_summary["constraint_chips"] = list(
        dict.fromkeys((analysis_summary.get("constraint_chips", []) or []) + ["自行车道优先", "禁用高速/封闭道路"])
    )

    if (
        top_policy.get("forbidden_hits", 0) > 0
        or top_policy.get("hard_keyword_hits", 0) > 0
    ):
        warnings.append("⛔ 当前路线命中高速、封闭或明确禁行道路，请勿直接执行。")
    elif (
        top_policy.get("fast_road_hits", 0) > 0
        or top_policy.get("soft_keyword_hits", 0) > 0
        or top_policy.get("profile_risk_hits", 0) > 0
    ):
        warnings.append("⚠️ 当前路线包含快速路、高架、隧道或普通机动车道路段，系统已降权但保留，请结合现场路权复核。")
    elif top_policy.get("cycleway_hits", 0) > 0:
        warnings.append("🚲 当前优先方案包含明确自行车道/骑行设施，符合骑行规划优先级。")
    else:
        warnings.append("ℹ️ 当前优先方案以适合骑行的普通道路为主，未检测到明显禁骑道路。")

    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][3]["status"] = "done"
        analysis_summary["agent_stack"][3]["detail"] = top_policy.get("summary", "已完成道路合规校验")
        analysis_summary["agent_stack"][4]["status"] = "running"
        analysis_summary["agent_stack"][4]["detail"] = "正在补充时间窗、天气和骑行体验建议"

    return {
        "route_data": route_payload,
        "analysis_summary": analysis_summary,
        "safety_warnings": warnings,
        "messages": [{"role": "assistant", "content": "已执行自行车路权与道路合规筛选。"}],
    }


async def lifestyle_enrichment_node(state: GraphState):
    print("--- LIFESTYLE ENRICHMENT NODE ---")
    lifestyle = dict(state.get("lifestyle_context", {}))
    constraints = state.get("parsed_constraints", {})
    route_data = state.get("route_data", {})
    weather = state.get("weather_info", {})

    try:
        lon, lat = _parse_coord_string(route_data.get("origin", "116.397389,39.908722"))
    except Exception:
        lon, lat = 116.397389, 39.908722

    sun_plan = _estimate_arrival_plan(
        distance_km=float(route_data.get("routes", [{}])[0].get("distance", 0)) / 1000 if route_data.get("routes") else 0,
        avg_speed_kmh=float(lifestyle.get("riding_speed_kmh", 18)),
        weather=weather,
        constraints=constraints,
    )

    bike_context = {}
    routes = route_data.get("routes", [])
    if routes:
        bike_context = routes[0].get("infra_context") or await _fetch_lane_context(routes[0].get("geometry", {}))

    if routes:
        top_route = routes[0]
        top_policy = top_route.get("policy", {}) or {}
        top_metrics = top_route.get("metrics", {}) or {}
        bike_context = {
            **(bike_context or {}),
            "cycleway_hits": max(
                int((bike_context or {}).get("cycleway_hits", 0) or 0),
                int(top_policy.get("cycleway_hits", 0) or 0),
                int(top_metrics.get("cycleway_hits", 0) or 0),
            ),
            "bike_friendly_hits": max(
                int((bike_context or {}).get("bike_friendly_hits", 0) or 0),
                int(top_policy.get("bike_friendly_hits", 0) or 0),
                int(top_metrics.get("bike_friendly_hits", 0) or 0),
            ),
            "primary_hits": max(
                int((bike_context or {}).get("primary_hits", 0) or 0),
                int(top_policy.get("primary_hits", 0) or 0),
                int(top_metrics.get("primary_road_hits", 0) or 0),
            ),
            "forbidden_hits": max(
                int((bike_context or {}).get("forbidden_hits", 0) or 0),
                int(top_policy.get("forbidden_hits", 0) or 0)
                + int(top_policy.get("hard_keyword_hits", 0) or 0),
                int(top_metrics.get("forbidden_road_hits", 0) or 0),
            ),
        }

    lifestyle["timing_advice"] = sun_plan
    lifestyle["bike_infra_advice"] = bike_context
    analysis_summary = dict(state.get("analysis_summary", {}))
    analysis_summary["timing_advice"] = sun_plan
    analysis_summary["bike_infra_advice"] = bike_context
    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][4]["status"] = "done"
        analysis_summary["agent_stack"][4]["detail"] = "已补充时间窗、风况和道路体验建议"
        analysis_summary["agent_stack"][5]["status"] = "running"
        analysis_summary["agent_stack"][5]["detail"] = "正在进行爬升、能耗和节奏推演"

    return {
        "lifestyle_context": lifestyle,
        "analysis_summary": analysis_summary,
        "messages": [{"role": "assistant", "content": "时间规划与道路偏好分析完成。"}],
    }


async def physical_simulation_node(state: GraphState):
    print("--- PHYSICAL SIMULATION NODE ---")
    route_payload = dict(state.get("route_data", {}))
    weather = state.get("weather_info", {})
    lifestyle = state.get("lifestyle_context", {})
    constraints = state.get("parsed_constraints", {})
    routes = route_payload.get("routes", [])
    if not routes:
        route_payload["routes"] = []
        return {"route_data": route_payload}

    wind_speed = float(weather.get("current", {}).get("wind_speed_10m", 0) or 0)
    avg_speed = float(lifestyle.get("riding_speed_kmh", 18) or 18)

    import asyncio

    lane_contexts = await asyncio.gather(
        *[
            asyncio.sleep(0, result=(route.get("infra_context") or {}))
            if route.get("infra_context")
            else _fetch_lane_context(route.get("geometry", {}))
            for route in routes
        ]
    )
    elevation_tasks = [
        _fetch_elevation_samples(_sample_geometry_points(route.get("geometry", {}), limit=24))
        for route in routes
    ]
    elevation_profiles = await asyncio.gather(*elevation_tasks)

    for idx, route in enumerate(routes):
        dist_km = round(float(route.get("distance", 0)) / 1000, 1)
        elevations = elevation_profiles[idx]
        climb_m = round(_compute_elevation_gain(elevations))
        lane = lane_contexts[idx]
        cycleway_score = lane.get("cycleway_hits", 0)
        bike_friendly_score = lane.get("bike_friendly_hits", 0)
        primary_penalty = lane.get("primary_hits", 0)
        trunk_penalty = (
            lane.get("fast_road_hits", 0)
            + int((route.get("policy", {}) or {}).get("soft_keyword_hits", 0) or 0)
            + int((route.get("policy", {}) or {}).get("profile_risk_hits", 0) or 0)
        )
        forbidden_penalty = (
            lane.get("forbidden_hits", 0)
            + int((route.get("policy", {}) or {}).get("hard_keyword_hits", 0) or 0)
        )

        est_hours = round(max(0.5, dist_km / max(avg_speed, 12) + climb_m / 900), 1)
        calories = round(dist_km * 28 + climb_m * 0.9)
        difficulty = round(
            dist_km * 0.55
            + climb_m / 70
            + wind_speed * 0.25
            + primary_penalty * 1.8
            + trunk_penalty * 3.2
            + forbidden_penalty * 12,
            1,
        )

        preference_bonus = cycleway_score * 1.6 + bike_friendly_score * 0.8
        if constraints.get("order_preference") == "climb_then_flat":
            preference_bonus += 1.5 if climb_m > 150 else 0
        if constraints.get("traffic_mode") == "avoid_motor_traffic":
            preference_bonus -= (primary_penalty * 1.2 + trunk_penalty * 2.2 + forbidden_penalty * 4)
        fallback_penalty = 10 if route.get("fallback_generated") else 0
        label = str(route.get("candidate_label") or "")
        candidate_bonus = 0
        if label == "主推荐":
            candidate_bonus += 8
        elif label in {"石门寺山海版", "海岸经典版", "东西环岛路版", "东强西松版", "滨海日落版", "山体外环版"}:
            candidate_bonus += 4
        elif label in {"反向环线", "节奏重排"}:
            candidate_bonus -= 6

        fit_score = round(
            100
            - difficulty * 1.55
            + preference_bonus * 4
            - primary_penalty * 3.5
            - trunk_penalty * 10
            - forbidden_penalty * 50,
            1,
        ) - fallback_penalty + candidate_bonus

        route["metrics"] = {
            "id": f"route_{idx}",
            "label": route.get("candidate_label") or ["均衡推荐", "强度优先", "轻松巡航"][idx % 3],
            "distance_km": dist_km,
            "climb_m": climb_m,
            "calories_kcal": calories,
            "est_hours": est_hours,
            "difficulty_score": difficulty,
            "wind_speed_kmh": round(wind_speed, 1),
            "cycleway_hits": cycleway_score,
            "bike_friendly_hits": bike_friendly_score,
            "primary_road_hits": primary_penalty,
            "trunk_road_hits": trunk_penalty,
            "forbidden_road_hits": forbidden_penalty,
            "policy_score": route.get("policy", {}).get("policy_score", 0),
            "fit_score": fit_score,
            "is_fallback": bool(route.get("fallback_generated")),
        }
        route["analysis"] = {
            "named_cycleways": lane.get("named_cycleways", []),
            "route_brief": _build_route_brief(route["metrics"], route_payload, constraints),
            "candidate_reason": route.get("candidate_reason", ""),
            "candidate_points": route.get("candidate_point_names", []),
            "segments": _segment_route(route)[:12],
            "policy_summary": route.get("policy", {}).get("summary", ""),
        }

    routes.sort(key=lambda item: item.get("metrics", {}).get("fit_score", 0), reverse=True)
    route_payload["routes"] = routes

    analysis_summary = dict(state.get("analysis_summary", {}))
    analysis_summary["route_overview"] = [
        {
            "id": route.get("metrics", {}).get("id"),
            "label": route.get("metrics", {}).get("label"),
            "brief": route.get("analysis", {}).get("route_brief"),
            "fit_score": route.get("metrics", {}).get("fit_score"),
            "candidate_reason": route.get("analysis", {}).get("candidate_reason", ""),
        }
        for route in routes[:5]
    ]
    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][5]["status"] = "done"
        analysis_summary["agent_stack"][5]["detail"] = "已完成爬升、能耗和节奏推演"
        analysis_summary["agent_stack"][6]["status"] = "running"
        analysis_summary["agent_stack"][6]["detail"] = "正在生成分段说明和关键道路摘要"

    return {"route_data": route_payload, "analysis_summary": analysis_summary}


async def explainability_node(state: GraphState):
    print("--- EXPLAINABILITY NODE ---")
    route_payload = dict(state.get("route_data", {}))
    routes = route_payload.get("routes", [])
    analysis_summary = dict(state.get("analysis_summary", {}))
    poi_elements = (state.get("poi_info", {}) or {}).get("elements", []) if isinstance(state.get("poi_info", {}), dict) else []
    weather = state.get("weather_info", {})
    if not routes:
        return {"route_data": route_payload, "analysis_summary": analysis_summary}

    for route in routes:
        route_analysis = route.get("analysis", {})
        segments = await _enrich_segments(route_analysis.get("segments", []), poi_elements, weather)
        route_analysis["segments"] = segments
        route_analysis["road_focus"] = _road_focus_from_segments(segments)
        route_analysis["segment_preview"] = [
            {
                "title": segment.get("title"),
                "road_name": segment.get("road_name"),
                "distance_km": segment.get("distance_km"),
                "supply_preview": segment.get("supply_preview"),
                "wind_label": segment.get("wind_label"),
            }
            for segment in segments[:5]
        ]
        route["analysis"] = route_analysis

    top_route = routes[0]
    top_analysis = top_route.get("analysis", {})
    analysis_summary["road_focus"] = top_analysis.get("road_focus", [])
    analysis_summary["segment_preview"] = top_analysis.get("segment_preview", [])
    analysis_summary["selected_route_policy"] = top_route.get("policy", {})
    analysis_summary["wind_explanation"] = {
        "outbound": (top_analysis.get("segments", [{}])[0] or {}).get("wind_label", "风况待定"),
        "return": (top_analysis.get("segments", [{}])[-1] or {}).get("wind_label", "风况待定"),
    }

    if analysis_summary.get("agent_stack"):
        analysis_summary["agent_stack"][6]["status"] = "done"
        analysis_summary["agent_stack"][6]["detail"] = "已生成分段说明、关键道路和地图阅读摘要"
        analysis_summary["agent_stack"][7]["status"] = "waiting"
        analysis_summary["agent_stack"][7]["detail"] = "等待用户确认路线后补充社区情报"

    return {
        "route_data": route_payload,
        "analysis_summary": analysis_summary,
        "messages": [{"role": "assistant", "content": "已生成路线解释层和关键道路摘要。"}],
    }


async def rag_node(state: GraphState):
    print("--- RAG NODE ---")
    route = state.get("route_data", {})
    intent = state.get("user_intent", "")
    warnings = list(state.get("safety_warnings", []))
    query = f"{route.get('origin_name', '')} {route.get('dest_name', '')} 骑行 封路 风险 补给"
    if not route.get("origin_name"):
        query = f"{intent} 骑行 风险 补给"

    try:
        import asyncio
        from duckduckgo_search import DDGS

        def _sync():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=4, region="cn-zh"))

        results = await asyncio.to_thread(_sync)
        for item in results:
            body = item.get("body", "")
            if body:
                warnings.append(f"🌐 联网情报：{body[:120]}")
        analysis_summary = dict(state.get("analysis_summary", {}))
        if analysis_summary.get("agent_stack"):
            analysis_summary["agent_stack"][7]["status"] = "done"
            analysis_summary["agent_stack"][7]["detail"] = "已补充社区风险、补给和封路相关情报"
        return {"safety_warnings": warnings, "analysis_summary": analysis_summary}
    except Exception:
        warnings.append("⚠️ 联网路况检索失败，请以实时导航为准。")
        analysis_summary = dict(state.get("analysis_summary", {}))
        if analysis_summary.get("agent_stack"):
            analysis_summary["agent_stack"][7]["status"] = "done"
            analysis_summary["agent_stack"][7]["detail"] = "RAG 检索失败，已自动降级为基础路况提示"
        return {"safety_warnings": warnings, "analysis_summary": analysis_summary}


async def safety_and_supply_node(state: GraphState):
    print("--- SAFETY & SUPPLY NODE ---")
    poi_data = state.get("poi_info", {})
    elements = poi_data.get("elements", []) if isinstance(poi_data, dict) else []
    warnings = list(state.get("safety_warnings", []))
    lifestyle = state.get("lifestyle_context", {})
    route = state.get("route_data", {})
    analysis_summary = dict(state.get("analysis_summary", {}))

    food = [p for p in elements if p.get("tags", {}).get("amenity") in {"restaurant", "cafe", "convenience"}]
    water = [p for p in elements if p.get("tags", {}).get("amenity") == "drinking_water"]
    view = [p for p in elements if p.get("tags", {}).get("tourism") == "viewpoint"]
    repair = [p for p in elements if p.get("tags", {}).get("shop") == "bicycle"]
    rest = [p for p in elements if p.get("tags", {}).get("amenity") in {"toilets", "bicycle_parking"}]

    if food:
        warnings.append("✅ 近距离补给点较充足，可中途安排咖啡或便利店停靠。")
    else:
        warnings.append("⚠️ 起点周边补给偏少，建议提前带足水和能量补给。")

    if lifestyle.get("timing_advice", {}).get("goal") == "sunset":
        warnings.append(
            f"🌅 建议 {lifestyle['timing_advice'].get('depart_time', '--')} 左右出发，"
            f"{lifestyle['timing_advice'].get('target_time', '--')} 前到达观景点。"
        )
    if route.get("routes"):
        metrics = route["routes"][0].get("metrics", {})
        if metrics.get("forbidden_road_hits", 0) > 0:
            warnings.append("⛔ 检测到高速、封闭或明确禁行道路，请务必改道，不要直接执行。")
        elif metrics.get("trunk_road_hits", 0) > 0 or metrics.get("primary_road_hits", 0) > 0:
            warnings.append("⚠️ 候选路线中存在主路、快速路、高架或隧道路段，建议结合现场路权和实时导航决定是否绕行。")

    if water:
        warnings.append("💧 路线上存在饮水点，可降低补给压力。")
    if view:
        warnings.append("📍 附近存在观景点，可作为休息或拍照停靠。")
    if repair:
        warnings.append("🛠️ 附近存在自行车相关商店，可作为应急维修备选。")
    if rest:
        warnings.append("🧭 路线上可找到厕所或停车点，休整条件相对友好。")

    analysis_summary["supply_detail"] = {
        "food": [item.get("tags", {}).get("name", "补给点") for item in food[:5]],
        "water": [item.get("tags", {}).get("name", "饮水点") for item in water[:5]],
        "scenic": [item.get("tags", {}).get("name", "观景点") for item in view[:5]],
        "repair": [item.get("tags", {}).get("name", "维修点") for item in repair[:5]],
        "rest": [item.get("tags", {}).get("name", "休整点") for item in rest[:5]],
    }

    return {"safety_warnings": warnings, "analysis_summary": analysis_summary}


async def finalizer_node(state: GraphState):
    print("--- FINALIZER NODE ---")
    from langchain_core.messages import HumanMessage

    route = state.get("route_data", {})
    weather = state.get("weather_info", {})
    pois = state.get("poi_info", {})
    warnings = state.get("safety_warnings", [])
    lifestyle = state.get("lifestyle_context", {})
    constraints = state.get("parsed_constraints", {})
    analysis_summary = state.get("analysis_summary", {})

    selected = route.get("routes", [{}])[0] if route.get("routes") else {}
    metrics = selected.get("metrics", {})
    analysis = selected.get("analysis", {})

    weather_current = weather.get("current", {})
    poi_names = [
        item.get("tags", {}).get("name", item.get("tags", {}).get("amenity", ""))
        for item in (pois.get("elements", []) if isinstance(pois, dict) else [])
    ][:10]

    prompt = f"""
请用中文输出一份真正可执行的骑行路书，避免空话。

用户原始需求：{state.get("user_intent", "")}
结构化约束：{json.dumps(constraints, ensure_ascii=False)}
规划摘要：{json.dumps(analysis_summary, ensure_ascii=False)}
路线基础信息：{json.dumps({
    "origin": route.get("origin_name", ""),
    "destination": route.get("dest_name", ""),
    "waypoints": route.get("waypoints_names", []),
    "route_notes": route.get("route_notes", ""),
}, ensure_ascii=False)}
选中方案指标：{json.dumps(metrics, ensure_ascii=False)}
路线分析：{json.dumps(analysis, ensure_ascii=False)}
天气：{json.dumps(weather_current, ensure_ascii=False)}
设施：{poi_names}
安全提示：{warnings[:8]}
时间建议：{json.dumps(lifestyle.get("timing_advice", {}), ensure_ascii=False)}

必须满足：
1. 明确说清楚这条路线是如何满足“先爬后平 / 看日落 / 自行车道优先 / 避开主路 / 禁用高速快速路”等约束的。
2. 给出一个简洁的出发建议时间。
3. 给出分段节奏建议，不要只说总里程。
4. 如果数据不充分，要明确写“建议现场以导航复核”。

Markdown 结构：
# 路线名称
## 为什么推荐这条
## 路线总览
## 分段骑行策略
## 时间与日落/日出规划
## 道路与风险提示
## 补给与停靠建议
## 出发前检查清单
"""

    try:
        content = llm.invoke([HumanMessage(content=prompt)]).content
    except Exception as exc:
        content = f"# 路书生成失败\n\n{exc}"

    return {"final_plan_markdown": content, "route_data": route}
