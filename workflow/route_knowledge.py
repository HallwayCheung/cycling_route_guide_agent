from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RoutePreset:
    key: str
    region_hint: str
    origin: str
    destination: str
    default_waypoints: list[str]
    climb_first_waypoints: list[str]
    flat_first_waypoints: list[str]
    aliases: list[str] = field(default_factory=list)
    cue_tokens: list[str] = field(default_factory=list)
    sunset_viewpoint: Optional[str] = None
    notes: Optional[str] = None
    community_summary: Optional[str] = None
    avoid_roads: list[str] = field(default_factory=list)
    community_variants: list["RouteVariant"] = field(default_factory=list)
    anchor_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    fallback_pois: list["KnownPOI"] = field(default_factory=list)


@dataclass
class RouteVariant:
    label: str
    waypoints: list[str]
    note: str


@dataclass
class KnownPOI:
    name: str
    lon: float
    lat: float
    tag_key: str
    tag_value: str


ROUTE_PRESETS: list[RoutePreset] = [
    RoutePreset(
        key="上海周边百公里",
        aliases=[
            "上海周边100km",
            "上海周围100km",
            "上海周边一百公里",
            "上海周围一百公里",
            "上海百公里骑行",
            "上海周边训练线",
            "上海郊区百公里",
            "上海青浦淀山湖百公里",
        ],
        cue_tokens=["上海", "青浦", "淀山湖", "佘山", "松江", "朱家角", "环湖", "百公里", "100km", "100公里", "训练"],
        region_hint="上海市青浦区淀山湖",
        origin="东方绿舟 上海市青浦区",
        destination="东方绿舟 上海市青浦区",
        default_waypoints=[
            "朱家角古镇 上海市青浦区",
            "金泽古镇 上海市青浦区",
            "练塘古镇 上海市青浦区",
            "松江大学城 上海市松江区",
            "佘山国家森林公园 上海市松江区",
            "辰山植物园 上海市松江区",
        ],
        climb_first_waypoints=[
            "佘山国家森林公园 上海市松江区",
            "辰山植物园 上海市松江区",
            "朱家角古镇 上海市青浦区",
            "环湖大道 上海市青浦区",
        ],
        flat_first_waypoints=[
            "朱家角古镇 上海市青浦区",
            "金泽古镇 上海市青浦区",
            "练塘古镇 上海市青浦区",
            "松江大学城 上海市松江区",
            "辰山植物园 上海市松江区",
            "佘山国家森林公园 上海市松江区",
        ],
        sunset_viewpoint="淀山湖日落观景点 上海市青浦区",
        notes="以上海西侧郊区常见骑行方向组织，避开市中心和高架快速路，适合百公里训练。",
        community_summary="上海周边百公里更适合放在青浦、淀山湖、朱家角、松江佘山一带组织，路网比市中心更适合巡航和补给。",
        avoid_roads=["沪渝高速", "沈海高速", "外环高速", "中环路", "高架", "快速路"],
        community_variants=[
            RouteVariant(
                label="青浦淀山湖版",
                waypoints=[
                    "朱家角古镇 上海市青浦区",
                    "淀山湖大道 上海市青浦区",
                    "环湖大道 上海市青浦区",
                    "东方绿舟 上海市青浦区",
                ],
                note="偏风景和巡航，围绕淀山湖与朱家角组织，路线更容易避开中心城区。",
            ),
            RouteVariant(
                label="青浦松江训练版",
                waypoints=[
                    "朱家角古镇 上海市青浦区",
                    "金泽古镇 上海市青浦区",
                    "练塘古镇 上海市青浦区",
                    "松江大学城 上海市松江区",
                    "佘山国家森林公园 上海市松江区",
                    "辰山植物园 上海市松江区",
                ],
                note="把松江佘山方向接入后距离更接近百公里，适合周末训练。",
            ),
        ],
        anchor_points={
            "东方绿舟 上海市青浦区": (121.0152, 31.1074),
            "朱家角古镇 上海市青浦区": (121.0480, 31.1075),
            "淀山湖大道 上海市青浦区": (121.0718, 31.1333),
            "环湖大道 上海市青浦区": (120.9715, 31.0820),
            "淀山湖日落观景点 上海市青浦区": (120.9576, 31.0810),
            "金泽古镇 上海市青浦区": (120.9138, 31.0430),
            "练塘古镇 上海市青浦区": (121.0070, 30.9997),
            "松江大学城 上海市松江区": (121.2155, 31.0538),
            "佘山国家森林公园 上海市松江区": (121.1930, 31.0961),
            "辰山植物园 上海市松江区": (121.1794, 31.0833),
        },
        fallback_pois=[
            KnownPOI("东方绿舟", 121.0152, 31.1074, "tourism", "attraction"),
            KnownPOI("朱家角古镇", 121.0480, 31.1075, "tourism", "attraction"),
            KnownPOI("淀山湖观景点", 120.9576, 31.0810, "tourism", "viewpoint"),
            KnownPOI("佘山国家森林公园", 121.1930, 31.0961, "leisure", "park"),
        ],
    ),
    RoutePreset(
        key="环大珠山",
        aliases=[
            "大珠山环线",
            "青岛环大珠山",
            "黄岛环大珠山",
            "大珠山一圈",
            "珠山环线",
            "大珠山绕圈",
            "珠山一圈",
            "石门寺环线",
            "珠山山海环线",
            "珠山海边环线",
            "大珠山山海环线",
            "石门寺珠山秀谷环线",
            "大珠山西海岸环线",
        ],
        cue_tokens=["大珠山", "珠山", "石门寺", "珠山秀谷", "山川路", "滨海大道", "映山红路", "三沙路", "高峪路", "海军路", "灵山湾"],
        region_hint="山东省青岛市黄岛区大珠山",
        origin="大珠山风景区石门寺游客中心 青岛市黄岛区",
        destination="大珠山风景区石门寺游客中心 青岛市黄岛区",
        default_waypoints=["珠山秀谷景区 青岛市黄岛区", "山川路 青岛市黄岛区", "滨海大道 青岛市黄岛区"],
        climb_first_waypoints=["珠山秀谷景区 青岛市黄岛区", "山川路 青岛市黄岛区", "滨海大道 青岛市黄岛区"],
        flat_first_waypoints=["滨海大道 青岛市黄岛区", "山川路 青岛市黄岛区", "珠山秀谷景区 青岛市黄岛区"],
        sunset_viewpoint="滨海大道西海岸观景段 青岛市黄岛区",
        notes="适合通过先山后海的顺序满足先爬升后放松的骑行偏好。",
        community_summary="常见走法会从石门寺或大珠山地铁站附近集结，经山川路上山，再接滨海大道做山海收尾。",
        avoid_roads=["204国道", "疏港高速", "高架", "快速路"],
        community_variants=[
            RouteVariant(
                label="石门寺山海版",
                waypoints=["珠山秀谷景区 青岛市黄岛区", "山川路 青岛市黄岛区", "滨海大道 青岛市黄岛区"],
                note="更贴近本地骑友常说的山海小环，先上山再回海边。",
            ),
            RouteVariant(
                label="滨海日落版",
                waypoints=["珠山秀谷景区 青岛市黄岛区", "山川路 青岛市黄岛区", "滨海大道 青岛市黄岛区", "滨海大道西海岸观景段 青岛市黄岛区"],
                note="把观景点放到后程，适合海边看日落后回收。",
            ),
            RouteVariant(
                label="山体外环版",
                waypoints=[
                    "三沙路 青岛市黄岛区",
                    "高峪路 青岛市黄岛区",
                    "海军路 青岛市黄岛区",
                    "珠山秀谷景区 青岛市黄岛区",
                    "滨海大道西海岸观景段 青岛市黄岛区",
                ],
                note="参考大珠山外圈道路组织更完整的一圈，更接近能看清楚具体走哪些路的山海环线。",
            ),
        ],
        anchor_points={
            "大珠山风景区石门寺游客中心 青岛市黄岛区": (120.0358, 35.7426),
            "大珠山景区南麓入口 青岛市黄岛区": (120.0438, 35.7344),
            "珠山秀谷景区 青岛市黄岛区": (120.0768, 35.7762),
            "山川路 青岛市黄岛区": (120.0688, 35.7662),
            "滨海大道 青岛市黄岛区": (120.0186, 35.7034),
            "滨海大道西海岸观景段 青岛市黄岛区": (120.0146, 35.6978),
            "三沙路 青岛市黄岛区": (120.0227, 35.7683),
            "高峪路 青岛市黄岛区": (120.0242, 35.7762),
            "海军路 青岛市黄岛区": (120.0359, 35.7825),
            "灵山湾观景段 青岛市黄岛区": (120.0195, 35.7350),
        },
        fallback_pois=[
            KnownPOI("石门寺游客中心", 120.0358, 35.7426, "tourism", "attraction"),
            KnownPOI("珠山秀谷景区", 120.0768, 35.7762, "tourism", "attraction"),
            KnownPOI("山川路补给点", 120.0688, 35.7662, "amenity", "convenience"),
            KnownPOI("滨海大道观景段", 120.0146, 35.6978, "tourism", "viewpoint"),
            KnownPOI("西海岸休整点", 120.0189, 35.7045, "amenity", "toilets"),
            KnownPOI("灵山湾观景段", 120.0195, 35.7350, "tourism", "viewpoint"),
            KnownPOI("大珠山外环补给", 120.0246, 35.7699, "shop", "supermarket"),
        ],
    ),
    RoutePreset(
        key="黄岛东西环岛",
        aliases=[
            "黄岛环岛",
            "青岛黄岛东西环岛",
            "黄岛东西海岸环线",
            "黄岛东西环线",
            "黄岛东西一圈",
            "黄岛东线西线环",
            "西海岸东西环线",
            "黄岛海岸环线",
            "黄岛东西大环",
            "黄岛东西大环线",
            "黄岛东西岸一圈",
            "黄岛东环西环一圈",
            "凤凰岛唐岛湾环线",
            "金沙滩唐岛湾环线",
            "西海岸环岛",
            "西海岸大环",
        ],
        cue_tokens=["黄岛", "西海岸", "唐岛湾", "金沙滩", "银沙滩", "鱼鸣嘴", "凤凰岛", "琅琊台", "东西", "东环岛路", "西环岛路", "连三岛", "陈姑庙", "甘水湾"],
        region_hint="山东省青岛市黄岛区",
        origin="金沙滩啤酒城 青岛市黄岛区",
        destination="金沙滩啤酒城 青岛市黄岛区",
        default_waypoints=["银沙滩 青岛市黄岛区", "唐岛湾滨海公园 青岛市黄岛区", "大珠山景区南麓入口 青岛市黄岛区", "琅琊台路沿海段 青岛市黄岛区"],
        climb_first_waypoints=["大珠山景区南麓入口 青岛市黄岛区", "琅琊台路沿海段 青岛市黄岛区", "唐岛湾滨海公园 青岛市黄岛区", "银沙滩 青岛市黄岛区"],
        flat_first_waypoints=["银沙滩 青岛市黄岛区", "唐岛湾滨海公园 青岛市黄岛区", "琅琊台路沿海段 青岛市黄岛区", "大珠山景区南麓入口 青岛市黄岛区"],
        sunset_viewpoint="鱼鸣嘴村观景平台 青岛市黄岛区",
        notes="东侧更适合安排爬升段，西侧滨海更适合日落和平路收尾。",
        community_summary="更像骑友口中的西海岸大环线，常见说法会把东环岛路、西环岛路、唐岛湾滨海骑行道连成一整圈，再串鱼鸣嘴和银沙滩。",
        avoid_roads=["疏港高速", "前湾港路快速路", "高架", "快速路"],
        community_variants=[
            RouteVariant(
                label="海岸经典版",
                waypoints=[
                    "银沙滩 青岛市黄岛区",
                    "唐岛湾滨海公园 青岛市黄岛区",
                    "鱼鸣嘴村观景平台 青岛市黄岛区",
                    "大珠山景区南麓入口 青岛市黄岛区",
                    "琅琊台路沿海段 青岛市黄岛区",
                ],
                note="先走东侧成熟骑行道和海湾观景段，再拉到西侧形成完整的大环。",
            ),
            RouteVariant(
                label="东西环岛路版",
                waypoints=[
                    "金沙滩 青岛市黄岛区",
                    "唐岛湾滨海公园 青岛市黄岛区",
                    "银沙滩 青岛市黄岛区",
                    "鱼鸣嘴村观景平台 青岛市黄岛区",
                ],
                note="按当地更常说的东环岛路 + 西环岛路思路组织，优先贴着海岸慢行系统走。",
            ),
            RouteVariant(
                label="东强西松版",
                waypoints=[
                    "唐岛湾滨海公园 青岛市黄岛区",
                    "大珠山景区南麓入口 青岛市黄岛区",
                    "鱼鸣嘴村观景平台 青岛市黄岛区",
                    "银沙滩 青岛市黄岛区",
                ],
                note="把爬升和起伏放在前段，后半程回到海边更利于巡航收尾。",
            ),
        ],
        anchor_points={
            "金沙滩啤酒城 青岛市黄岛区": (120.2009, 35.9642),
            "银沙滩 青岛市黄岛区": (120.2006, 35.9237),
            "唐岛湾滨海公园 青岛市黄岛区": (120.1782, 35.9556),
            "鱼鸣嘴村观景平台 青岛市黄岛区": (120.0584, 35.8155),
            "大珠山景区南麓入口 青岛市黄岛区": (120.0438, 35.7344),
            "琅琊台路沿海段 青岛市黄岛区": (119.9624, 35.7388),
        },
        fallback_pois=[
            KnownPOI("金沙滩啤酒城", 120.2009, 35.9642, "tourism", "attraction"),
            KnownPOI("唐岛湾滨海公园", 120.1782, 35.9556, "leisure", "park"),
            KnownPOI("银沙滩游客服务点", 120.2006, 35.9237, "amenity", "convenience"),
            KnownPOI("鱼鸣嘴观景平台", 120.0584, 35.8155, "tourism", "viewpoint"),
            KnownPOI("西海岸骑行补水点", 120.1791, 35.9532, "amenity", "drinking_water"),
            KnownPOI("沿海公厕", 120.1812, 35.9514, "amenity", "toilets"),
        ],
    ),
    RoutePreset(
        key="环崂山",
        aliases=["崂山环线", "青岛崂山环线", "崂山一圈", "崂山绕圈"],
        cue_tokens=["崂山", "仰口", "流清河", "青山渔村"],
        region_hint="山东省青岛市崂山区",
        origin="仰口游客服务中心 青岛市崂山区",
        destination="仰口游客服务中心 青岛市崂山区",
        default_waypoints=["流清河景区 青岛市崂山区", "青山渔村 青岛市崂山区", "仰口海滩 青岛市崂山区"],
        climb_first_waypoints=["流清河景区 青岛市崂山区", "青山渔村 青岛市崂山区", "仰口海滩 青岛市崂山区"],
        flat_first_waypoints=["仰口海滩 青岛市崂山区", "青山渔村 青岛市崂山区", "流清河景区 青岛市崂山区"],
        sunset_viewpoint="青山渔村观景台 青岛市崂山区",
        notes="兼顾海景与山路，是典型的青岛进阶骑行路线。",
    ),
    RoutePreset(
        key="环千岛湖",
        aliases=["千岛湖环湖", "淳安千岛湖环线", "千岛湖一圈"],
        cue_tokens=["千岛湖", "界首", "文渊狮城", "上江埠"],
        region_hint="浙江省杭州市淳安县千岛湖",
        origin="千岛湖广场 杭州市淳安县",
        destination="千岛湖广场 杭州市淳安县",
        default_waypoints=["上江埠大桥 杭州市淳安县", "界首乡 杭州市淳安县", "文渊狮城 杭州市淳安县"],
        climb_first_waypoints=["文渊狮城 杭州市淳安县", "界首乡 杭州市淳安县", "上江埠大桥 杭州市淳安县"],
        flat_first_waypoints=["上江埠大桥 杭州市淳安县", "界首乡 杭州市淳安县", "文渊狮城 杭州市淳安县"],
        sunset_viewpoint="千岛湖天屿山观景台 杭州市淳安县",
        notes="适合长距离耐力骑行，风景资源丰富，补给点相对稳定。",
    ),
    RoutePreset(
        key="环滇池",
        aliases=["滇池环湖", "昆明环滇", "滇池一圈"],
        cue_tokens=["滇池", "海埂", "捞鱼河", "晋宁", "海口林场"],
        region_hint="云南省昆明市滇池",
        origin="海埂大坝 昆明市西山区",
        destination="海埂大坝 昆明市西山区",
        default_waypoints=["捞鱼河湿地公园 昆明市呈贡区", "晋宁南滇池国家湿地 昆明市晋宁区", "海口林场 昆明市西山区"],
        climb_first_waypoints=["海口林场 昆明市西山区", "晋宁南滇池国家湿地 昆明市晋宁区", "捞鱼河湿地公园 昆明市呈贡区"],
        flat_first_waypoints=["捞鱼河湿地公园 昆明市呈贡区", "晋宁南滇池国家湿地 昆明市晋宁区", "海口林场 昆明市西山区"],
        sunset_viewpoint="海埂大坝观景段 昆明市西山区",
        notes="非常适合看湖景与晚霞，风大时需要控制侧风风险。",
    ),
    RoutePreset(
        key="环东湖",
        aliases=["东湖绿道", "武汉东湖环线", "东湖一圈"],
        cue_tokens=["东湖", "梨园", "磨山", "落雁", "白马洲头"],
        region_hint="湖北省武汉市东湖风景区",
        origin="梨园广场 武汉市武昌区",
        destination="梨园广场 武汉市武昌区",
        default_waypoints=["磨山景区 武汉市东湖风景区", "落雁景区 武汉市东湖风景区", "白马洲头 武汉市东湖风景区"],
        climb_first_waypoints=["磨山景区 武汉市东湖风景区", "落雁景区 武汉市东湖风景区", "白马洲头 武汉市东湖风景区"],
        flat_first_waypoints=["白马洲头 武汉市东湖风景区", "落雁景区 武汉市东湖风景区", "磨山景区 武汉市东湖风景区"],
        sunset_viewpoint="白马洲头 武汉市东湖风景区",
        notes="适合城市骑行和景观巡航，绿道资源较好。",
    ),
    RoutePreset(
        key="环玄武湖",
        aliases=["玄武湖一圈", "南京玄武湖环线", "玄武湖环线"],
        cue_tokens=["玄武湖", "玄武门", "情侣园", "太阳宫"],
        region_hint="江苏省南京市玄武湖",
        origin="玄武门 南京市玄武区",
        destination="玄武门 南京市玄武区",
        default_waypoints=["情侣园 南京市玄武区", "和平门 南京市玄武区", "太阳宫 南京市玄武区"],
        climb_first_waypoints=["和平门 南京市玄武区", "太阳宫 南京市玄武区", "情侣园 南京市玄武区"],
        flat_first_waypoints=["情侣园 南京市玄武区", "太阳宫 南京市玄武区", "和平门 南京市玄武区"],
        sunset_viewpoint="玄武湖梁洲观景区 南京市玄武区",
        notes="适合轻松巡航与夜景体验，也适合手动追加城市地标途经。",
    ),
]


