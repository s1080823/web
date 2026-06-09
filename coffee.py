import os
import json
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

# 引入 Firebase
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# 1. 初始化 Firebase Firestore
if os.path.exists('serviceAccountKey.json'):
    cred = credentials.Certificate('serviceAccountKey.json')
else:
    cred_dict = json.loads(os.getenv('FIREBASE_CONFIG'))
    cred = credentials.Certificate(cred_dict)

firebase_admin.initialize_app(cred)
db = firestore.client()


# 2. 建立星巴克專用的 Webhook 端點 (指定必須用 POST 接收)
@app.route("/starbucks_webhook", methods=["POST"])
def starbucks_webhook():
    try:
        # 【步驟 A】接收並解析 Webhook 傳來的 JSON 資料
        # 很多平台觸發 Webhook 時會帶有一些防偽金鑰 (Token) 或觸發事件名稱
        payload = request.get_json()
        if not payload:
            return jsonify({"status": "error", "message": "未偵測到正確的 JSON 資料"}), 400
            
        print("====== 成功觸發星巴克 Webhook ======")
        print(f"收到觸發參數: {payload}")
        
        # 可選：這裡可以加上簡單的安全檢查，防止外人亂呼叫你的 Webhook
        # 假設對方必須帶有 "action": "update_menu" 才會啟動爬蟲
        if payload.get("action") != "update_menu":
            return jsonify({"status": "ignored", "message": "動作不符，不執行爬蟲"}), 200

        # 【步驟 B】直接在背景執行星巴克爬蟲邏輯
        cat_ids = [1, 4, 8, 10, 107]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        count = 0
        
        for cat_id in cat_ids:
            url = f"https://www.starbucks.com.tw/products/drinks/view.jspx?catId={cat_id}"
            Data = requests.get(url, headers=headers, timeout=15)
            Data.encoding = "utf-8"
            sp = BeautifulSoup(Data.text, "html.parser")
            
            category_name = "星巴克飲品"
            title_box = sp.find(class_="title_mint") or sp.find("h1")
            if title_box:
                category_name = title_box.text.strip()
            
            items = sp.select(".item_box") or sp.find_all("li")
            
            for item in items:
                a_tag = item.find("a")
                if not a_tag or "id=" not in a_tag.get("href", ""):
                    continue
                    
                href = a_tag.get("href")
                drink_id_match = re.search(r"id=(\d+)", href)
                if not drink_id_match:
                    continue
                drink_id = drink_id_match.group(1)
                
                # 抓名稱
                img_tag = item.find("img")
                title = "未命名飲品"
                if img_tag and img_tag.get("alt"):
                    title = img_tag.get("alt").strip()
                elif a_tag.get("title"):
                    title = a_tag.get("title").strip()
                
                # 抓圖片
                picture = "無圖片"
                if img_tag and img_tag.get("src"):
                    picture = "https://www.starbucks.com.tw" + img_tag.get("src")
                
                hyperlink = "https://www.starbucks.com.tw/products/drinks/" + href
                introduce = f"星巴克【{category_name}】系列：{title}。詳細資訊請參閱官方詳細頁面。"
                
                doc = {
                    "title": title,
                    "category": category_name,
                    "introduce": introduce,
                    "picture": picture,
                    "hyperlink": hyperlink,
                    "drink_id": int(drink_id),
                    "lastUpdate": "透過 Webhook 自動更新"
                }
                
                # 寫入 Firebase
                doc_ref = db.collection("星巴克飲料菜單").document(drink_id)
                doc_ref.set(doc)
                count += 1
                
        # 【步驟 C】回傳給 Webhook 發送端，告知已經成功跑完爬蟲並更新
        return jsonify({
            "status": "success",
            "message": f"Webhook 觸發成功！星巴克菜單已更新完畢，共寫入 {count} 筆資料。"
        }), 200

    except Exception as e:
        print(f"Webhook 內部發生錯誤: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)