from __future__ import annotations


THEME_SECTORS = [
    {
        "sector_id": "cpo",
        "sector_name": "CPO/光模块",
        "branch": "光模块",
        "category": "ai_compute",
        "keywords": ["AI", "算力", "CPO", "光模块", "英伟达"],
        "stocks": [
            ("300308", "中际旭创"),
            ("300502", "新易盛"),
            ("300394", "天孚通信"),
            ("300548", "博创科技"),
            ("300570", "太辰光"),
            ("300620", "光库科技"),
        ],
        "catalysts": ["AI算力资本开支", "高速光模块需求"],
    },
    {
        "sector_id": "pcb",
        "sector_name": "PCB",
        "branch": "PCB",
        "category": "ai_compute",
        "keywords": ["AI", "算力", "PCB", "服务器"],
        "stocks": [
            ("002463", "沪电股份"),
            ("300476", "胜宏科技"),
            ("002916", "深南电路"),
            ("603228", "景旺电子"),
            ("002436", "兴森科技"),
        ],
        "catalysts": ["AI服务器高速板需求"],
    },
    {
        "sector_id": "server",
        "sector_name": "服务器/国产算力",
        "branch": "服务器",
        "category": "ai_compute",
        "keywords": ["AI", "算力", "服务器", "国产算力"],
        "stocks": [
            ("601138", "工业富联"),
            ("000977", "浪潮信息"),
            ("603019", "中科曙光"),
            ("000938", "紫光股份"),
            ("002281", "光迅科技"),
        ],
        "catalysts": ["AI服务器订单", "国产算力替代"],
    },
    {
        "sector_id": "rare_earth",
        "sector_name": "稀土永磁",
        "branch": "稀土",
        "category": "resource_price",
        "keywords": ["资源", "涨价", "稀土", "小金属"],
        "stocks": [
            ("600111", "北方稀土"),
            ("600392", "盛和资源"),
            ("000831", "中国稀土"),
            ("000970", "中科三环"),
            ("300748", "金力永磁"),
        ],
        "catalysts": ["稀土价格变化", "供需收紧预期"],
    },
    {
        "sector_id": "lithium",
        "sector_name": "锂矿",
        "branch": "锂矿",
        "category": "resource_price",
        "keywords": ["资源", "锂", "涨价", "新能源"],
        "stocks": [
            ("002466", "天齐锂业"),
            ("002460", "赣锋锂业"),
            ("002756", "永兴材料"),
            ("000792", "盐湖股份"),
            ("002738", "中矿资源"),
        ],
        "catalysts": ["碳酸锂价格波动", "新能源链反弹"],
    },
    {
        "sector_id": "industrial_gas",
        "sector_name": "工业气体",
        "branch": "工业气体",
        "category": "resource_price",
        "keywords": ["工业气体", "氦气", "涨价", "资源"],
        "stocks": [
            ("002430", "杭氧股份"),
            ("688106", "金宏气体"),
            ("301286", "侨源股份"),
            ("688146", "中船特气"),
        ],
        "catalysts": ["工业气体价格变化", "半导体材料需求"],
    },
    {
        "sector_id": "power",
        "sector_name": "电力",
        "branch": "电力",
        "category": "defensive_yield",
        "keywords": ["电力", "公用事业", "高股息", "防御"],
        "stocks": [
            ("600900", "长江电力"),
            ("600011", "华能国际"),
            ("600795", "国电电力"),
            ("600027", "华电国际"),
            ("003816", "中国广核"),
        ],
        "catalysts": ["高股息风格", "公用事业防御"],
    },
    {
        "sector_id": "coal",
        "sector_name": "煤炭",
        "branch": "煤炭",
        "category": "defensive_yield",
        "keywords": ["煤炭", "高股息", "资源", "防御"],
        "stocks": [
            ("601088", "中国神华"),
            ("601225", "陕西煤业"),
            ("600188", "兖矿能源"),
            ("601898", "中煤能源"),
            ("600546", "山煤国际"),
        ],
        "catalysts": ["红利资产配置", "能源价格"],
    },
    {
        "sector_id": "low_altitude",
        "sector_name": "低空经济",
        "branch": "eVTOL",
        "category": "low_altitude",
        "keywords": ["低空经济", "eVTOL", "无人机", "空管"],
        "stocks": [
            ("002085", "万丰奥威"),
            ("001696", "宗申动力"),
            ("000099", "中信海直"),
            ("300424", "航新科技"),
            ("300900", "广联航空"),
        ],
        "catalysts": ["低空经济政策", "eVTOL产业进展"],
    },
    {
        "sector_id": "ai_app",
        "sector_name": "AI应用",
        "branch": "AI应用",
        "category": "ai_application",
        "keywords": ["AI", "应用", "传媒", "游戏", "智能体"],
        "stocks": [
            ("300418", "昆仑万维"),
            ("002555", "三七互娱"),
            ("002230", "科大讯飞"),
            ("300033", "同花顺"),
            ("300364", "中文在线"),
        ],
        "catalysts": ["多模态应用", "智能体产品迭代"],
    },
    {
        "sector_id": "medicine",
        "sector_name": "医药复苏",
        "branch": "创新药/CXO",
        "category": "medicine_recovery",
        "keywords": ["医药", "创新药", "CXO", "减肥药"],
        "stocks": [
            ("603259", "药明康德"),
            ("300760", "迈瑞医疗"),
            ("300015", "爱尔眼科"),
            ("300347", "泰格医药"),
            ("600276", "恒瑞医药"),
        ],
        "catalysts": ["创新药政策", "医药估值修复"],
    },
]


CATEGORY_LABELS = {
    "ai_compute": "AI硬件/算力基础设施",
    "resource_price": "资源涨价",
    "defensive_yield": "防御红利",
    "low_altitude": "低空经济",
    "ai_application": "AI应用",
    "medicine_recovery": "医药复苏",
}


WATCHLIST = [
    {"ts_code": "300308.SZ", "symbol": "300308", "name": "中际旭创"},
    {"ts_code": "002463.SZ", "symbol": "002463", "name": "沪电股份"},
    {"ts_code": "600111.SH", "symbol": "600111", "name": "北方稀土"},
    {"ts_code": "002085.SZ", "symbol": "002085", "name": "万丰奥威"},
]


PORTFOLIO = [
    {"ts_code": "300308.SZ", "symbol": "300308", "name": "中际旭创", "quantity": 200, "cost_price": 162.8},
    {"ts_code": "600111.SH", "symbol": "600111", "name": "北方稀土", "quantity": 800, "cost_price": 19.6},
    {"ts_code": "002085.SZ", "symbol": "002085", "name": "万丰奥威", "quantity": 500, "cost_price": 15.2},
]