REWRITE_MAP = {
    "西海岸新区": "黄岛",
    "青岛西海岸": "黄岛",
    "黄岛区": "黄岛",
    "大珠山景区": "大珠山",
    "唐岛湾公园": "唐岛湾",
    "唐岛湾滨海公园": "唐岛湾",
    "东西海岸": "东西",
    "东西岸": "东西",
    "东线西线": "东西环线",
    "东环西环": "东西环线",
    "西海岸大环": "黄岛东西环岛",
    "西海岸环岛": "黄岛东西环岛",
    "凤凰岛唐岛湾": "黄岛东西环岛",
    "环湖一圈": "环湖",
}


def normalize_route_text(text: str) -> str:
    normalized = (text or "").lower()
    normalized = re.sub(r"[，。、“”‘’：:；;,.!?？!（）()【】\\[\\]\\-_/\\\\]+", "", normalized)
    normalized = normalized.replace("骑车", "骑行").replace("单车", "骑行").replace("公路车", "骑行")
    normalized = normalized.replace("绕一圈", "一圈").replace("兜一圈", "一圈")
    normalized = normalized.replace("顺一圈", "环线").replace("跑一圈", "一圈")
    normalized = normalized.replace("东西大环", "东西环线").replace("东西小环", "东西环线")
    for source, target in REWRITE_MAP.items():
        normalized = normalized.replace(source.lower(), target.lower())
    return normalized.replace(" ", "")


