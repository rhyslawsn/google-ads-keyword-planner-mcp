"""One-off helper: run the OAuth flow locally and print a refresh token.

Usage:
    pip install google-auth-oauthlib
    GOOGLE_ADS_CLIENT_ID=... GOOGLE_ADS_CLIENT_SECRET=... python get_refresh_token.py

Sign in with a Google user that has access to the Google Ads account.
"""

import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords"]

client_config = {
    "installed": {
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nGOOGLE_ADS_REFRESH_TOKEN=" + creds.refresh_token)
