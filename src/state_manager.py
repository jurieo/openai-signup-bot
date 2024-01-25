import threading
from collections import deque

from config import max_success_accounts, max_failure_accounts
from log import logger
from proxy import get_cf_solver_proxy


class GlobalStateManager:
    def __init__(self):
        self.success_count = 0
        self.failure_count = 0
        self.recent_success_rate = deque(maxlen=20)
        self.lock = threading.Lock()
        self.max_success = max_success_accounts
        self.max_failure = max_failure_accounts
        self._should_stop = False
        self.cookie = None
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        self.proxy = get_cf_solver_proxy()

    def increment_success(self):
        with self.lock:
            self.success_count += 1
            self.recent_success_rate.append(1)
            if 0 < self.max_success <= self.success_count:
                self._should_stop = True
                logger.info("max success reached, stop running")

    def increment_failure(self):
        with self.lock:
            self.failure_count += 1
            self.recent_success_rate.append(0)

            if 0 < self.max_failure <= self.failure_count:
                self._should_stop = True
                logger.warning("max failure reached, stop running")

    def stop_with_message(self, message):
        with self.lock:
            self._should_stop = True
            logger.error(message)

    def should_stop(self):
        with self.lock:
            return self._should_stop

    def set_success_info(self, info, proxy):
        self.cookie = info['cookies']
        self.user_agent = info['user_agent']
        self.proxy = proxy

    def get_success_info(self):
        return self.cookie, self.user_agent, self.proxy