def _route_score(preset: RoutePreset, text: str) -> tuple[int, int]:
    score = 0
    matched_alias_length = 0

    candidates = [preset.key, *preset.aliases]
    for alias in candidates:
        alias_text = normalize_route_text(alias)
        if alias_text and alias_text in text:
            score += 100 + len(alias_text)
            matched_alias_length = max(matched_alias_length, len(alias_text))

    cue_hits = 0
    for token in preset.cue_tokens:
        token_text = normalize_route_text(token)
        if token_text and token_text in text:
            cue_hits += 1

    score += cue_hits * 16

    if "环" in text or "环线" in text or "一圈" in text:
        score += 8
    if preset.key == "黄岛东西环岛":
        if "黄岛" in text or "西海岸" in text:
            score += 20
        if "东西" in text:
            score += 20
        if "环岛" in text or "环线" in text or "一圈" in text:
            score += 14
    if preset.key == "环大珠山":
        if "大珠山" in text or "珠山" in text:
            score += 26
        if "环" in text or "一圈" in text:
            score += 12
    if preset.key == "上海周边百公里":
        if "上海" in text:
            score += 34
        if any(token in text for token in ["周边", "周围", "郊区", "附近"]):
            score += 18
        if any(token in text for token in ["100km", "100公里", "百公里", "一百公里"]):
            score += 34
        if any(token in text for token in ["训练", "风景", "少走大车", "少车"]):
            score += 8
    return score, matched_alias_length


