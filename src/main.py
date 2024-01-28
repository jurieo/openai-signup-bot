import threading
import time

from config import signup_worker_num
from pool_manager import ThreadPoolManager
from signup import run_sign_up
from state_manager import GlobalStateManager


def main():
    sm = GlobalStateManager()

    while not sm.should_stop():
        # 执行注册任务
        run_sign_up(sm)


if __name__ == "__main__":
    main()
