import requests
from bs4 import BeautifulSoup

from flask import Flask, render_template,request, make_response, jsonify
from datetime import datetime

import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types

if os.path.exists('serviceAccountKey.json'):
    cred = credentials.Certificate('serviceAccountKey.json')
else:
    firebase_config = os.getenv('FIREBASE_CONFIG')
    cred_dict = json.loads(firebase_config)
    cred = credentials.Certificate(cred_dict)

firebase_admin.initialize_app(cred)

app = Flask(__name__)

client = genai.Client()

@app.route("/fiftylan_news")
def fiftylan_news():
    # 50嵐 最新消息
    url = "http://50lan.com/web/news.asp"
    
    # ⚠️ 50嵐必加 Headers，否則網站會直接拒絕連線 (回傳 403)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    Data = requests.get(url, headers=headers)
    Data.encoding = "utf-8"
    
    sp = BeautifulSoup(Data.text, "html.parser")
    
    # 50嵐網頁沒有任何 class。觀察後發現，所有新聞列表都包在「沒有任何屬性」的 <tr> 裡面
    # 這裡我們先撈出所有的 tr
    all_rows = sp.find_all("tr")
    
    count = 0
    
    for x in all_rows:
        # 檢查這一列裡面有沒有超連結 <a>，沒有的話代表是空白列或標頭，直接跳過
        a_tag = x.find("a")
        if a_tag is None:
            continue
            
        # 1. 抓取標題
        title = a_tag.text.strip()
        
        # 2. 抓取新聞 ID 與 超連結
        # 50嵐的 href 長這樣: "news_detail.asp?id=38"
        href = a_tag.get("href")
        news_id = href.replace("news_detail.asp?id=", "") # 切出流水號數字當作 Document ID
        hyperlink = "http://50lan.com/web/" + href
        
        # 3. 抓取日期
        # 50嵐的日期跟標題在同一個 <tr> 的不同 <td> 裡面
        tds = x.find_all("td")
        showDate = "未分類"
        for td in tds:
            text = td.text.strip()
            # 用正規表達式判斷，如果文字符合 "2024/05/20" 這種日期格式
            if re.match(r"^\d{4}/\d{2}/\d{2}$", text):
                showDate = text
                break
        
        # 4. 抓取內文簡介 (50嵐首頁沒有簡介，所以預設為標題內容)
        introduce = f"50嵐官方最新公告：{title}。詳細活動內容請點擊連結至官網查看。"
        
        # 5. 抓取圖片
        # 50嵐列表沒有小圖，因此我們預設抓取它的官方商標 Logo 圖
        picture = "http://50lan.com/web/images/title.gif"

        # 6. 組裝成與你電影爬蟲一模一樣的資料結構 (Dict)
        doc = {
            "title": title,
            "introduce": introduce,
            "picture": picture,
            "hyperlink": hyperlink,
            "showDate": showDate,         # 消息發布日期
            "news_id": int(news_id),      # 轉成整數型態 (對應你原本的 int(showLength))
            "lastUpdate": "官網即時同步"
        }

        # 7. 寫入 Firebase Firestore
        db = firestore.client()
        # 集合名稱改為 "50嵐最新消息"
        doc_ref = db.collection("50嵐最新消息").document(news_id)
        doc_ref.set(doc)
        
        count += 1
        
    return f"50嵐最新消息已爬蟲及存檔完畢，共成功寫入 {count} 筆資料到 Firebase！"