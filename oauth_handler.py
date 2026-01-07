import os
import json
import pickle
import streamlit as st
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# OAuth 2.0 스코프
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
TOKEN_PICKLE = 'token.pickle'

# 로컬 환경에서는 포트 자동 감지, 배포 환경에서는 환경 변수 사용
def get_redirect_uri():
    """현재 환경에 맞는 redirect URI 반환"""
    # 환경 변수로 직접 설정된 경우 (배포 환경)
    if os.getenv('REDIRECT_URI'):
        return os.getenv('REDIRECT_URI')
    
    # 로컬 환경 - 기본 포트 사용
    return "http://localhost:8502"

REDIRECT_URI = get_redirect_uri()

class GmailOAuthHandler:
    def __init__(self):
        self.creds = None
        self.service = None
        
    def _get_credentials_dict(self):
        """secrets.toml 또는 credentials.json에서 설정을 로드"""
        creds_data = None
        
        # 1. Streamlit secrets 확인 (권장 방식)
        if "google_oauth" in st.secrets:
            # st.secrets는 도트 접근이 가능한 특수 객체이므로 dict로 변환
            creds_data = dict(st.secrets["google_oauth"])
        # 2. 로컬 파일 확인 (개발 환경용)
        elif os.path.exists('credentials.json'):
            try:
                with open('credentials.json', 'r') as f:
                    creds_data = json.load(f)
            except Exception as e:
                st.error(f"credentials.json 파일을 읽는 중 오류가 발생했습니다: {e}")
                return None
        
        if not creds_data:
            st.error("""
            **OAuth 설정이 누락되었습니다.**
            
            배포 환경(Streamlit Cloud)에서는 `.streamlit/secrets.toml`의 내용을 
            App Settings > Secrets에 아래 형식으로 입력해 주세요:
            
            ```toml
            [google_oauth]
            web = { client_id = "...", client_secret = "...", ... }
            ```
            """)
            return None
        
        # credentials.json 형식 확인 및 변환
        if "web" in creds_data:
            return creds_data
        elif "installed" in creds_data:
            # Desktop app을 Web app 형식으로 변환
            return {
                "web": {
                    "client_id": creds_data["installed"]["client_id"],
                    "client_secret": creds_data["installed"]["client_secret"],
                    "redirect_uris": [REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
                }
            }
        else:
            # 직접 client_id, client_secret만 있는 경우
            return {
                "web": {
                    "client_id": creds_data.get("client_id"),
                    "client_secret": creds_data.get("client_secret"),
                    "redirect_uris": [REDIRECT_URI],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs"
                }
            }

    def load_credentials(self):
        """저장된 토큰 로드"""
        if os.path.exists(TOKEN_PICKLE):
            try:
                with open(TOKEN_PICKLE, 'rb') as token:
                    self.creds = pickle.load(token)
            except Exception:
                self.creds = None

        # 토큰이 있고 유효하지 않다면 갱신 시도
        if self.creds and self.creds.expired and self.creds.refresh_token:
            try:
                self.creds.refresh(Request())
                # 갱신된 토큰 저장
                with open(TOKEN_PICKLE, 'wb') as token:
                    pickle.dump(self.creds, token)
            except Exception:
                self.creds = None

        return self.creds is not None and self.creds.valid

    def handle_oauth_flow(self):
        """OAuth 인증 흐름을 자동으로 처리"""
        
        # 설정 확인 정보 표시
        with st.expander("🔧 OAuth 설정 확인 (문제 해결용)", expanded=False):
            st.code(f"현재 Redirect URI: {REDIRECT_URI}")
            st.markdown("""
            **Google Cloud Console 체크리스트:**
            
            1. ✅ **OAuth 클라이언트 ID 타입**: "웹 애플리케이션"
            2. ✅ **승인된 JavaScript 원본**:
               - `http://localhost:8502`
            3. ✅ **승인된 리디렉션 URI**:
               - `http://localhost:8502`
            4. ✅ **credentials.json**: "web" 타입으로 다운로드
            """)
        
        # URL에서 코드 파라미터 확인 (리다이렉트 후)
        query_params = st.query_params.to_dict()
        
        if "code" in query_params:
            code = query_params["code"]
            with st.spinner("🔄 인증 처리 중..."):
                success = self._exchange_code(code)
                
            if success:
                st.query_params.clear()
                self.load_credentials()
                st.success("✅ 인증이 완료되었습니다!")
                st.balloons()
                st.rerun()
            else:
                st.query_params.clear()
                return False
        
        # 에러 파라미터 확인 (인증 실패 시)
        if "error" in query_params:
            error = query_params.get("error")
            st.error(f"❌ Google 인증 오류: {error}")
            st.query_params.clear()
            return False

        # 이미 로그인 된 경우
        if self.load_credentials():
            return True

        # 로그인 필요
        client_config = self._get_credentials_dict()
        if not client_config:
            return False

        try:
            flow = Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                redirect_uri=REDIRECT_URI
            )

            auth_url, _ = flow.authorization_url(
                prompt='consent',
                access_type='offline',
                include_granted_scopes='true'
            )

            st.markdown(f'''
                <a href="{auth_url}" target="_self">
                    <button style="
                        background-color: #4285F4; 
                        color: white; 
                        padding: 12px 24px; 
                        border: none; 
                        border-radius: 5px; 
                        cursor: pointer;
                        font-size: 16px;
                        font-weight: bold;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                        🔐 Google 계정으로 로그인
                    </button>
                </a>
                ''', unsafe_allow_html=True)
        except Exception as e:
            st.error(f"❌ OAuth Flow 생성 실패: {str(e)}")
            
            if "Client secrets must be for a web or installed app" in str(e):
                st.warning("""
                **해결 방법:**
                
                Google Cloud Console에서:
                1. 기존 OAuth 클라이언트 ID 삭제
                2. 새로 만들기 → **"웹 애플리케이션"** 선택
                3. 승인된 JavaScript 원본: `http://localhost:8502` 추가
                4. 승인된 리디렉션 URI: `http://localhost:8502` 추가
                5. credentials.json 다시 다운로드
                """)
            return False
        
        return False

    def _exchange_code(self, code):
        """URL에서 받은 코드를 토큰으로 교환"""
        try:
            client_config = self._get_credentials_dict()
            if not client_config:
                st.error("클라이언트 설정을 불러올 수 없습니다.")
                return False
                
            flow = Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                redirect_uri=REDIRECT_URI
            )
            
            # 코드로 토큰 교환
            flow.fetch_token(code=code)
            self.creds = flow.credentials
            
            # 토큰 저장
            with open(TOKEN_PICKLE, 'wb') as token:
                pickle.dump(self.creds, token)
            
            return True
                
        except Exception as e:
            error_msg = str(e)
            st.error(f"❌ 토큰 교환 실패: {error_msg}")
            
            if "invalid_client" in error_msg.lower() or "unauthorized" in error_msg.lower():
                st.error("""
                **🔧 invalid_client 오류 해결 방법:**
                
                ### 1. Google Cloud Console 설정 확인
                
                **OAuth 클라이언트 ID 편집:**
                - 애플리케이션 유형: **"웹 애플리케이션"**
                - 승인된 JavaScript 원본:
                  ```
                  http://localhost:8502
                  ```
                - 승인된 리디렉션 URI:
                  ```
                  http://localhost:8502
                  ```
                
                ### 2. 새 credentials.json 다운로드
                - 저장 후 JSON 다운로드 (⬇️ 아이콘)
                - 기존 파일 교체
                
                ### 3. 기존 토큰 삭제
                ```bash
                rm token.pickle
                ```
                
                ### 4. 앱 재시작
                """)
            
            return False

    def send_email(self, to_email, subject, html_content):
        """이메일 전송"""
        if not self.creds or not self.creds.valid:
            return False, "인증이 필요합니다."

        try:
            service = build('gmail', 'v1', credentials=self.creds)
            message = MIMEMultipart('alternative')
            message['To'] = to_email
            message['Subject'] = subject
            
            html_part = MIMEText(html_content, 'html', 'utf-8')
            message.attach(html_part)
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            sent = service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
            return True, sent['id']
        except Exception as e:
            return False, str(e)

    def get_user_email(self):
        """로그인한 사용자 이메일 표시"""
        if self.creds and self.creds.valid:
            try:
                service = build('gmail', 'v1', credentials=self.creds)
                profile = service.users().getProfile(userId='me').execute()
                return profile['emailAddress']
            except:
                return "Unknown"
        return None
        
    def logout(self):
        """로그아웃 처리"""
        if os.path.exists(TOKEN_PICKLE):
            os.remove(TOKEN_PICKLE)
        self.creds = None
        st.rerun()


def render_oauth_section():
    """OAuth 인증 섹션 렌더링"""
    st.header("🔐 Gmail OAuth 인증")
    
    oauth_handler = GmailOAuthHandler()
    is_authenticated = oauth_handler.handle_oauth_flow()
    
    if is_authenticated:
        user_email = oauth_handler.get_user_email()
        st.success(f"✅ 인증됨: {user_email}")
        
        # 발신자명 설정
        sender_name = st.text_input("발신자명", value=st.session_state.get('sender_name', "배송관리팀"))
        st.session_state['sender_name'] = sender_name
        
        if st.button("🔓 인증 해제 (로그아웃)", type="secondary"):
            oauth_handler.logout()
            
        return oauth_handler, sender_name
    else:
        st.info("👆 Google 로그인을 완료하면 메일 발송 기능이 활성화됩니다.")
        return None, None