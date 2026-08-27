#%%
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import List, Dict
import os
from datetime import datetime, timedelta, timezone
import json
import time

class GmailConnector:
    def __init__(self, user_account: str, user_token_path: str = None):
        self.user_account = user_account
        self.user_token_path = user_token_path
        self.user_token = None
        if not user_token_path:
            self.user_token_path = f'{os.path.expanduser("~")}/.config/gmail/python/token_{self.user_account}.txt'
        try:
            self.user_token = open(self.user_token_path, 'r').read().strip()
            if '\xa0' in self.user_token:
                self.user_token = self.user_token.replace('\xa0', ' ')
        except:
            raise ValueError(f'Error reading the token file at {self.user_token_path} or token is not provided')
        self.smtp_server = 'smtp.gmail.com'
        self.smtp_port = 587
        self.imap_server = 'imap.gmail.com'
        self.logged_in_imap = False  # Track login status
        self.logged_in_smtp = False  # Track login status
        self.server_imap = None
        self.server_smtp = None

    def __repr__(self):
        return f"<GmailConnector(user_account='{self.user_account}', logged_in={self.logged_in})>"

    def ensure_logged_in_imap(self):
        """Check if connections to IMAP servers are still alive."""
        if self.server_imap:
            try:
                self.server_imap.noop()  # Send a no-operation command to test connection
            except Exception as e:
                print(f"IMAP connection lost: {e}")
                self.logged_in_imap = False

        if not self.logged_in_imap:
            print("The account is not logged in. Try login...")
            self.login_imap()
        return True
    
    def ensure_logged_in_smtp(self):
        """Check if connections to SMTP servers are still alive."""
        if self.server_smtp:
            try:
                self.server_smtp.noop()  # SMTP doesn't officially support NOOP but try a simple command
            except Exception as e:
                print(f"SMTP connection lost: {e}")
                self.logged_in_smtp = False

        if not self.logged_in_smtp:
            print("The account is not logged in. Try login...")
            self.login_smtp()
        return True

    def login_imap(self):
        """Login to the IMAP server to check credentials and set login status."""
        try:
            # Connect to the IMAP server
            self.server_imap = imaplib.IMAP4_SSL(self.imap_server)
            self.server_imap.login(self.user_account, self.user_token)
            self.logged_in_imap = True
            print("IMAP Login successful.")
        except Exception as e:
            self.logged_in_imap = False
            print(f"Failed to login IMAP: {e}")
            
    def login_smtp(self):
        """Login to the IMAP server to check credentials and set login status."""
        try:

            # Connect to the SMTP server
            self.server_smtp = smtplib.SMTP(self.smtp_server, self.smtp_port)
            self.server_smtp.starttls()
            self.server_smtp.login(self.user_account, self.user_token)
            self.logged_in_smtp = True
            print("SMTP Login successful.")
        except Exception as e:
            self.logged_in_smtp = False
            print(f"Failed to login SMTP: {e}")
            
    def logout_imap(self):
        """Gracefully close connections to IMAP and SMTP servers."""
        if self.server_imap:
            try:
                self.server_imap.logout()
                print("Logged out of IMAP server.")
            except Exception as e:
                print(f"Error logging out of IMAP server: {e}")

        self.logged_in_imap = False
        
    def logout_smtp(self):
        """Gracefully close connections to IMAP and SMTP servers."""
        if self.server_smtp:
            try:
                self.server_smtp.quit()
                print("Logged out of SMTP server.")
            except Exception as e:
                print(f"Error logging out of SMTP server: {e}")

        self.logged_in_smtp = False
    
    def send_mail(self, to_users: str or list, cc_users : str or list, subject: str, body: str, attachments: list or str = None, text_type = 'plain'):
        """
        Send an email with optional attachments.
        
        Args:
            to_users (str or list): Recipient's email address.
            cc_users (str or list): CC recipient's email address.
            subject (str): Subject of the email.
            body (str): Body of the email.
            attachments (list or str): List of file paths to attach to the email.
        """
        if text_type not in ['plain', 'html']:
            raise ValueError("Invalid text_type. Must be 'plain' or 'html'.")
        self.ensure_logged_in_smtp()
        try:
            # Convert to_users and cc_users to lists if they are strings
            if isinstance(to_users, str):
                to_users = [to_users]
            if isinstance(cc_users, str):
                cc_users = [cc_users]

            # Compose the email
            msg = MIMEMultipart()
            msg['From'] = self.user_account
            msg['To'] = ", ".join(to_users)  # Display multiple recipients
            msg['Subject'] = subject
            if cc_users:
                msg['CC'] = ", ".join(cc_users)
            msg.attach(MIMEText(body, text_type))

            # Attach files if any
            if attachments:
                if isinstance(attachments, str):
                    attachments = [attachments]
                for file_path in attachments:
                    try:
                        with open(file_path, "rb") as attachment:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(attachment.read())
                            encoders.encode_base64(part)
                            part.add_header(
                                'Content-Disposition',
                                f'attachment; filename={os.path.basename(file_path)}'
                            )
                            msg.attach(part)
                    except Exception as e:
                        print(f"Failed to attach file {file_path}: {e}")

            # Combine all recipients (To + CC)
            all_recipients = to_users
            if cc_users:
                all_recipients += cc_users

            # Send the email
            try:
                self.server_smtp.sendmail(self.user_account, all_recipients, msg.as_string())
            except:
                print('Sending email failed. Try to login again...')
                self.login_smtp()
                time.sleep(5)
                self.server_smtp.sendmail(self.user_account, all_recipients, msg.as_string())
            # Logout of the SMTP server
            self.logout_smtp()
            print("Email sent successfully.")
        except Exception as e:
            print(f"Failed to send email: {e}")
    
    def read_mail(self,
                  mailbox: str = 'inbox',
                  max_numbers: int = 10,
                  since_days : float = 5,
                  save : bool = True,
                  save_dir : str = '../alert_history/gmail'
                  ) -> List[Dict]:
        """
        Read emails and save attachments.

        Args:
            mailbox (str): The mailbox to read from.
            max_numbers (int): The maximum number of emails to fetch.
            save_dir (str): Directory to save attachments.

        Returns:
            List[Dict]: A list of dictionaries containing email details and attachment info.
        """

        # Function to extract and decode the 'From' field
        def get_sender_email(mail_from):
            # Parse the 'From' field
            if '<' in mail_from and '>' in mail_from:
                # Separate name and email
                name, email_address = mail_from.split('<')
                email_address = email_address.strip('>')

                # Decode the name part if it's encoded
                decoded_name, encoding = decode_header(name.strip())[0]
                if isinstance(decoded_name, bytes):  # Decode bytes if necessary
                    decoded_name = decoded_name.decode(encoding or 'utf-8')
                return decoded_name, email_address
            else:
                return None, mail_from

        self.ensure_logged_in_imap()
        emails = []

        try:
            # Connect to the IMAP server
            self.server_imap.select(mailbox)

            print('Searching for emails...')
            # Search for all emails
            search_criteria = 'ALL'
            if since_days:
                since_time = datetime.utcnow() - timedelta(days=since_days)
                since_date = since_time.strftime('%d-%b-%Y')
                search_criteria = f'(SINCE "{since_date}")'
                print(f'Searching for emails since {since_date}...')

            status, data = self.server_imap.search(None, search_criteria)
            email_ids = data[0].split()
            print(f"{len(email_ids)} emails are found.")
            for email_id in email_ids[-max_numbers:]:
                # Fetch each email
                status, data = self.server_imap.fetch(email_id, '(RFC822)')
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Parse the email
                email_data = {
                    'From': get_sender_email(msg['From']),
                    'Subject': self._get_email_subject(msg),
                    'Date': msg['Date'],
                    'Body': self._get_email_body(msg),
                    'Attachments': []  # To store attachment info
                }
                parsed_date = parsedate_to_datetime(email_data['Date'])
                utc_date = parsed_date.astimezone(timezone.utc)
                date_str = utc_date.strftime('%Y%m%d_%H%M%S')

                # Check for attachments
                if msg.is_multipart():
                    for part in msg.walk():
                        content_disposition = part.get("Content-Disposition", "")
                        if "attachment" in content_disposition:
                            # Get the filename
                            filename = part.get_filename()
                            if filename:
                                # Decode the filename
                                filename = decode_header(filename)[0][0]
                                if isinstance(filename, bytes):
                                    filename = filename.decode()

                                # Save the file
                                if save:
                                    save_dir_for_attachments = os.path.join(save_dir, date_str, 'attachments')
                                    if not os.path.exists(save_dir_for_attachments):
                                        os.makedirs(save_dir_for_attachments)
                                    attachment_path = os.path.join(save_dir_for_attachments, filename)
                                    with open(attachment_path, "wb") as f:
                                        f.write(part.get_payload(decode=True))
                                    # Append attachment info
                                    email_data['Attachments'].append(attachment_path)
                if save:
                    save_dir_for_email = os.path.join(save_dir, date_str)
                    if not os.path.exists(save_dir_for_email):
                        os.makedirs(save_dir_for_email)
                    email_path = os.path.join(save_dir_for_email, "body.txt")
                    with open(email_path, "w") as f:
                        json.dump(email_data, f, indent = 4)

                emails.append(email_data)

        except Exception as e:
            print(f"Failed to read emails: {e}")

        return emails
    
    def delete_mail(self, mailbox: str = 'inbox', subject: str = None):
        """Delete emails based on subject."""
        self.ensure_logged_in()
        try:
            self.server_imap.select(mailbox)
            
            # Search for emails by subject
            status, data = self.server_imap.search(None, f'SUBJECT "{subject}"')
            email_ids = data[0].split()
            for email_id in email_ids:
                self.server_imap.store(email_id, '+FLAGS', '\\Deleted')
            
            self.server_imap.expunge()
            self.server_imap.logout()
            print(f"Emails with subject '{subject}' deleted successfully.")
        except Exception as e:
            print(f"Failed to delete emails: {e}")

    def _get_email_body(self, msg) -> str:
        """Extract the body from an email message."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == 'text/plain':
                    return part.get_payload(decode=True).decode()
        else:
            return msg.get_payload(decode=True).decode()
        return ""
            
    def _get_email_subject(self, msg) -> str:
        """
        Extract and decode the subject of an email message.

        Args:
            msg (email.message.Message): The email message object.

        Returns:
            str: The decoded email subject.
        """
        subject = msg['Subject']
        if subject:
            decoded_parts = decode_header(subject)
            decoded_subject = ''
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    # Decode bytes using the specified encoding
                    decoded_subject += part.decode(encoding or 'utf-8', errors='ignore')
                else:
                    # If iti's already a string, just append it
                    decoded_subject += part
            return decoded_subject.strip()
        return "No Subject"

# %%
if __name__ == "__main__":
    from tcspy.configuration import mainConfig
    config = mainConfig()

    gc = GmailConnector(user_account = config.config['GMAIL_USERNAME'], user_token_path = config.config['GMAIL_TOKENPATH'])
    result = gc.read_mail()
# %%


class GmailTokenExpiredError(Exception):
    """Raised when the Gmail OAuth token can't be refreshed and interactive
    re-authorization is disabled (i.e. running unattended). The caller should
    alert loudly and re-mint the token via `python configuration/keys/gmail.py`
    rather than block on a browser consent flow that can never complete headless."""
    pass


class GmailPushReceiver:
    """Registers a Gmail watch on INBOX and polls Pub/Sub for new-mail notifications.

    Does NOT read email content — that is still handled by GmailConnector (IMAP).
    Call poll_pubsub() in a tight loop; when it returns True, call check_new_mail() as usual.
    """

    SCOPES = [
        'https://www.googleapis.com/auth/gmail.readonly',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/pubsub',
    ]

    def __init__(self, token_path: str, credentials_path: str, interactive: bool = False):
        self.token_path = token_path
        self.credentials_path = credentials_path
        # interactive=False (default) is the unattended/daemon mode: a dead token
        # raises GmailTokenExpiredError instead of opening a browser that would hang
        # monitoring.py forever. Only the manual mint script passes interactive=True.
        self.interactive = interactive
        self.service = None
        self._creds = None
        self._last_history_id = None
        self._build_service()

    def _build_service(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)
            except Exception:
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(self.token_path, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                if not self.interactive:
                    raise GmailTokenExpiredError(
                        f'Gmail token refresh failed ({e}). Re-mint with '
                        f'`python configuration/keys/gmail.py`.'
                    )
                print(f'[GmailPushReceiver] Token refresh failed ({e}). Re-authorizing...')
                creds = None

        if not creds or not creds.valid:
            if not self.interactive:
                raise GmailTokenExpiredError(
                    f'Gmail token at {self.token_path} is missing or invalid. Re-mint with '
                    f'`python configuration/keys/gmail.py`.'
                )
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, self.SCOPES)
            creds = flow.run_local_server(port=0)
            with open(self.token_path, 'w') as f:
                f.write(creds.to_json())
            print(f'[GmailPushReceiver] New token saved to {self.token_path}')

        self._creds = creds
        self.service = build('gmail', 'v1', credentials=creds)

    def send_mail(self, to_users, cc_users, subject: str, body: str, attachments=None, text_type: str = 'plain'):
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders as _encoders
        if isinstance(to_users, str):
            to_users = [to_users]
        if isinstance(cc_users, str):
            cc_users = [cc_users]
        msg = MIMEMultipart()
        msg['From'] = 'me'
        msg['To'] = ', '.join(to_users)
        msg['Subject'] = subject
        if cc_users:
            msg['CC'] = ', '.join(cc_users)
        msg.attach(MIMEText(body, text_type))
        if attachments:
            if isinstance(attachments, str):
                attachments = [attachments]
            for file_path in attachments:
                try:
                    with open(file_path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                        _encoders.encode_base64(part)
                        part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(file_path)}')
                        msg.attach(part)
                except Exception as e:
                    print(f'Failed to attach {file_path}: {e}')
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        # The service holds a long-lived HTTP/SSL connection that Google closes after
        # idle periods. Reusing it then fails with BrokenPipeError/ConnectionError on the
        # first send. Retry on transient connection errors, rebuilding the service first.
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self.service.users().messages().send(userId='me', body={'raw': raw}).execute()
                print('Email sent successfully.')
                return
            except (BrokenPipeError, ConnectionError, OSError) as e:
                if attempt == max_attempts:
                    raise
                print(f'Email send failed ({type(e).__name__}: {e}). '
                      f'Rebuilding Gmail service and retrying ({attempt}/{max_attempts - 1})...')
                self._build_service()

    def setup_watch(self, topic_name: str) -> dict:
        """Register Gmail push notifications to a Pub/Sub topic. Expires after 7 days;
        a daemon thread renews it automatically every 6 days."""
        result = self.service.users().watch(
            userId='me',
            body={'labelIds': ['INBOX'], 'topicName': topic_name}
        ).execute()
        self._last_history_id = result['historyId']
        import threading
        t = threading.Thread(target=self._renew_watch_loop, args=(topic_name,), daemon=True)
        t.start()
        return result

    def _renew_watch_loop(self, topic_name: str):
        time.sleep(6 * 24 * 3600)
        self.setup_watch(topic_name)

    def poll_pubsub(self, subscription_name: str) -> bool:
        """Pull from Pub/Sub. Returns True if at least one new-mail notification arrived."""
        from google.cloud import pubsub_v1
        subscriber = pubsub_v1.SubscriberClient(credentials=self._creds)
        try:
            response = subscriber.pull(
                request={'subscription': subscription_name, 'max_messages': 20},
                timeout=2,
            )
        except Exception as e:
            # 504 Deadline Exceeded is normal when no messages arrive within the timeout
            if '504' not in str(e):
                print(f"Pub/Sub pull error: {e}")
            return False
        if not response.received_messages:
            return False
        subscriber.acknowledge(request={
            'subscription': subscription_name,
            'ack_ids': [m.ack_id for m in response.received_messages],
        })
        return True

    def get_new_messages(self) -> list:
        """Return mail_dicts for INBOX messages added since _last_history_id via Gmail History API.
        Advances _last_history_id so subsequent calls are incremental."""
        if not self._last_history_id:
            return []
        try:
            history_resp = self.service.users().history().list(
                userId='me',
                startHistoryId=self._last_history_id,
                historyTypes=['messageAdded'],
            ).execute()
        except Exception as e:
            print(f"[GmailPushReceiver] history.list failed: {e}")
            return []

        new_cursor = history_resp.get('historyId')
        if new_cursor:
            self._last_history_id = new_cursor

        seen_ids = set()
        message_ids = []
        for record in history_resp.get('history', []):
            for entry in record.get('messagesAdded', []):
                msg = entry['message']
                if 'INBOX' in msg.get('labelIds', []) and msg['id'] not in seen_ids:
                    seen_ids.add(msg['id'])
                    message_ids.append(msg['id'])

        mail_dicts = []
        for msg_id in message_ids:
            try:
                msg_resp = self.service.users().messages().get(
                    userId='me', id=msg_id, format='full'
                ).execute()
                mail_dict = self._parse_message(msg_resp)
                if mail_dict:
                    mail_dicts.append(mail_dict)
            except Exception as e:
                print(f"[GmailPushReceiver] messages.get failed for {msg_id}: {e}")

        return mail_dicts

    def _parse_message(self, msg_resp: dict) -> dict:
        """Parse Gmail REST message into mail_dict format compatible with Alert.decode_mail()."""
        headers = {h['name']: h['value']
                   for h in msg_resp.get('payload', {}).get('headers', [])}
        from_str = headers.get('From', '')
        if '<' in from_str and '>' in from_str:
            name, addr = from_str.split('<', 1)
            addr = addr.rstrip('>')
            name = name.strip()
        else:
            name, addr = None, from_str.strip()
        return {
            'From': (name, addr),
            'Subject': headers.get('Subject', 'No Subject'),
            'Date': headers.get('Date', ''),
            'Body': self._extract_body(msg_resp.get('payload', {})),
            'Attachments': [],
        }

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract text/plain body from Gmail message payload."""
        import base64
        if payload.get('mimeType') == 'text/plain':
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data + '==').decode('utf-8', errors='replace')
        for part in payload.get('parts', []):
            result = self._extract_body(part)
            if result:
                return result
        return ''
