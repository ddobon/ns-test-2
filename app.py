import streamlit as st
import pandas as pd
from mailer_logic import SaaSMailer
from oauth_handler import GmailOAuthHandler
import os
from datetime import datetime

# --- 설정 및 상수 ---
HISTORY_FILE = "delivery_delay_history.csv"
st.set_page_config(layout="wide", page_title="배송지연 안내 발송기")

def safe_read_csv(file, file_description="파일"):
    """Safely read CSV with multiple encoding attempts"""
    encodings = ['utf-8-sig', 'cp949', 'euc-kr', 'latin1', 'utf-8']
    
    for i, encoding in enumerate(encodings):
        try:
            file.seek(0)
            df = pd.read_csv(file, encoding=encoding)
            if i > 0:
                st.info(f"ℹ️ {file_description}을(를) {encoding} 인코딩으로 읽었습니다.")
            return df
        except UnicodeDecodeError:
            if i == len(encodings) - 1:
                st.error(f"❌ {file_description} 인코딩 오류. 파일을 UTF-8로 저장하여 다시 시도해주세요.")
                raise
            continue
        except Exception as e:
            st.error(f"❌ {file_description} 읽기 오류: {str(e)}")
            raise
    return None

def save_history_log(mail_items, send_results):
    """발송된 내역을 주문 단위로 풀어서 CSV에 누적 저장"""
    history_rows = []
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in mail_items:
        p_name = item['partner_name']
        p_code = item['partner_code']
        
        if p_name in send_results:
            status = "Success" if send_results[p_name]['success'] else "Fail"
            msg = send_results[p_name]['msg']
        else:
            status = "Skipped"
            msg = "No Email / Excluded"

        target_df = item['df']
        for _, row in target_df.iterrows():
            history_rows.append({
                '수집일시': current_time,
                '협력사명': p_name,
                '협력사코드': p_code,
                '주문번호': row.get('주문번호', ''),
                '상품코드': row.get('상품코드', ''),
                '상품명': row.get('상품명', ''),
                '운송장번호': row.get('운송장번호', ''),
                '발송결과': status,
                '비고': msg
            })

    if not history_rows:
        return

    new_df = pd.DataFrame(history_rows)
    
    if not os.path.exists(HISTORY_FILE):
        new_df.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
    else:
        new_df.to_csv(HISTORY_FILE, mode='a', header=False, index=False, encoding='utf-8-sig')
    
    st.toast(f"💾 히스토리 파일({HISTORY_FILE})에 {len(new_df)}건의 데이터가 저장되었습니다.", icon="✅")

def render_oauth_section():
    """OAuth 인증 섹션 렌더링 (자동 리다이렉트 방식 대응)"""
    st.header("🔐 Gmail OAuth 인증")
    
    oauth_handler = GmailOAuthHandler()
    
    # handle_oauth_flow가 True를 반환하면 인증 완료, False면 로그인 버튼 표시
    is_authenticated = oauth_handler.handle_oauth_flow()
    
    if is_authenticated:
        user_email = oauth_handler.get_user_email()
        st.success(f"✅ 인증됨: {user_email}")
        
        # 발신자명 설정
        sender_name = st.text_input("발신자명", value=st.session_state.get('sender_name', "배송관리팀"))
        st.session_state['sender_name'] = sender_name
        
        if st.button("🔓 인증 해제 (로그아웃)", type="secondary"):
            oauth_handler.logout() # 핸들러 내부의 logout() 호출
            
        return oauth_handler, sender_name
    else:
        # handle_oauth_flow 내부에 버튼 생성 로직이 있으므로 추가 버튼은 필요 없음
        st.info("👈 로그인을 완료하면 메인 기능이 활성화됩니다.")
        return None, None