def detect_route_preset(intent: str) -> Optional[RoutePreset]:
    text = normalize_route_text(intent)
    if not text:
        return None

    ranked: list[tuple[int, int, RoutePreset]] = []
    for preset in ROUTE_PRESETS:
        score, matched_alias_length = _route_score(preset, text)
        ranked.append((score, matched_alias_length, preset))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best_score, _, best_preset = ranked[0]
    if best_score >= 60:
        return best_preset

    if "黄岛" in text and ("东西" in text or "东线" in text or "西线" in text) and ("环岛" in text or "环线" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "黄岛东西环岛"), None)
    if ("大珠山" in text or "珠山" in text) and ("环" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "环大珠山"), None)
    if "上海" in text and (
        any(token in text for token in ["100km", "100公里", "百公里", "一百公里"])
        or any(token in text for token in ["周边", "周围", "郊区"])
    ):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "上海周边百公里"), None)
    if "崂山" in text and ("环" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "环崂山"), None)
    if "千岛湖" in text and ("环" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "环千岛湖"), None)
    if "滇池" in text and ("环" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "环滇池"), None)
    if "东湖" in text and ("环" in text or "绿道" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "环东湖"), None)
    if "玄武湖" in text and ("环" in text or "一圈" in text):
        return next((preset for preset in ROUTE_PRESETS if preset.key == "环玄武湖"), None)
    return None


