import urllib
import arrow
import re
import streamlit as st
import openai
import ics
import json
import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
import pytz  # タイムゾーンを扱うライブラリ
from ics import Calendar, Event
from gmail.auth import login_and_get_emails

load_dotenv()

# OpenAI APIキーの設定
OPENAI_API_KEY = os.environ['OPEN_API_KEY']
openai.api_key = OPENAI_API_KEY

# イベントの保存ディレクトリ
EVENT_DIR = "events"
os.makedirs(EVENT_DIR, exist_ok=True)


def extract_event_info(email_content):
    # 現在の年度を取得 (4月以降は次の年度)
    current_year = datetime.now().year
    
    """OpenAIを使用してメール内容を解析し、イベント情報を抽出する"""
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""
    あなたはメールの内容を解析し、イベント情報を抽出するAIアシスタントです。
    
    以下のメールの内容からイベント情報を抽出してください：
    {email_content}

    ルール：
    - もしメールがイベントと無関係なら、"not_event" と出力してください。
    - メールにある時間は日本標準時 (JST) です。つまりZ+9です。
    - 年度が省略されている場合の年度は、イベントの日付が現在の日付よりも遅れている場合は{int(current_year)+1}、進んでいる場合は{current_year}としてください。
    - 終了時間が明示されていない場合、開始時間の一時間後としてください。
    - online linkはURLがオンラインイベントのリンクを指します。それ以外のURLは無視してください。
    - online passwordはオンラインイベントのパスワードを指します。それ以外のテキストは無視してください。
    - イベントの場合、次のJSONフォーマットで出力してください：
      {{
        "title": "イベント名",
        "start_time": "YYYY-MM-DD HH:MM",
        "end_time": "YYYY-MM-DD HH:MM",
        "location": "イベントの場所",
        "description": "イベントの説明",
        "online link": "イベントのオンラインリンク",
        "online password": "オンラインイベントのパスワード"
        }}
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "あなたはイベント解析AIです。"},
            {"role": "user", "content": prompt}
        ]
    )

    content = response.choices[0].message.content.strip()

    if content == "not_event":
        return None

    try:
        event_info = json.loads(content)
        # **日付フォーマットの修正し、年度の記載のない場合には、補完する**
        current_year = datetime.now().year
        def fix_date_format(date_str):
            # 日付がYYYY-MM-DD HH:mm形式であることを確認
            match = re.match(
                r"(\d{4})-(\d{1,2})-(\d{1,2}) (\d{2}):(\d{2})", date_str)
            if match:
                return date_str  # 形式が正しい場合

            # `YYYY-MM-15 HH:MM`のような誤った形式を処理
            parts = date_str.split()
            if len(parts) == 2:
                date_part, time_part = parts
                date_parts = date_part.split("-")

                if len(date_parts) == 3:
                    year, month, day = date_parts
                    if not day.isdigit() or int(day) > 31:  # AIの誤認識の可能性
                        day = "01"  # デフォルトで1日に設定
                    corrected_date = f"{year}-{month.zfill(2)}-{day.zfill(2)} {time_part}"
                    return corrected_date

            return date_str  # 修正できない場合はそのまま返す

        event_info["start_time"] = fix_date_format(event_info["start_time"])
        event_info["end_time"] = fix_date_format(event_info["end_time"])

        # **日付の有効性チェック**
        try:
            arrow.get(event_info["start_time"], "YYYY-MM-DD HH:mm")
            arrow.get(event_info["end_time"], "YYYY-MM-DD HH:mm")
        except arrow.parser.ParserError:
            return None  # 時間が解析できない場合はNoneを返す

        return event_info
    except json.JSONDecodeError:
        return None  # 解析失敗時はNoneを返す

def create_ics_file(event_info):
    """イベント情報から .ics ファイルを生成 (JST タイムゾーン対応)"""
    cal = Calendar()
    event = Event()
    event.name = event_info["title"]
    
    # JST (UTC+9) タイムゾーンを指定
    jst = pytz.timezone("Asia/Tokyo")
    
    start_time = arrow.get(event_info["start_time"], "YYYY-MM-DD HH:mm").replace(tzinfo=jst)
    end_time = arrow.get(event_info["end_time"], "YYYY-MM-DD HH:mm").replace(tzinfo=jst)

    event.begin = start_time.format("YYYY-MM-DDTHH:mm:ssZZ")  # ISO 8601 フォーマット
    event.end = end_time.format("YYYY-MM-DDTHH:mm:ssZZ")  # ISO 8601 フォーマット
    event.location = event_info["location"]
    event.description = event_info["description"] 
    if "online link" in event_info:
        event.description += "\n" + "オンライン会議のリンク:" + event_info["online link"]
        if "online password" in event_info:
            event.description += "\n" + "オンライン会議のパスコード:" + event_info["online password"]
    
    cal.events.add(event)

    file_name = f"{uuid.uuid4().hex}.ics"
    file_path = os.path.join(EVENT_DIR, file_name)

    with open(file_path, "w") as f:
        f.writelines(cal)

    return file_path

#gmailからメールを取得
emails = login_and_get_emails()

if emails:
    for idx, email in enumerate(emails, start=1):
        st.write(f"タイトル: {email['Subject']}")
        st.write(f"送信者: {email['From']}")
        #st.write(f"日付: {email['Date']}")
        st.write(f"サマリ: {email['Snippet']}")
        st.write(f"メール本文: {email['Body']}")
        email_content = json.dumps(email)

        if st.button("解析を開始", key=idx):
            if email_content.strip():
                st.write("🔍 イベント情報を解析中...")
                event_info = extract_event_info(email_content)

            if event_info:
                st.success("✅ イベントが検出されました！")
                st.write(f"**📌 イベント名:** {event_info['title']}")
                st.write(f"**📅 開始時間:** {event_info['start_time']}")
                st.write(f"**⏳ 終了時間:** {event_info['end_time']}")
                st.write(f"**📍 場所:** {event_info['location']}")
                st.write(f"**📝 説明:** {event_info['description']}")
                if "online link" in event_info:
                    st.write(f"**🔗 オンラインリンク:** {event_info['online link']}"
                            f" (パスワード: {event_info.get('online password', 'なし')})")

                # .icsファイルの生成
                ics_path = create_ics_file(event_info)
                # Goole カレンダーへのリンク生成
                title = event_info["title"]
                description = event_info["description"]
                location = event_info["location"]

                start_dt = datetime.strptime(
                    event_info["start_time"], "%Y-%m-%d %H:%M")
                end_dt = datetime.strptime(
                    event_info["end_time"], "%Y-%m-%d %H:%M")

                start_str = start_dt.strftime("%Y%m%dT%H%M%S")
                end_str = end_dt.strftime("%Y%m%dT%H%M%S")

                params = {
                    "action": "TEMPLATE",
                    "text": title,
                    "dates": f"{start_str}/{end_str}",
                    "location": location,
                    "details": description,
                    "ctz": "Asia/Tokyo"
                }

                base_url = "https://calendar.google.com/calendar/render"
                encoded_params = urllib.parse.urlencode(
                    params, quote_via=urllib.parse.quote)
                google_cal_url = f"{base_url}?{encoded_params}"
                ###
                st.write(f"👉 [Google カレンダーに追加]({google_cal_url})")
                st.download_button(
                    label="📥 カレンダーに追加 (.icsファイルをダウンロード)",
                    data=open(ics_path, "rb"),
                    file_name="event.ics",
                    mime="text/calendar"
                )
            else:
                st.error("❌ イベントが見つかりませんでした。")
        st.write("---")