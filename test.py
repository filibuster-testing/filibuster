#!/usr/bin/env python3

import requests

response = requests.get("http://localhost:5000/users/chris_rivers/bookings")
print("**** TEST RECEIVED OUTPUT: " + str(response.status_code))

###

print("Fault injected?")
f_response = requests.get("http://localhost:5005/fault-injected")
print(f_response.status_code)
print(f_response.json())
print("")

print("Fault injected on HELLO service?")
f_response = requests.get("http://localhost:5005/fault-injected/hello")
print(f_response.status_code)
print(f_response.json())
print("")

print("Fault injected on WORLD service?")
f_response = requests.get("http://localhost:5005/fault-injected/world")
print(f_response.status_code)
print(f_response.json())
print("")

###
#
# if response.status_code == 200:
#     exit(0)
# else:
#     exit(1)

