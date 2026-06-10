import os
import json
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify

# 🔥 補上 LINE Bot 所需的 SDK 套件
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    TemplateSendMessage, CarouselTemplate, CarouselColumn, URITemplateAction
)

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

# 🔥 2. 請填入你 LINE Developers 後台的真實密鑰
LINE_CHANNEL_ACCESS_TOKEN = "你的_LINE_CHANNEL_ACCESS_TOKEN"
LINE_CHANNEL_SECRET = "你的_LINE_CHANNEL_SECRET"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ---------------------------------------------------------
# 新增端點：負責接收 LINE 平台傳過來的訊號 (必須設定為 POST)
# ---------------------------------------------------------
@app.route("/line_webhook", methods=["POST"])
def line_webhook():
    # 檢查 LINE 專屬的安全驗證簽章
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


# ---------------------------------------------------------
# LINE 訊息處理邏輯：當使用者在 LINE 傳送文字時會觸發這裡
# ---------------------------------------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    
    # 功能一：使用者輸入「看菜單」 -> 從 Firebase 讀取資料並傳回給 LINE
    if "看菜單" in user_message or "菜單" in user_message:
        try:
            # 從 Firebase 撈出前 5 筆飲料做成輪播字卡
            docs = db.collection("星巴克飲料菜單").order_by("drink_id").limit(5).stream()
            
            columns = []
            for doc in docs:
                drink = doc.to_dict()
                columns.append(
                    CarouselColumn(
                        thumbnail_image_url=drink.get("picture"),
                        title=drink.get("title")[:19],  # LINE 限制標題 20 字以內
                        text=f"分類: {drink.get('category')}",
                        actions=[
                            URITemplateAction(
                                label="查看完整介紹",
                                uri=drink.get("hyperlink")
                            )
                        ]
                    )
                )
                
            if not columns:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="☕ 目前資料庫是空的，請先對我輸入「更新菜單」來抓取官網資料。")
                )
                return

            carousel_template = TemplateSendMessage(
                alt_text="星巴克精選飲料菜單",
                template=CarouselTemplate(columns=columns)
            )
            line_bot_api.reply_message(event.reply_token, carousel_template)

        except Exception as firebase_err:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"❌ 讀取資料庫失敗: {firebase_err}")
            )

    # 功能二：使用者輸入「更新菜單」 -> 執行你原本寫的星巴克爬蟲核心並回存 Firebase
    elif "更新菜單" in user_message:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⏳ 正在幫您連線到星巴克官網爬取最新菜單，這需要幾秒鐘，請稍候..."))
        
        try:
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
                    
                    img_tag = item.find("img")
                    title = "未命名飲品"
                    if img_tag and img_tag.get("alt"):
                        title = img_tag.get("alt").strip()
                    elif a_tag.get("title"):
                        title = a_tag.get("title").strip()
                    
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
                        "lastUpdate": "透過 LINE 機器人手動更新"
                    }
                    
                    # 寫入 Firebase
                    db.collection("星巴克飲料菜單").document(drink_id).set(doc)
                    count += 1
            
            # 爬完後主動發送推播通知告知用戶
            line_bot_api.push_message(
                event.source.user_id,
                TextSendMessage(text=f"🎉 菜單更新成功！共同步了 {count} 筆飲品到 Firebase。請輸入「看菜單」來瀏覽！")
            )
            
        except Exception as crawl_err:
            line_bot_api.push_message(
                event.source.user_id,
                TextSendMessage(text=f"❌ 菜單更新中途發生錯誤: {crawl_err}")
            )
            
    # 功能三：一般聊天引導
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="☕ 歡迎使用星巴克菜單小助手！\n\n請輸入「看菜單」來查看特選飲料，或輸入「更新菜單」來與官網同步資料。")
        )


# ---------------------------------------------------------
# 你原本保留的舊 Webhook，如果你想保留讓 Postman 測試可以用
# ---------------------------------------------------------
@app.route("/starbucks_webhook", methods=["POST"])
def starbucks_webhook():
    # ... 你原本寫的舊 Webhook 代碼 (已整合進 LINE 內，此段可留著當備用 API)
    return jsonify({"status": "success", "message": "預留端點正常"}), 200


# 🔥 3. 修正底部的啟動程式碼：適應 Render 雲端平台的 Port 分配機制
if __name__ == "__main__":
    # Render 會給予環境變數 PORT，若沒有則預設 5000
    port = int(os.environ.get("PORT", 5000))
    # 必須綁定到 0.0.0.0，外網（LINE 平台）才連得進來
    app.run(host="0.0.0.0", port=port, debug=False)