


#%%%
from slack_sdk import WebClient
import os
#%%
class SlackConnector:
    
    def __init__(self,
                 token_path: str = f'{os.path.expanduser("~")}/configuration/keys/slack_token.txt',
                 default_channel_id: str = 'C0AUD37DQG5'):
        token = open(token_path, 'r').read()
        self.client = WebClient(token=token)
        self.channel_id = default_channel_id
        self.channel_name = self._get_channel_name(default_channel_id) if default_channel_id else None

    def __repr__(self):
        channel_info = f"Channel: {self.channel_name or 'No channel selected'}"
        return f"<SlackConnector({channel_info})>"

    def _get_channel_name(self, channel_id):
        """
        Retrieve the channel name using the channel ID.
        """
        try:
            result = self.client.conversations_info(channel=channel_id)
            return result['channel']['name']
        except Exception as e:
            print(f"Failed to fetch channel name for ID {channel_id}: {e}")
            return "Unknown Channel"

    def get_channel_id(self, channel_name):
        """
        Get channel ID based on the channel name.
        """
        private_channels = self.client.conversations_list(types="private_channel").data['channels']
        public_channels = self.client.conversations_list(types="public_channel").data['channels']
        channels = private_channels + public_channels
        channel = list(filter(lambda c: c["name"] == channel_name, channels))
        
        if len(channel) == 0:
            raise ValueError(f"Channel {channel_name} not found")
        else:
            return channel[0]["id"]
    
    def select_channel(self, channel_name):
        """
        Select a channel based on the channel name.
        """
        self.channel_id = self.get_channel_id(channel_name)
        self.channel_name = channel_name

    def get_message_ts(self, match_string):
        """
        Retrieve a message timestamp in the selected Slack channel.
        """
        if self.channel_id is None:
            raise ValueError("Channel is not selected")
        result = self.client.conversations_history(channel=self.channel_id)
        messages = result.data['messages']
        matched_messages = list(filter(lambda m: match_string in m["text"], messages))
        if len(matched_messages) == 0:
            print(f"Message {match_string} not found")   
            return None
        message_ts = matched_messages[0]["ts"]
        return message_ts

    def post_thread_message(self, message_ts, text = None, blocks = None):
        """
        Post a message to a thread in the selected Slack channel.
        """
        if self.channel_id is None:
            raise ValueError("Channel is not selected")
        result = self.client.chat_postMessage(
            channel=self.channel_id,
            text=text,
            blocks = blocks,
            thread_ts=message_ts
        )
        print(f'Thread message posted: text = {text}, blocks = {blocks}')
        return result

    def upload_file_to_thread(self, file_path: str, thread_ts: str, title: str = None):
        """Upload a file as a reply to an existing Slack thread."""
        if self.channel_id is None:
            raise ValueError("Channel is not selected")
        self.client.files_upload_v2(
            channel=self.channel_id,
            file=file_path,
            title=title or os.path.basename(file_path),
            thread_ts=thread_ts
        )

    def post_message(self, text = None, blocks = None):
        """
        Post a message to the selected Slack channel.
        """
        if self.channel_id is None:
            raise ValueError("Channel is not selected")
        result = self.client.chat_postMessage(
            channel=self.channel_id,
            text=text,
            blocks = blocks
        )
        print(f'Message posted: text = {text}, blocks = {blocks}')
        return result
