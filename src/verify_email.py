import email
import imaplib
import re
import time

from curl_cffi import requests
from loguru import logger

import config
from config import yes_client_key, email_worker_num
from pool_manager import ThreadPoolManager
from proxy import get_cf_solver_proxy, get_proxy

pm = ThreadPoolManager(email_worker_num)


def _precheck_verify_link(sm, link):
    logger.debug(f"开始使用之前成功的信息跳过cf")
    info = sm.get_success_info()
    client = requests.Session()
    user_agent = info[1]
    client.proxies = {"http": info[2], "https": info[2]}
    client.headers.update({"User-Agent": user_agent})
    cookies = info[0]
    if cookies:
        for name, value in cookies.items():
            client.cookies.set(name, value)

    try:
        response_get = client.get(link, allow_redirects=False, timeout=30)
        print("GET请求的响应：", response_get)
        if response_get.status_code == 302:
            redirect_url = response_get.headers["Location"]
            logger.debug(f"redirect url: {redirect_url}")
            res = client.get(redirect_url, allow_redirects=False)
            logger.debug(f"redirect 响应: {res.text}")
            if "<title>OpenAI Platform</title>" not in res.text:
                logger.debug(f"自动跳过cf失败,将使用yes绕过")
                _click_verify_link(sm, link)
            else:
                return True
        else:
            _click_verify_link(sm, link)
    except Exception as e:
        _click_verify_link(sm, link)


def _click_verify_link(sm, link):
    client = requests.Session(proxies={"http": get_proxy(), "https": get_proxy()})

    url = "https://api.yescaptcha.com/createTask"

    request = {
        "clientKey": yes_client_key,
        "task": {
            "type": "CloudFlareTaskS2",
            "websiteURL": link,
            "proxy": get_cf_solver_proxy(),
            "waitLoad": True,
        },
        "softID": 31275,
    }

    task_id = None
    for i in range(3):
        resp = client.post(
            url, json=request, proxies={"http": get_proxy(), "https": get_proxy()}
        )
        resp_json = resp.json()
        task_id = resp_json["taskId"]
        if task_id:
            break
        else:
            time.sleep(3)

    if not task_id:
        raise Exception("failed to create task")

    logger.debug(f"created task {task_id} for link {link}")
    while True:
        task_url = "https://api.yescaptcha.com/getTaskResult"
        resp = client.post(
            task_url,
            json={"clientKey": yes_client_key, "taskId": task_id},
            proxies={"http": get_proxy(), "https": get_proxy()},
        )
        resp_json = resp.json()
        if resp_json["status"] == "processing":
            time.sleep(6)
        elif resp_json["errorId"] == 0 and resp_json["status"] == "ready":
            break
        elif resp_json["errorId"] == 1:
            raise Exception(f"task {task_id} error: {resp_json['errorDescription']}")
        else:
            raise Exception("unknown status")

    error_id = resp_json["errorId"]
    logger.debug(f"task {task_id} 返回结果: {resp_json}")

    if error_id == 0:
        logger.debug(f"success verify email link {link}")
        try:
            cf_clearance = resp_json["solution"]["cookies"]["cf_clearance"]
            if cf_clearance:
                sm.set_success_info(resp_json["solution"], get_proxy())
                return cf_clearance
        except Exception as e:
            raise Exception(f"failed to get cf_clearance from {resp_json}")

    raise Exception(
        f"failed to verify email link {link} error id {error_id} task id {task_id}"
    )


def click_verify_link(sm, link):
    success = False
    for i in range(3):
        try:
            # _click_verify_link(sm, link)
            _precheck_verify_link(sm, link)
            success = True
            break
        except Exception as e:
            logger.warning(f"failed to click verify link {link} retry {i + 1} times")
            time.sleep(3)

    if not success:
        logger.error(f"failed to click verify link {link} please check your proxy")


def verify_email(sm):
    username = config.email_addr
    password = config.email_password
    imap_server = config.email_imap_server
    email_imap_port = config.email_imap_port
    if email_imap_port:
        mail = imaplib.IMAP4_SSL(imap_server, port=email_imap_port)
    else:
        mail = imaplib.IMAP4_SSL(imap_server)
    try:
        mail.login(username, password)
    except Exception as e:
        raise e

    logger.debug("start to monitor openai verify email")

    def get_html_part(msg):
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    charset = part.get_content_charset()
                    payload = part.get_payload(decode=True)
                    try:
                        return payload.decode(charset or "utf-8", errors="replace")
                    except LookupError:
                        return payload.decode("utf-8", errors="replace")
        else:
            if msg.get_content_type() == "text/html":
                charset = msg.get_content_charset()
                payload = msg.get_payload(decode=True)
                try:
                    return payload.decode(charset or "utf-8", errors="replace")
                except LookupError:
                    return payload.decode("utf-8", errors="replace")

    def check_mail():
        mail.select("INBOX")
        status, messages = mail.search(None, '(UNSEEN FROM "noreply@tm.openai.com")')
        messages = messages[0].split()

        for mail_id in messages:
            if sm.should_stop():
                break

            status, data = mail.fetch(mail_id, "(RFC822)")
            for response in data:
                if isinstance(response, tuple):
                    msg = email.message_from_bytes(response[1])
                    from_ = msg.get("From")
                    if "openai" in from_:
                        html_content = get_html_part(msg)
                        if "Verify your email address" in html_content:
                            link = re.search(
                                r'href="(https://mandrillapp.com[^"]+)"', html_content
                            )
                            if link:
                                link = link.group(1)
                                pm.add_task(lambda: click_verify_link(sm, link))

    try:
        while True and not sm.should_stop():
            check_mail()
            time.sleep(10)
    except Exception as e:
        sm.stop_with_message(
            "email worker stopped pls check your network or email account and password"
        )
    finally:
        mail.logout()


if __name__ == "__main__":
    verify_email()
