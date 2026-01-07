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

def get_redirect_uri():
    """현재 환경에 맞는 redirect URI 반환"""
    # 1. 환경 변수 우선 (배포 시 설정)
    if os.getenv('REDIRECT_URI'):
        return os.getenv('REDIRECT_URI')
    
    # 2. Streamlit secrets 확인
    if "google_oauth" in st.secrets:
        if "redirect_uri" in st.secrets["google_oauth"]:
            return st.secrets["google_oauth"]["redirect_uri"]
        if "redirect_uris" in st.secrets["google_oauth"]:
            uris = st.secrets["google_oauth"]["redirect_uris"]
            return uris[0] if isinstance(uris, list) else uris
    
    # 3. 로컬 환경 기본값
    return "http://localhost:8502"

REDIRECT_URI = get_redirect_uri()

class GmailOAuthHandler:
    def __init__(self):
        self.creds = None
        self.service = None
        
    def _get_credentials_dict(self):
        """secrets.toml 또는 credentials.json에서 설정을 로드"""
        creds_data = None
        
        # 1. Streamlit secrets 확인
        if "google_oauth" in st.secrets:
            creds_data = dict(st.secrets["google_oauth"])
            
            # 디버깅 정보
            with st.expander("🔍 Debug: OAuth 설정 확인", expanded=False):
                st.code(f"Redirect URI: {REDIRECT_URI}")
                st.json({
                    "client_id_exists": bool(creds_data.get('client_id')),
                    "client_id_prefix": str(creds_data.get('client_id', ''))[:30] + "..." if creds_data.get('client_id') else "없음",
                    "has_client_secret": bool(creds_data.get('client_secret')),
                    "redirect_uri": REDIRECT_URI
                })
        
        # 2. 로컬 파일 확인
        elif os.path.exists('credentials.json'):
            try:
                with open('credentials.json', 'r') as f:
                    creds_data = json.load(f)
            except Exception as e:
                st.error(f"credentials.json 읽기 실패: {e}")
                return None
        
        if not creds_data:
            st.error("OAuth 설정이 누락되었습니다.")
            return None
        
        # 형식 변환
        if "web" in creds_data:
            # redirect_uris 확인 및 업데이트
            if "redirect_uris" not in creds_data["web"] or not creds_data["web"]["redirect_uris"]:
                creds_data["web"]["redirect_uris"] = [REDIRECT_URI]
            return creds_data
        elif "installed" in creds_data:
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

        if self.creds and self.creds.expired and self.creds.refresh_token:
            try:
                self.creds.refresh(Request())
                with open(TOKEN_PICKLE, 'wb') as token:
                    pickle.dump(self.creds, token)
            except Exception:
                self.creds = None

        return self.creds is not None and self.creds.valid

    def handle_oauth_flow(self):
        """OAuth 인증 흐름 처리"""
        
        # 설정 확인 정보
        with st.expander("🔧 OAuth 설정 가이드", expanded=False):
            st.code(f"현재 Redirect URI: {REDIRECT_URI}")
            st.markdown("""
            **Google Cloud Console 설정 체크리스트:**
            
            ### 1. OAuth Consent Screen
            - **Publishing status 확인**:
              - `Testing` → 테스트 사용자 추가 필수
              - `In production` → 모든 사용자 사용 가능
            - **User Type**: External 권장
            - **Test users**: 로그인할 Gmail 주소 추가
            
            ### 2. OAuth 클라이언트 ID
            - **애플리케이션 유형**: 웹 애플리케이션
            - **승인된 자바스크립트 원본**:
              ```
              https://your-app.streamlit.app
              http://localhost:8502
              ```
            - **승인된 리디렉션 URI**:
              ```
              https://your-app.streamlit.app
              http://localhost:8502
              ```
            
            ### 3. Streamlit Secrets 설정
            ```toml
            [google_oauth]
            client_id = "your-client-id.apps.googleusercontent.com"
            client_secret = "your-client-secret"
            redirect_uri = "https://your-app.streamlit.app"
            ```
            
            ⚠️ **주의**: redirect_uri에 슬래시(/)를 붙이지 마세요!
            """)
        
        # URL 파라미터 확인
        query_params = st.query_params.to_dict()
        
        # 리다이렉트 후 코드 처리
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
        
        # 에러 처리
        if "error" in query_params:
            error = query_params.get("error")
            error_description = query_params.get("error_description", "")
            
            st.error(f"❌ Google 인증 오류: {error}")
            
            if error == "access_denied":
                if "403" in error_description or "org_internal" in error_description:
                    st.error("""
                    **403 에러: 앱 액세스 제한**
                    
                    ### 해결 방법
                    
                    #### 옵션 1: 테스트 사용자 추가 (가장 빠름)
                    1. Google Cloud Console → OAuth consent screen
                    2. Test users → ADD USERS 클릭
                    3. 로그인할 Gmail 주소 입력
                    4. SAVE 후 다시 로그인 시도
                    
                    #### 옵션 2: User Type 변경
                    1. OAuth consent screen에서 MAKE EXTERNAL 클릭
                    2. 외부 사용자도 접근 가능하도록 변경
                    
                    #### 옵션 3: 앱 게시 (공개)
                    1. OAuth consent screen → PUBLISH APP
                    2. 검토 없이 게시 가능 (민감한 권한 없는 경우)
                    """)
                else:
                    st.warning("사용자가 인증을 취소했습니다.")
            
            st.query_params.clear()
            return False

        # 이미 인증된 경우
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
                prompt='select_account',
                access_type='offline',
                include_granted_scopes='true'
            )

            # 방법 1: 스타일링된 링크 (권장) - target="_top"으로 iframe 탈출
            st.markdown(f'''
                <style>
                .google-login-btn {{
                    display: inline-block;
                    background: linear-gradient(135deg, #4285F4 0%, #357AE8 100%);
                    color: white;
                    padding: 14px 32px;
                    text-decoration: none;
                    border-radius: 8px;
                    font-size: 16px;
                    font-weight: 600;
                    box-shadow: 0 4px 6px rgba(66, 133, 244, 0.3);
                    transition: all 0.3s ease;
                    cursor: pointer;
                    text-align: center;
                }}
                .google-login-btn:hover {{
                    background: linear-gradient(135deg, #357AE8 0%, #2A63C8 100%);
                    box-shadow: 0 6px 12px rgba(66, 133, 244, 0.4);
                    transform: translateY(-2px);
                }}
                .google-login-btn:active {{
                    transform: translateY(0);
                    box-shadow: 0 2px 4px rgba(66, 133, 244, 0.3);
                }}
                </style>
                <a href="{auth_url}" target="_top" class="google-login-btn">
                    🔐 Google 계정으로 로그인
                </a>
                ''', unsafe_allow_html=True)
            
            st.markdown("---")
            
            # 방법 2: URL 직접 표시 (대체 방안)
            with st.expander("🔗 로그인이 안 되나요? 이 링크를 직접 클릭하세요"):
                st.markdown(f"[Google 로그인 페이지 열기]({auth_url})")
                st.caption("위 버튼이 작동하지 않으면 이 링크를 사용하세요.")
            
            st.info("""
            **💡 로그인 팁:**
            - 버튼 클릭 후 새 탭에서 로그인 페이지가 열립니다
            - 403 에러 발생 시 위의 "OAuth 설정 가이드"를 확인하세요
            - 특히 **테스트 사용자 등록** 여부를 확인하세요
            """)
            
        except Exception as e:
            st.error(f"❌ OAuth Flow 생성 실패: {str(e)}")
            
            if "redirect_uri_mismatch" in str(e).lower():
                st.error(f"""
                **Redirect URI 불일치 오류**
                
                현재 설정된 URI: `{REDIRECT_URI}`
                
                Google Cloud Console의 "승인된 리디렉션 URI"에 
                이 주소가 **정확히** 등록되어 있는지 확인하세요.
                
                - 프로토콜(http/https) 일치 확인
                - 끝에 슬래시(/) 없는지 확인
                - 포트 번호 일치 확인
                """)
            
            return False
        
        return False

    def _exchange_code(self, code):
        """코드를 토큰으로 교환"""
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
            
            flow.fetch_token(code=code)
            self.creds = flow.credentials
            
            with open(TOKEN_PICKLE, 'wb') as token:
                pickle.dump(self.creds, token)
            
            return True
                
        except Exception as e:
            error_msg = str(e)
            st.error(f"❌ 토큰 교환 실패: {error_msg}")
            
            if "invalid_client" in error_msg.lower():
                st.error("""
                **invalid_client 오류**
                
                **원인:**
                - Client ID 또는 Client Secret이 잘못됨
                - Redirect URI 불일치
                
                **해결:**
                1. Google Cloud Console에서 credentials.json 재다운로드
                2. Streamlit Secrets 업데이트
                3. 앱 재시작 (Manage app → Reboot)
                """)
            elif "redirect_uri_mismatch" in error_msg.lower():
                st.error(f"""
                **Redirect URI 불일치**
                
                코드 교환 시 사용된 URI: `{REDIRECT_URI}`
                
                Google Cloud Console 설정을 다시 확인하세요.
                """)
            
            return False

    def send_email(self, to_email, subject, html_content, from_name=None):
        """이메일 전송"""
        if not self.creds or not self.creds.valid:
            return False, "인증이 필요합니다."

        try:
            service = build('gmail', 'v1', credentials=self.creds)
            user_email = self.get_user_email()
            
            message = MIMEMultipart('alternative')
            message['To'] = to_email
            if from_name:
                message['From'] = f"{from_name} <{user_email}>"
            else:
                message['From'] = user_email
            message['Subject'] = subject
            
            html_part = MIMEText(html_content, 'html', 'utf-8')
            message.attach(html_part)
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            sent = service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
            return True, sent['id']
        except Exception as e:
            return False, str(e)

    def get_user_email(self):
        """로그인한 사용자 이메일 반환"""
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
        
        sender_name = st.text_input("발신자명", value=st.session_state.get('sender_name', "배송관리팀"))
        st.session_state['sender_name'] = sender_name
        
        if st.button("🔓 인증 해제 (로그아웃)", type="secondary"):
            oauth_handler.logout()
            
        return oauth_handler, sender_name
    else:
        st.info("👆 Google 로그인을 완료하면 메일 발송 기능이 활성화됩니다.")
        return None, None