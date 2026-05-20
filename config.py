import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

API_BASE = "https://prod20327-138271283.fssb.io/api/eventlist/eu"
SPORTS_URL = f"{API_BASE}/navigation/v2/sports"
EVENTS_URL = f"{API_BASE}/events/v2"

TOKEN_REFRESH_URL = (
    "https://prod20327-138271283.fssb.io/es/spbk/"
    "?operatorToken=logout"
    "&api=https%3A%2F%2Fbet30-vip.ai%2Fjs%2Fbti.js%3Fv%3D2200"
)

FOOTBALL_SPORT_ID = "1"

POLL_INTERVAL = 120  # seconds between checks for new matches

ODDS_CHANGE_NOTIFICATIONS = False  # notificar cuando las cuotas cambian

HEADERS = {
    "accept": "application/json",
    "accept-language": "es-AR,es;q=0.9",
    "authorization": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJsYW5ndWFnZUNvZGUiOiJlcyIsImN1cnJlbmN5UmF0ZSI6MSwiY3VycmVuY3lSYXRlZXVyIjoxLCJjdXN0b21lckxpbWl0cyI6W10sImN1c3RvbWVyVHlwZSI6ImFub24iLCJjdXJyZW5jeUNvZGUiOiJBUlMiLCJjdXJyZW5jeUNvZGVBbm9uIjoiIiwiY3VzdG9tZXJJZCI6LTEsImJldHRpbmdWaWV3IjoiRXVyb3BlYW4gVmlldyIsInNvcnRpbmdUeXBlSWQiOjAsImJldHRpbmdMYXlvdXQiOjEsImRpc3BsYXlUeXBlSWQiOjEsInRpbWV6b25lSWQiOjEwLCJhdXRvVGltZVpvbmUiOjEsImxhc3RJbnB1dFN0YWtlIjowLCJldU9kZHNJZCI6IjEiLCJhc2lhbk9kZHNJZCI6IjMiLCJrb3JlYW5PZGRzSWQiOiIxIiwiaW50VGFiRXhwYW5kZWQiOjEsImRvbWFpbklEIjoyOTU2LCJhZ2VudElEIjoxMzgyNzEyODMsInNpdGVJZCI6MjAzMjcsInNlbGVjdGVkT3B0aW9uSWQiOjAsImN1c3RvbWVyTGV2ZWwiOjAsImJhbGFuY2VQcmlvcml0eSI6MSwiRVBPRW5hYmxlZCI6dHJ1ZSwiaWF0IjoxNzc4NTE2MTA4fQ"
        ".HtaqT5LUIR5fRRxOckp1qZWxf-DzZgmuxJigwTFkT2U"
    ),
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
}

COOKIES = {
    "session": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJjdXN0b21lcklkIjotMSwiZXhwaXJlZERhdGUiOjE3Nzg2MDI1MDg0NDMsImlhdCI6MTc3ODUxNjEwOH0"
        ".NPmWnh64axA7BHkM8Peq-gmHfpyGxDR-yPXngN9BxsE"
    ),
}
