import base64
import os
import streamlit as st
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from dotenv import load_dotenv
import urllib.parse

# 環境変数の読み込み
load_dotenv()

# Gmail APIのスコープ（読み取り専用）
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]

# リダイレクトURL（Google OAuth 認証後に戻るページ）
REDIRECT_URI = os.environ["REDIRECT_URI"]


def decode_base64url(data_string: str) -> bytes:
    """
    Gmail API から取得した Base64URL エンコードされたデータをデコードする。
    Gmail は Base64URL 形式を使用するため、通常の Base64 に変換してからデコードする。
    """
    data_string = data_string.replace('-', '+').replace('_', '/')
    
    # Base64のパディングを補完（Gmailのデータは "=" が不足している場合がある）
    missing_padding = 4 - (len(data_string) % 4)
    if missing_padding != 4:
        data_string += '=' * missing_padding
    
    return base64.b64decode(data_string)


def get_email_body(payload: dict) -> str:
    """
    メールの MIME 構造を解析して、本文（text/plain）を抽出する。
    - multipart の場合は text/plain を優先的に取得
    - 単一のメッセージの場合は直接デコード
    """
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    # 【1】 multipart（複数の部分を持つメール）の場合
    if mime_type.startswith("multipart"):
        parts = payload.get("parts", [])
        for part in parts:
            part_mime = part.get("mimeType", "")
            part_body = part.get("body", {})
            part_data = part_body.get("data")
            if part_mime == "text/plain" and part_data:
                decoded_bytes = decode_base64url(part_data)
                return decoded_bytes.decode("utf-8", errors="replace")
        return ""  # どの部分にも本文が見つからない場合

    # 【2】 通常の（単一）メールの場合
    else:
        if body_data:
            decoded_bytes = decode_base64url(body_data)
            return decoded_bytes.decode("utf-8", errors="replace")
        return ""


def get_flow():
    """
    Google OAuth 2.0 の Flow オブジェクトを作成し、認証フローを設定する。
    """
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        'client_secret.json',  # Google Cloud から取得した認証情報ファイル
        scopes=SCOPES
    )
    flow.redirect_uri = REDIRECT_URI
    return flow


def login_and_get_emails():
    """
    - すでにログイン済み（session_state に credentials がある）なら、Gmail API でメールを取得
    - まだログインしていない場合は、Google 認証ページへリダイレクト
    """
    if "credentials" in st.session_state:
        creds = st.session_state["credentials"]
        service = build("gmail", "v1", credentials=creds)

        # Gmail API を呼び出して最新の5通のメールを取得
        results = service.users().messages().list(
            userId="me", maxResults=5
        ).execute()
        messages = results.get("messages", [])

        if not messages:
            st.write("📭 メールが見つかりませんでした。")
            return []
        else:
            email_data_list = []

            for msg in messages:
                # メールの詳細を取得（format="full" で本文を含む）
                msg_full = service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()

                payload = msg_full.get("payload", {})
                headers = payload.get("headers", [])

                # 本文のデコード処理
                decoded_body = get_email_body(payload)

                # ヘッダーから「件名」「送信者」「日時」を取得
                subject, sender, date = None, None, None
                for header in headers:
                    name = header.get("name", "").lower()
                    value = header.get("value", "")
                    if name == "subject":
                        subject = value
                    elif name == "from":
                        sender = value
                    elif name == "date":
                        date = value

                # スニペット（概要）を取得
                snippet = msg_full.get("snippet", "")

                email_data_list.append({
                    "Subject": subject or "",
                    "From": sender or "",
                    "Date": date or "",
                    "Snippet": snippet,
                    "Body": decoded_body
                })

            return email_data_list

    else:
        # 未ログインなら、URL のクエリパラメータに認証コードがあるかチェック
        query_params = st.query_params
        if "code" in query_params:
            code = query_params["code"][0]
            flow = get_flow()

            # 認証リダイレクトURLを組み立て
            parsed_params = urllib.parse.urlencode(query_params, doseq=True)
            authorization_response_url = f"{REDIRECT_URI}?{parsed_params}"

            # トークンを取得してセッションに保存
            flow.fetch_token(authorization_response=authorization_response_url)
            st.session_state["credentials"] = flow.credentials
            st.rerun()

        else:
            st.write("🔑 Google アカウントでログインしてください。")

            flow = get_flow()
            auth_url, state = flow.authorization_url(
                access_type='offline',
                prompt='consent'
            )
            if st.button("Google にログイン"):
                st.markdown(
                    f'<a href="{auth_url}" target="_self">クリックしてログイン</a>',
                    unsafe_allow_html=True
                )
            return []


def main():
    """
    Streamlit の UI を作成し、Gmail の最新5通のメールを表示する
    """
    st.title("📩 Gmail メール取得アプリ")

    emails = login_and_get_emails()

    if emails:
        for i, mail in enumerate(emails, start=1):
            st.subheader(f"📧 メール {i}")
            st.write("📌 **件名:**", mail["Subject"])
            st.write("📤 **送信者:**", mail["From"])
            #st.write("📅 **受信日時:**", mail["Date"])
            st.write("📝 **概要:**", mail["Snippet"])
            st.write("📜 **本文（300文字まで表示）:**")
            st.write(mail["Body"][:300] + "...")
            st.write("---")


if __name__ == "__main__":
    main()
