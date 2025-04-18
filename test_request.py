import requests
import json

url = "http://localhost:5000/add-link"
payload = {
    "category": "Sheet1",
    "link": "https://example.com/test",
    "summary": "Test link",
    "source": "Test source",
    "date": "2025-04-17"
}

headers = {
    "Content-Type": "application/json"
}

response = requests.post(url, data=json.dumps(payload), headers=headers)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}") 