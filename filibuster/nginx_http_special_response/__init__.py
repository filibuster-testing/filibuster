# Special responses adapted from https://github.com/nginx/nginx/blob/release-1.15.8/src/http/ngx_http_special_response.c#L132

special_responses_format1 = {
    301: "301 Moved Permanently",
    302: "302 Found",
    303: "303 See Other",
    307: "307 Temporary Redirect",
    308: "308 Permanent Redirect",
    400: "400 Bad Request",
    401: "401 Authorization Required",
    402: "402 Payment Required",
    403: "403 Forbidden",
    404: "404 Not Found",
    405: "405 Not Allowed",
    406: "406 Not Acceptable",
    408: "408 Request Time-out",
    409: "409 Conflict",
    410: "410 Gone",
    411: "411 Length Required",
    412: "412 Precondition Failed",
    413: "413 Request Entity Too Large",
    414: "414 Request-URI Too Large",
    415: "415 Unsupported Media Type",
    416: "416 Requested Range Not Satisfiable",
    421: "421 Misdirected Request",
    429: "429 Too Many Requests",
    500: "500 Internal Server Error",
    501: "501 Not Implemented",
    502: "502 Bad Gateway",
    503: "503 Service Temporarily Unavailable",
    504: "504 Gateway Time-out",
    505: "505 HTTP Version Not Supported",
    507: "50 Insufficient Storage"
}

special_responses_format2 = {
    494: "Request Header or Cookie Too Large",
    495: "The SSL certificate error",
    496: "No required SSL certificate was sent",
    497: "The plain HTTP request was sent to HTTPS port"
}

def get_response(status_code):
    error_msg = ""
    print(status_code)
    if status_code in special_responses_format1:
        status_error = special_responses_format1[status_code]
        error_msg += f"<html>\n<head><title>{status_error}</title></head>\n<body>\n<center><h1>{status_error}</h1><center>"
    if status_code in special_responses_format2:
        status_error = special_responses_format2[status_code]
        error_msg += f"<html>\n<head><title>400 {status_error}</title></head>\n<body>\n<center><h1>400 Bad Request</h1><center><center>{status_error}</center>"
    return error_msg