def choose_waypoints(preset: RoutePreset, order_preference: Optional[str] = None) -> list[str]:
    if order_preference == "climb_then_flat":
        return preset.climb_first_waypoints
    if order_preference == "flat_then_climb":
        return preset.flat_first_waypoints
    return preset.default_waypoints


def build_preset_variants(
    preset: RoutePreset,
    order_preference: Optional[str] = None,
    wants_sunset: bool = False,
) -> list[RouteVariant]:
    variants: list[RouteVariant] = [
        RouteVariant(
            label="主推荐",
            waypoints=choose_waypoints(preset, order_preference),
            note=preset.notes or preset.community_summary or "按预设骨架生成的推荐路线。",
        )
    ]
    variants.extend(preset.community_variants)

    if wants_sunset and preset.sunset_viewpoint:
        sunset_waypoints = choose_waypoints(preset, order_preference)
        if preset.sunset_viewpoint not in sunset_waypoints:
            sunset_waypoints = [*sunset_waypoints, preset.sunset_viewpoint]
        variants.append(
            RouteVariant(
                label="日落观景版",
                waypoints=sunset_waypoints,
                note=f"把 {preset.sunset_viewpoint} 放在后段，方便按日落时间收尾。",
            )
        )

    deduped: list[RouteVariant] = []
    seen = set()
    for variant in variants:
        key = tuple(normalize_route_text(name) for name in variant.waypoints if name)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def lookup_anchor_point(preset: RoutePreset | None, name: str) -> tuple[float, float] | None:
    if not preset or not name:
        return None
    normalized = normalize_route_text(name)
    for key, value in preset.anchor_points.items():
        if normalize_route_text(key) == normalized:
            return value
    return None


def get_route_preset(key: str | None) -> Optional[RoutePreset]:
    if not key:
        return None
    return next((preset for preset in ROUTE_PRESETS if preset.key == key), None)
