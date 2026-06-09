import os
import json
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, make_response, jsonify
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore

if os.path.exists('serviceAccountKey.json'):
    cred = credentials.Certificate('serviceAccountKey.json')
else:
    firebase_config = os.getenv('FIREBASE_CONFIG')
    cred_dict = json.loads(firebase_config)
    cred = credentials.Certificate(cred_dict)

firebase_admin.initialize_app(cred)

app = Flask(__name__)

db = firestore.client()

@app.route("/fiftylan_news")
def fiftylan_news():
    # 50嵐 最新消息
    url = "http://50lan.com/web/news.asp"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    Data = requests.get(url, headers=headers)
    Data.encoding = "utf-8"
    
    sp = BeautifulSoup(Data.text, "html.parser")
    
    all_rows = sp.find_all("tr")
    
    count = 0
    
    for x in all_rows:
        a_tag = x.find("a")
        if a_tag is None:
            continue
            
        # 1. 抓取標題
        title = a_tag.text.strip()
        
        # 2. 抓取新聞 ID 與 超連結
        href = a_tag.get("href")
        news_id = href.replace("news_detail.asp?id=", "") # 切出流水號數字當作 Document ID
        hyperlink = "http://50lan.com/web/" + href
        
        # 3. 抓取日期
        tds = x.find_all("td")
        showDate = "未分類"
        for td in tds:
            text = td.text.strip()
            if re.match(r"^\d{4}/\d{2}/\d{2}$", text):
                showDate = text
                break
        
        introduce = f"50嵐官方最新公告：{title}。詳細活動內容請點擊連結至官網查看。"
        
        picture = "http://50lan.com/web/images/title.gif"

        doc = {
            "title": title,
            "introduce": introduce,
            "picture": picture,
            "hyperlink": hyperlink,
            "showDate": showDate,         
            "news_id": int(news_id),      
            "lastUpdate": "官網即時同步"
        }

        doc_ref = db.collection("50嵐最新消息").document(news_id)
        doc_ref.set(doc)
        
        count += 1
        
    return f"50嵐最新消息已爬蟲及存檔完畢，共成功寫入 {count} 筆資料到 Firebase！"

if __name__ == "__main__":
    app.run(debug=True)