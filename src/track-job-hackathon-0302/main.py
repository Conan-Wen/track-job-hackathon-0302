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
    - イベントの場合、次のJSONフォーマットで出力してください：
      {{
        "title": "イベント名",
        "start_time": "YYYY-MM-DD HH:MM",
        "end_time": "YYYY-MM-DD HH:MM",
        "location": "イベントの場所",
        "description": "イベントの説明"
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
    """イベント情報に基づいて.icsファイルを生成する"""
    cal = ics.Calendar()
    event = ics.Event()
    event.name = event_info["title"]
    event.begin = event_info["start_time"]
    event.end = event_info["end_time"]
    event.location = event_info["location"]
    event.description = event_info["description"]
    cal.events.add(event)

    file_name = f"{uuid.uuid4().hex}.ics"
    file_path = os.path.join(EVENT_DIR, file_name)

    with open(file_path, "w") as f:
        f.writelines(cal)

    return file_path


# Streamlit UI
st.title("📅 メールからイベントを抽出")

st.write("📩 メールの内容を入力してください。イベント情報を解析し、カレンダー用の.icsファイルを生成します。")

email_content = st.text_area("✉️ メール内容を入力", height=200)

if st.button("解析を開始"):
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

            # .icsファイルの生成
            ics_path = create_ics_file(event_info)
            st.download_button(
                label="📥 カレンダーに追加 (.icsファイルをダウンロード)",
                data=open(ics_path, "rb"),
                file_name="event.ics",
                mime="text/calendar"
            )
        else:
            st.error("❌ イベントが見つかりませんでした。")
    else:
        st.warning("⚠️ メールの内容を入力してください！")