def main():
    st.title("📮 배송지연 안내 메일 자동 발송기")
    
    st.markdown("""
    업로드한 CSV에서 **배송지연 분류**가 비어있는 항목을 찾아 협력사별로 안내 메일을 자동 생성합니다.
    발송 완료 시 **자동으로 이력이 파일로 저장**됩니다.
    """)
    
    # Sidebar: Configuration
    with st.sidebar:
        oauth_handler, sender_name = render_oauth_section()
                
        st.divider()
        st.write("**사용법:**")
        st.write("1. Gmail OAuth 인증")
        st.write("2. `input_template.csv` 업로드")
        st.write("3. `mail_list` 업로드")
        st.write("4. 분석 및 미리보기")
        st.write("5. 메일 발송 (자동 기록)")
        
        if os.path.exists(HISTORY_FILE):
            st.divider()
            st.write("📊 **발송 히스토리 관리**")
            
            # 기존 히스토리 업로드
            uploaded_history = st.file_uploader("기존 히스토리 파일 합치기 (CSV)", type=['csv'], key="history_uploader")
            if uploaded_history:
                try:
                    uploaded_df = pd.read_csv(uploaded_history)
                    if not os.path.exists(HISTORY_FILE):
                        uploaded_df.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
                    else:
                        # 중복 제거 로직 (주문번호 기준 등)을 넣을 수도 있지만, 일단 단순 병합
                        existing_df = pd.read_csv(HISTORY_FILE)
                        combined_df = pd.concat([existing_df, uploaded_df]).drop_duplicates().reset_index(drop=True)
                        combined_df.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
                    st.success("✅ 히스토리가 성공적으로 통합되었습니다!")
                except Exception as e:
                    st.error(f"히스토리 통합 오류: {e}")

            # 다운로드 버튼
            with open(HISTORY_FILE, "rb") as f:
                st.download_button(
                    label="📥 전체 히스토리 다운로드",
                    data=f,
                    file_name=f"delivery_history_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
        else:
            st.divider()
            st.info("아직 발송 히스토리가 없습니다. 메일을 발송하면 자동으로 생성됩니다.")
            uploaded_history = st.file_uploader("기존 히스토리 파일 업로드 (CSV)", type=['csv'], key="history_init")
            if uploaded_history:
                try:
                    df = pd.read_csv(uploaded_history)
                    df.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
                    st.success("✅ 히스토리 파일이 업로드되었습니다. 이제 이 파일에 기록이 누적됩니다!")
                    st.rerun()
                except Exception as e:
                    st.error(f"파일 업로드 오류: {e}")

    # OAuth 인증이 완료되지 않으면 메인 기능 비활성화
    if not oauth_handler:
        st.warning("Gmail 인증이 필요합니다. 사이드바에서 로그인을 진행해 주세요.")
        # 만약 URL에 code가 포함되어 리다이렉트 된 상태라면, 
        # 위 render_oauth_section 내의 handle_oauth_flow가 처리 후 재실행할 것임.
        return

    # Main: File Upload
    col1, col2 = st.columns(2)
    
    with col1:
        uploaded_file = st.file_uploader("1️⃣ 주문/배송 데이터 (CSV)", type=['csv'])
        
    with col2:
        mail_list_file = st.file_uploader("2️⃣ 협력사 메일 리스트 (CSV/Excel)", type=['csv', 'xlsx'])

    # Optional Template
    with st.expander("3️⃣ 메일 템플릿 수정 (선택사항)"):
        col_t1, col_t2 = st.columns(2)
        
        with col_t1:
            st.markdown("**일반 배송지연 템플릿**")
            default_template = """**제목: [배송확인] {{협력사명}} 배송 지연 건 확인 요청 드립니다**

안녕하세요, {{협력사명}} 담당자님.

귀사의 일익 번창을 기원합니다.
현재 아래 주문 건에 대하여 배송 흐름이 확인되지 않거나 지연되고 있어 확인 요청드립니다.

**[요청 사항]**
**정확한 출고 예정일**을 회신 부탁드립니다.
품절로 취소가 필요할 경우 **품절**로 회신 부탁드립니다.

**[확인 요청 상세 정보]**

| 상품코드 | 상품명 | 단품명 | 주문번호 | 운송장번호 |
| :--- | :--- | :--- | :--- | :--- |
| {{상품코드}} | {{상품명}} | {{단품명}} | {{주문번호}} | {{운송장번호}} |

바쁘시겠지만 빠른 확인 부탁드립니다.
감사합니다."""
            template_input = st.text_area("템플릿 내용", value=default_template, height=300, key="template_normal")
        
        with col_t2:
            st.markdown("**출고예정일 경과 템플릿**")
            default_overdue_template = """**제목: [긴급] {{협력사명}} 출고예정일 경과 건 확인 요청 드립니다**

안녕하세요, {{협력사명}} 담당자님.

귀사의 일익 번창을 기원합니다.
현재 아래 주문 건에 대하여 **출고예정일이 경과**하였으나 배송이 진행되지 않아 긴급 확인 요청드립니다.

**[요청 사항]**
**즉시 출고 가능 여부** 및 **정확한 출고 예정일**을 회신 부탁드립니다.
품절로 취소가 필요할 경우 **품절**로 회신 부탁드립니다.

**[출고예정일 경과 상세 정보]**

| 상품코드 | 상품명 | 단품명 | 주문번호 | 운송장번호 |
| :--- | :--- | :--- | :--- | :--- |
| {{상품코드}} | {{상품명}} | {{단품명}} | {{주문번호}} | {{운송장번호}} |

출고예정일이 지났으니 **긴급한 확인**이 필요합니다.
빠른 회신 부탁드립니다.
감사합니다."""
            template_overdue_input = st.text_area("템플릿 내용", value=default_overdue_template, height=300, key="template_overdue")

    # Analyze Button
    if uploaded_file and mail_list_file:
        if st.button("🔍 데이터 분석 및 메일 생성", type="primary"):
            try:
                data_df = safe_read_csv(uploaded_file, "주문/배송 데이터")

                if mail_list_file.name.endswith('.csv'):
                    mail_list_df = safe_read_csv(mail_list_file, "협력사 메일 리스트")
                else:
                    mail_list_df = pd.read_excel(mail_list_file)
                
                mailer = SaaSMailer(data_df, mail_list_df, template_input, template_overdue_input)
                
                with st.spinner("분석 중..."):
                    mail_items, logs = mailer.filter_and_process()
                
                with st.expander("처리 로그 보기", expanded=False):
                    for log in logs:
                        st.write(log)
                
                if not mail_items:
                    st.warning("⚠️ 발송할 대상(배송지연 분류가 비어있는 항목)이 없습니다.")
                else:
                    mail_items.sort(key=lambda x: 0 if x['email'] else 1)
                    st.success(f"✅ 총 {len(mail_items)}개의 안내 메일이 생성되었습니다.")
                    st.session_state['mail_items'] = mail_items
                    st.session_state['ready_to_send'] = True
                    
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")
                
    # Preview and Send Section
    if st.session_state.get('ready_to_send') and st.session_state.get('mail_items'):
        mail_items = st.session_state['mail_items']
        
        st.divider()
        st.subheader("📋 메일 미리보기 & 발송")
        
        # UI: Preview Tabs
        if len(mail_items) > 10:
            selected_partner = st.selectbox("협력사 선택", [m['partner_name'] for m in mail_items])
            preview_item = next((m for m in mail_items if m['partner_name'] == selected_partner), None)
            display_items = [preview_item] if preview_item else []
            if display_items:
                render_preview(display_items[0])
        else:
            tabs = st.tabs([f"{m['partner_name']} ({m['count']}건)" for m in mail_items])
            for tab, item in zip(tabs, mail_items):
                with tab:
                    render_preview(item)

        st.divider()
        col_send, col_dummy = st.columns([1, 4])
        with col_send:
            if st.button("🚀 전체 메일 발송 시작", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_area = st.empty()
                
                success_cnt = 0
                fail_cnt = 0
                send_results = {} 

                valid_items = [item for item in mail_items if item['email']]
                
                # 이메일 없는 건들은 Skipped 처리
                for item in mail_items:
                    if not item['email']:
                        send_results[item['partner_name']] = {'success': False, 'msg': 'No Email Address'}

                if not valid_items:
                    st.warning("발송할 유효한 이메일 대상이 없습니다. (히스토리는 저장됩니다)")
                else:
                    for i, item in enumerate(valid_items):
                        status_area.write(f"sending to {item['partner_name']}...")
                        
                        # OAuth를 사용한 메일 전송
                        temp_mailer = SaaSMailer(None, None, None, None)
                        html_content = temp_mailer.markdown_to_html(item['content'])
                        
                        # 제목 추출
                        subject_line = item['content'].split('\n')[0].replace('**제목:', '').replace('**', '').strip()
                        
                        success, msg = oauth_handler.send_email(
                            to_email=item['email'],
                            subject=subject_line,
                            html_content=html_content,
                            from_name=sender_name
                        )
                        
                        send_results[item['partner_name']] = {'success': success, 'msg': msg}
                        
                        if success:
                            success_cnt += 1
                        else:
                            fail_cnt += 1
                            st.write(f"❌ {item['partner_name']} 실패: {msg}")
                            
                        progress_bar.progress((i + 1) / len(valid_items))
                
                status_area.write("완료!")
                
                # 히스토리 저장
                save_history_log(mail_items, send_results)
                
                st.success(f"발송 완료! 성공: {success_cnt}, 실패: {fail_cnt} (히스토리 저장 완료)")


def render_preview(item):
    st.markdown(f"**수신**: {item['email'] if item['email'] else '❌ 이메일 없음'}")
    import streamlit.components.v1 as components
    temp_mailer = SaaSMailer(None, None, None, None)
    html_content = temp_mailer.markdown_to_html(item['content'])
    with st.expander("HTML 미리보기", expanded=True):
        components.html(html_content, height=400, scrolling=True)
    with st.expander("원본 텍스트 보기"):
        st.text(item['content'])

if __name__ == "__main__":
    main()