#!/usr/bin/env python3

import requests

response = requests.get("http://localhost:5000/world")
if response.status_code == 200:
    exit(0)
else:
    exit(1)

