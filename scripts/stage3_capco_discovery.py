#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASES = [
    "https://www.capco.org.cn/xhgg/hyfl/hyfljg/",
    "https://www.capco.org.cn/pub/zgssgsxh/xhgg/hyfl/hyfljg/",
]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def get(session: requests.Session, url: str) -> requests.Response:
    r=session.get(url,headers={"User-Agent":UA,"Referer":"https://www.capco.org.cn/"},timeout=90)
    r.raise_for_status()
    return r


def decode_html(raw: bytes) -> tuple[str,str]:
    cand=[]
    for enc in ("utf-8","gb18030","gbk"):
        try:
            text=raw.decode(enc)
            score=sum(text.count(x) for x in ("上市公司行业分类结果","行业分类结果","发布时间","按股票代码"))
            cand.append((score,enc,text))
        except Exception:
            pass
    if not cand:
        return raw.decode("latin1",errors="replace"),"latin1"
    cand.sort(key=lambda x:(x[0],x[1]=="utf-8"),reverse=True)
    return cand[0][2],cand[0][1]


def discover_publications(session: requests.Session) -> list[dict]:
    found:dict[str,dict]={}
    index_evidence=[]
    for base in BASES:
        for i in range(5):
            u=urljoin(base,"index.html" if i==0 else f"index_{i}.html")
            try:
                r=get(session,u);text,enc=decode_html(r.content);soup=BeautifulSoup(text,"html.parser");hits=0
                for a in soup.find_all("a",href=True):
                    title=" ".join(a.stripped_strings).strip()
                    if "上市公司行业分类结果" not in title:continue
                    detail=urljoin(r.url,a["href"]);found[detail]={"title":title,"detail_url":detail};hits+=1
                index_evidence.append({"requested_url":u,"final_url":r.url,"sha256":sha(r.content),"bytes":len(r.content),"decoded_as":enc,"classification_links_found":hits})
            except Exception:
                continue
    out=[]
    for detail,x in sorted(found.items()):
        r=get(session,detail);text,enc=decode_html(r.content);soup=BeautifulSoup(text,"html.parser");plain=" ".join(soup.stripped_strings)
        dm=re.search(r"发布时间[：:]?\s*(20\d{2})[-年](\d{1,2})[-月](\d{1,2})",plain) or re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})",plain)
        pub=f"{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
        pdfs=[];seen=set()
        for a in soup.find_all("a",href=True):
            href=urljoin(r.url,a["href"]);label=" ".join(a.stripped_strings).strip()
            if ".pdf" in href.lower() or "行业分类结果" in label or "按股票代码" in label:
                if href not in seen:seen.add(href);pdfs.append({"title":label,"url":href})
        preferred=[p for p in pdfs if "按股票代码" in p["title"]]
        if not preferred:preferred=[p for p in pdfs if "行业分类结果" in p["title"] and "按行业" not in p["title"]]
        if not preferred:preferred=pdfs
        out.append({**x,"publication_date":pub,"detail_final_url":r.url,"detail_sha256":sha(r.content),"detail_decoded_as":enc,"pdf_candidates":pdfs,"preferred_pdf":preferred[0] if preferred else None,"index_evidence":index_evidence})
    return out
