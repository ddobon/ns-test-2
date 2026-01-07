import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re

class SaaSMailer:
    def __init__(self, data_df, mail_list_df, template_content):
        """
        Args:
            data_df: DataFrame from input_template.csv
            mail_list_df: DataFrame from mail_list.csv (or excel)
            template_content: String content of mail_template.md
        """
        self.df = data_df
        self.mail_list = mail_list_df
        self.template = template_content
        
    def filter_and_process(self):
        """Web-friendly processing pipeline"""
        logs = []
        
        # 1. Filter
        logs.append("🔍 Filtering data...")
        filtered_df = self.df[self.df['배송지연 분류'].isna() | (self.df['배송지연 분류'] == '')].copy()
        
        required_columns = [
            '협력사코드', '협력사명', '상품코드', '상품명', 
            '단품명', '주문번호', '운송장번호'
        ]
        
        # Ensure columns exist
        missing_cols = [col for col in required_columns if col not in filtered_df.columns]
        if missing_cols:
             raise ValueError(f"Missing required columns in CSV: {missing_cols}")

        result_df = filtered_df[required_columns]
        logs.append(f"✓ Filtered {len(result_df)} rows from {len(self.df)} total rows.")
        
        if len(result_df) == 0:
            return [], logs

        # 2. Group
        grouped = result_df.groupby('협력사명')
        logs.append(f"✓ Grouped into {len(grouped)} partners.")
        
        # 3. Generate Mails
        mail_items = []
        
        for partner_name, group_df in grouped:
            partner_code = group_df.iloc[0]['협력사코드']
            
            # Create content
            mail_content = self.create_mail_content(partner_name, group_df)
            
            # Find Email
            email = self.get_partner_email(partner_name, partner_code)
            
            mail_items.append({
                'partner_name': partner_name,
                'partner_code': partner_code,
                'email': email,
                'content': mail_content,
                'count': len(group_df),
                'df': group_df # Keep ref for preview if needed
            })
            
        logs.append(f"✓ Generated {len(mail_items)} mail drafts.")
        return mail_items, logs

    def create_table(self, group_df):
        table_rows = []
        for _, row in group_df.iterrows():
            table_row = f"| {row['상품코드']} | {row['상품명']} | {row['단품명']} | {row['주문번호']} | {row['운송장번호'] if pd.notna(row['운송장번호']) else '-'} |"
            table_rows.append(table_row)
        return '\n'.join(table_rows)

    def create_mail_content(self, partner_name, group_df):
        table_content = self.create_table(group_df)
        mail_content = self.template.replace(
            '| {{상품코드}} | {{상품명}} | {{단품명}} | {{주문번호}} | {{운송장번호}} |',
            table_content
        )
        mail_content = mail_content.replace('{{협력사명}}', partner_name)
        return mail_content

    def get_partner_email(self, partner_name, partner_code):
        # Case insensitive search could be added here if needed
        # Ensuring column names match what we expect from mail_list
        # The user provided mail_list has '협력사명', '협력사코드', '영업담당자E-MAIL'
        
        result = self.mail_list[self.mail_list['협력사명'] == partner_name]
        if result.empty and partner_code:
            # Handle potential type mismatch (int vs str) for code
            # Try to convert everything to string for comparison
            p_code_str = str(partner_code).split('.')[0] # handle float 1010.0 -> 1010
            
            # Create a localized copy for safe type casting
            temp_mail_list = self.mail_list.copy()
            temp_mail_list['협력사코드'] = temp_mail_list['협력사코드'].astype(str).str.split('.').str[0]
            
            result = temp_mail_list[temp_mail_list['협력사코드'] == p_code_str]

        if not result.empty:
            return result.iloc[0]['영업담당자E-MAIL']
        return None

    def markdown_to_html(self, markdown_text):
        """
        Convert markdown to simple HTML for email. 
        Reuse logic from script_v1.1.py but ensuring refined fix.
        """
        html = markdown_text
        
        # 1. Tables
        lines = html.split('\n')
        i = 0
        result_lines = []
        
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('|') and line.endswith('|') and '|' in line[1:-1]:
                table_lines = []
                while i < len(lines):
                    curr = lines[i].strip()
                    if curr.startswith('|') and curr.endswith('|'):
                        table_lines.append(curr)
                        i += 1
                    else:
                        break
                
                if len(table_lines) >= 3:
                     # Parse
                    header_line = table_lines[0]
                    headers = [c.strip() for c in header_line[1:-1].split('|')]
                    
                    data_rows = []
                    for dl in table_lines[2:]: # Skip separator
                        cells = [c.strip() for c in dl[1:-1].split('|')]
                        if any(cells): data_rows.append(cells)
                    
                    # Build HTML without newlines to avoid <br> issues
                    tbl = '<table style="border-collapse: collapse; width: 100%; margin: 20px 0; border: 1px solid #dee2e6;">'
                    tbl += '<thead><tr style="background-color: #4a5568; color: white;">'
                    for h in headers:
                        tbl += f'<th style="border: 1px solid #dee2e6; padding: 12px; text-align: left; font-weight: bold;">{h}</th>'
                    tbl += '</tr></thead><tbody>'
                    
                    for idx, row in enumerate(data_rows):
                        bg = '#ffffff' if idx % 2 == 0 else '#f8f9fa'
                        tbl += f'<tr style="background-color: {bg};">'
                        for c in row:
                            val = c if c else '-'
                            tbl += f'<td style="border: 1px solid #dee2e6; padding: 10px;">{val}</td>'
                        tbl += '</tr>'
                    tbl += '</tbody></table>'
                    result_lines.append(tbl)
                else:
                    result_lines.extend(table_lines)
            else:
                result_lines.append(lines[i])
                i += 1
                
        html = '\n'.join(result_lines)

        # 2. Markdown syntax replacements
        # Headers
        html = re.sub(r'^### (.+)$', r'<h3 style="color: #333; margin-top: 20px; margin-bottom: 10px;">\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2 style="color: #333; margin-top: 25px; margin-bottom: 15px;">\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1 style="color: #333; margin-top: 30px; margin-bottom: 20px;">\1</h1>', html, flags=re.MULTILINE)
        
        # Bold/Italic
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        
        # Lists (Basic)
        # For simplicity in this regex approach, we handle single-level bullets
        html = re.sub(r'^- (.+)$', r'<li style="margin: 5px 0;">\1</li>', html, flags=re.MULTILINE)
        # Wrap lis in ul? This is tricky with regex alone for multi-blocks, 
        # but let's try a simple block replacement if multiple lis exist
        # Or just leave them as li elements; email clients usually handle them okayish or we wrap them in a p?
        # Better: Wrap consecutive li lines.
        html = re.sub(r'(<li.*?</li>(\n)?)+', r'<ul style="margin: 10px 0; padding-left: 20px;">\g<0></ul>', html, flags=re.DOTALL)

        # Links
        html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2" style="color: #007bff; text-decoration: none;">\1</a>', html)
        
        # Newlines to <br> (but not inside HTML tags ideally)
        # Simple approach: Replace \n that are NOT inside tags. 
        # Since we removed checks for tags, we should be careful. 
        # But we reconstructed the table without \n, so \n now mostly exists in text paragraphs.
        
        # Convert double newline to P
        html = html.replace('\n\n', '</p><p style="margin: 10px 0;">')
        html = html.replace('\n', '<br>')
        
        return f'<div style="font-family: sans-serif; line-height: 1.6; color: #333;">{html}</div>'

    def send_single_mail(self, mail_item, smtp_config):
        """return (success, message)"""
        try:
            if not mail_item['email']:
                return False, "No Email Address"

            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[배송확인] {mail_item['partner_name']} 배송 지연 건 확인 요청 드립니다"
            msg['From'] = f"{smtp_config['from_name']} <{smtp_config['from_email']}>"
            msg['To'] = mail_item['email']

            html_content = self.markdown_to_html(mail_item['content'])
            part_text = MIMEText(mail_item['content'], 'plain', 'utf-8')
            part_html = MIMEText(html_content, 'html', 'utf-8')

            msg.attach(part_text)
            msg.attach(part_html)

            with smtplib.SMTP(smtp_config['server'], smtp_config['port']) as server:
                server.starttls()
                server.login(smtp_config['username'], smtp_config['password'])
                server.send_message(msg)
            
            return True, "Sent"
        except Exception as e:
            return False, str(e)
