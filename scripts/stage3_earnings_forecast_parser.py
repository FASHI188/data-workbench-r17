#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation

UNIT = {"元":Decimal("1"),"万元":Decimal("10000"),"亿元":Decimal("100000000")}
NUM = r"-?\d[\d,]*(?:\.\d+)?"
PARENT_LABELS = (
    "归属于上市公司股东的净利润",
    "归属于母公司所有者的净利润",
    "归属于母公司股东的净利润",
    "归属于本公司股东的净利润",
    "归属于本行股东的净利润",
)


def norm(s:str)->str:
    return re.sub(r"\s+","",s or "").replace("－","-").replace("—","-").replace("–","-").replace("至","到")

def dec(s:str)->Decimal:
    return Decimal(s.replace(",",""))

def period(text:str)->str|None:
    t=norm(text)
    m=re.search(r"(20\d{2})年(年度|半年度|第一季度|前三季度|第三季度)",t)
    if not m:return None
    y=int(m.group(1));p=m.group(2)
    if p=="年度":return f"{y:04d}-12-31"
    if p=="半年度":return f"{y:04d}-06-30"
    if p=="第一季度":return f"{y:04d}-03-31"
    return f"{y:04d}-09-30"

@dataclass
class Forecast:
    status:str
    economic_date:str|None=None
    low_cny:str|None=None
    high_cny:str|None=None
    midpoint_cny:str|None=None
    unit:str|None=None
    sign_inference:str|None=None
    matched_label:str|None=None
    matched_text:str|None=None


def parse_parent_net_profit_forecast(text:str)->dict:
    t=norm(text);econ=period(t)
    best=None
    for label in PARENT_LABELS:
        start=0
        while True:
            i=t.find(label,start)
            if i<0:break
            # Short local window prevents accidentally using previous-year values later in the notice.
            w=t[i:i+220]
            # Explicit range with a shared or repeated unit.
            m=re.search(rf"(?:为|预计|盈利[:：]?|亏损[:：]?)?(?:人民币)?({NUM})(万元|亿元|元)?(?:到|~|～|-)(?:人民币)?({NUM})(万元|亿元|元)",w)
            if not m:
                # Common table form: 亏损：100万元-1,300万元
                m=re.search(rf"(?:盈利|亏损)[:：]({NUM})(万元|亿元|元)(?:到|~|～|-)?({NUM})(万元|亿元|元)",w)
            if m:
                a=dec(m.group(1));u1=m.group(2) or m.group(4);b=dec(m.group(3));u2=m.group(4) or u1
                if not u1 or not u2: start=i+len(label);continue
                ac=a*UNIT[u1];bc=b*UNIT[u2]
                cue=w[:max(m.end(),40)]
                sign="EXPLICIT_NUMERIC_SIGN"
                if "亏损" in cue and ac>=0 and bc>=0:
                    ac=-ac;bc=-bc;sign="LOSS_CUE_NEGATED_POSITIVE_MAGNITUDES"
                elif "盈利" in cue and ac>=0 and bc>=0:
                    sign="PROFIT_CUE_POSITIVE"
                lo=min(ac,bc);hi=max(ac,bc);mid=(lo+hi)/2
                cand=Forecast("FOUND",econ,str(lo),str(hi),str(mid),"CNY",sign,label,w[:m.end()+20])
                # Prefer an explicit numeric range closest to the label.
                best=cand;break
            # Single approximate point, only when the label window has a strong approx cue.
            m2=re.search(rf"(?:约|大约|预计)?(?:为)?(?:人民币)?({NUM})(万元|亿元|元)(?:左右)?",w)
            if m2 and any(x in w[:m2.end()+10] for x in ("约","大约","左右")):
                v=dec(m2.group(1))*UNIT[m2.group(2)];sign="EXPLICIT_NUMERIC_SIGN"
                if "亏损" in w[:m2.end()+10] and v>=0:v=-v;sign="LOSS_CUE_NEGATED_POSITIVE_MAGNITUDE"
                best=Forecast("FOUND_POINT_ESTIMATE",econ,str(v),str(v),str(v),"CNY",sign,label,w[:m2.end()+20]);break
            start=i+len(label)
        if best:break
    if not best:return asdict(Forecast("NOT_FOUND",econ))
    return asdict(best)


def compare_actual(forecast:dict, actual_cny:str)->dict:
    if forecast.get("status") not in ("FOUND","FOUND_POINT_ESTIMATE"):
        raise ValueError("forecast not usable")
    actual=Decimal(actual_cny);lo=Decimal(forecast["low_cny"]);hi=Decimal(forecast["high_cny"]);mid=Decimal(forecast["midpoint_cny"])
    if actual<lo:direction="BELOW_GUIDANCE_RANGE"
    elif actual>hi:direction="ABOVE_GUIDANCE_RANGE"
    else:direction="WITHIN_GUIDANCE_RANGE"
    width=hi-lo
    pos=str((actual-lo)/width) if width!=0 else None
    return {"actual_cny":str(actual),"forecast_low_cny":str(lo),"forecast_high_cny":str(hi),"forecast_midpoint_cny":str(mid),"surprise_cny":str(actual-mid),"range_position":pos,"surprise_direction":direction}
