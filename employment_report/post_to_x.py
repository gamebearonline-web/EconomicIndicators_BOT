import os
import requests
from requests_oauthlib import OAuth1

def post_to_x(text: str) -> dict:
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        raise RuntimeError("X secrets missing (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)")

    auth = OAuth1(api_key, api_secret, access_token, access_secret)

    r = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        timeout=25,
    )
    r.raise_for_status()
    return r.json()
