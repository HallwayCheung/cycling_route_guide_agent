import os
import json
import httpx
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from dotenv import load_dotenv

load_dotenv()

server = Server("cycling-agent-mcp-free")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_cycling_route",
            description="Get free cycling directions using OSRM (OpenStreetMap). Use lon,lat coordinates or a full semicolon-separated coordinate sequence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "lon,lat (e.g. 116.4,39.9)"},
                    "destination": {"type": "string", "description": "lon,lat"},
                    "coords_sequence": {"type": "string", "description": "Optional full OSRM coordinate sequence: lon,lat;lon,lat;..."},
                    "allow_driving_fallback": {"type": "boolean", "default": True},
                },
                "required": []
            }
        ),
        Tool(
            name="get_weather",
            description="Get real-time weather using Open-Meteo (No API Key required).",
            inputSchema={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                },
                "required": ["lat", "lon"]
            }
        ),
        Tool(
            name="search_pois_osm",
            description="Search for restaurants/cafes/shops nearby using OpenStreetMap Overpass API.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "radius": {"type": "integer", "default": 1000}
                },
                "required": ["lat", "lon"]
            }
        ),
        Tool(
            name="get_elevation",
            description="Get elevation (height above sea level) for a coordinate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "points": {
                        "type": "array",
                        "description": "Optional batch points, each item has lat and lon.",
                        "items": {
                            "type": "object",
                            "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
                            "required": ["lat", "lon"],
                        },
                    },
                },
                "required": []
            }
        )
    ]

@server.call_tool()
async def call_tool(name, arguments):
    async with httpx.AsyncClient(timeout=10.0) as client:
        if name == "get_cycling_route":
            # OSRM Public API
            coords_sequence = arguments.get("coords_sequence")
            if not coords_sequence:
                origin = arguments["origin"]
                dest = arguments["destination"]
                coords_sequence = f"{origin};{dest}"
            profiles = ["bicycle"] + (["driving"] if arguments.get("allow_driving_fallback", True) else [])
            last_error = None
            
            for profile in profiles:
                url = (
                    f"http://router.project-osrm.org/route/v1/{profile}/{coords_sequence}"
                    "?overview=full&geometries=geojson&alternatives=3&steps=true&annotations=false"
                )
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    payload = resp.json()
                    payload["_profile"] = profile
                    if payload.get("routes"):
                        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]
                    last_error = f"{profile}: empty routes"
                except Exception as e:
                    last_error = str(e)
                    continue
            return [TextContent(type="text", text=json.dumps({"routes": [], "error": last_error or "Routing Error"}, ensure_ascii=False))]

        elif name == "get_weather":
            # Open-Meteo
            lat, lon = arguments["lat"], arguments["lon"]
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,wind_speed_10m,wind_direction_10m,precipitation"
                "&daily=sunrise,sunset&timezone=auto&forecast_days=2"
            )
            
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False))]
            except Exception as e:
                return [TextContent(type="text", text=f"Weather Error: {str(e)}")]

        elif name == "search_pois_osm":
            # Overpass API
            lat, lon = arguments["lat"], arguments["lon"]
            radius = arguments.get("radius", 1000)
            
            # Query for restaurants and cafes
            overpass_query = f"""
            [out:json][timeout:18];
            (
              node(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|convenience|bicycle_parking|drinking_water|toilets|pharmacy|hospital|fuel"];
              node(around:{radius},{lat},{lon})["shop"~"bicycle|sports|supermarket"];
              node(around:{radius},{lat},{lon})["tourism"~"viewpoint|attraction"];
              node(around:{radius},{lat},{lon})["leisure"~"park|fitness_station"];
            );
            out 40;
            """
            url = "https://overpass-api.de/api/interpreter"
            
            try:
                resp = await client.post(url, data={"data": overpass_query})
                resp.raise_for_status()
                return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False))]
            except Exception as e:
                return [TextContent(type="text", text=f"POI Error: {str(e)}")]

        elif name == "get_elevation":
            # Open-Elevation
            points = arguments.get("points")
            if points:
                locations = "|".join(f"{point['lat']},{point['lon']}" for point in points)
            else:
                lat, lon = arguments["lat"], arguments["lon"]
                locations = f"{lat},{lon}"
            url = f"https://api.open-elevation.com/api/v1/lookup?locations={locations}"
            
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return [TextContent(type="text", text=json.dumps(resp.json(), ensure_ascii=False))]
            except Exception as e:
                # Fallback to a mock/zero if service is down
                return [TextContent(type="text", text=json.dumps({"results": [{"elevation": 0}]}, ensure_ascii=False))]

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
